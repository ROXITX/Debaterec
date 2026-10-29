"""FastAPI application (PRD §51).

Serves both the JSON API and the frontend, so the whole system is one process
and one command on Windows, macOS and Linux alike.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import store
from .config import settings
from .domains.registry import REGISTRY, catalogue
from .llm.factory import create_llm, llm_status, shutdown_llm, verify_llm
from .nlp.preferences import understand
from .pipeline import recommend, recommend_stream
from .recommender.index import warm_all
from .schemas import FeedbackRequest, RecommendRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    counts = await asyncio.get_running_loop().run_in_executor(None, warm_all)
    create_llm()

    # Prove the provider works before serving a single page, so the banner and
    # the status pill never claim a capability the system does not have.
    app.state.llm_check = await verify_llm()

    total = sum(counts.values())
    print("\n  DebateRec is ready.")
    print(f"  Catalogue : {total} items across {len(counts)} domains — "
          + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"  Reasoning : {llm_status()}")
    check = app.state.llm_check
    if check.get("verified") and not check.get("ok"):
        print(f"\n  The LLM is configured but NOT working: {check['message']}")
        print("  DebateRec will run the deterministic agents instead.")
        print("  Diagnose it with:  python setup_key.py --check\n")
    print(f"  Open      : http://{settings.host}:{settings.port}\n")
    yield
    await shutdown_llm()


app = FastAPI(
    title="DebateRec",
    description="Evidence-grounded, debate-based multi-domain recommendation.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    check = getattr(app.state, "llm_check", {})
    return {
        "status": "ok",
        "config": settings.describe(),
        "provider": llm_status(),
        "llm": {
            "ok": bool(check.get("ok")),
            "model": check.get("model", ""),
            "message": check.get("message", ""),
            "verified": bool(check.get("verified")),
        },
        "store": store.stats(),
    }


@app.post("/api/verify-llm")
async def reverify():
    """Re-check the provider without restarting the server — so a key added to
    .env can be picked up by pressing a button rather than killing the process."""
    from .llm.factory import shutdown_llm as _shutdown

    await _shutdown()
    create_llm(force=True)
    app.state.llm_check = await verify_llm()
    return {**app.state.llm_check, "provider": llm_status()}

from pydantic import BaseModel
from typing import Literal, Optional

class LLMProviderRequest(BaseModel):
    provider: Literal["gemini", "ollama", "mock"]
    # Optional: when switching to offline mode, pick which pulled Ollama model
    # to reason with (e.g. "llama3.1:8b"). Ignored for the other providers.
    model: Optional[str] = None

@app.post("/api/settings/llm")
async def set_llm_provider(payload: LLMProviderRequest):
    """Flip the active reasoning backend from the UI — online (Gemini) to
    offline (Ollama) or the deterministic mock — without a restart.

    The choice is persisted to .env so it survives the next launch. This is the
    endpoint that the frozen-dataclass bug used to crash on."""
    settings.apply_llm(payload.provider, ollama_model=payload.model)

    from .llm.factory import shutdown_llm as _shutdown
    await _shutdown()
    create_llm(force=True)
    app.state.llm_check = await verify_llm()
    return {**app.state.llm_check, "provider": llm_status()}


@app.get("/api/ollama/models")
async def ollama_models():
    """List the models actually pulled into the local Ollama daemon, so the UI
    can offer a real choice for offline mode instead of a hardcoded guess.

    Returns reachable=False (rather than an error) when the daemon is not
    running, so the frontend can show a helpful hint instead of a broken list.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=6.0) as http:
            resp = await http.get(f"{settings.ollama_base_url}/api/tags")
        models = [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
        return {"reachable": True, "current": settings.ollama_model, "models": models}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "current": settings.ollama_model,
                "models": [], "message": str(exc)}


@app.get("/api/domains")
async def domains():
    return {"domains": catalogue()}


@app.post("/api/understand")
async def understand_only(payload: RecommendRequest):
    """Exposes the NLP layer on its own, so preference extraction can be
    evaluated independently of retrieval and debate."""
    from .nlp.preferences import spec_debug

    try:
        spec = await understand(payload.query, payload.domain, create_llm())
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown domain {exc}") from exc
    return spec_debug(spec)


@app.post("/api/recommend")
async def recommend_endpoint(payload: RecommendRequest):
    try:
        result = await recommend(payload.query, payload.domain, payload.top_k, payload.method,
                                 curated_only=payload.curated_only)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown domain {exc}") from exc
    store.log_request(payload.session_id, payload.query, result)
    return result


@app.get("/api/recommend/stream")
async def recommend_sse(
    request: Request,
    query: str,
    domain: str = "auto",
    top_k: int = 5,
    method: str = "debate",
    session_id: str = "anon",
    curated_only: bool = False,
):
    """Server-Sent Events: the interface watches the pipeline work.

    SSE rather than WebSockets because the traffic is one-directional, it needs
    no extra dependency, and it reconnects on its own.
    """

    async def event_source():
        final: dict = {}
        try:
            async for event in recommend_stream(query, domain, top_k, method,
                                                curated_only=curated_only):
                if await request.is_disconnected():
                    break
                if event.get("type") == "done":
                    final = event
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # noqa: BLE001 - a stream must always terminate cleanly
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        finally:
            if final:
                try:
                    store.log_request(session_id, query, final)
                except Exception:  # noqa: BLE001
                    pass

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/feedback")
async def feedback_endpoint(payload: FeedbackRequest):
    """Records feedback and turns free-text comments into stored preferences
    (PRD §25). Natural-language feedback goes through the same extractor as the
    original query, so "I liked it but I don't want slow-paced films" becomes a
    negative tone preference rather than an uninterpretable string."""
    store.log_feedback(payload.session_id, payload.item_id, payload.domain,
                       payload.feedback, payload.comment)

    learned: list[str] = []
    if payload.comment.strip() and payload.domain in REGISTRY:
        spec = await understand(payload.comment, payload.domain, create_llm())
        for c in spec.categorical:
            for value in c.exclude:
                store.save_preference(payload.session_id, payload.domain, c.facet, f"-{value}", 0.85, "feedback")
                learned.append(f"avoid {value}")
            for value in c.include:
                store.save_preference(payload.session_id, payload.domain, c.facet, value, 0.7, "feedback")
                learned.append(f"prefers {value}")
        for n in spec.numeric:
            store.save_preference(payload.session_id, payload.domain, n.facet, n.human(), n.importance, "feedback")
            learned.append(n.human())

    return {"status": "recorded", "learned": learned[:6]}


@app.get("/api/memory")
async def memory(session_id: str = "anon", domain: str = "movie"):
    return {"session_id": session_id, "domain": domain,
            "preferences": store.session_memory(session_id, domain)}


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

if settings.frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(settings.frontend_dir / "index.html")

    @app.get("/favicon.ico")
    async def favicon():
        path = settings.frontend_dir / "assets" / "favicon.svg"
        if path.exists():
            return FileResponse(path)
        return JSONResponse({}, status_code=404)
