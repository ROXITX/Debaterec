"""The end-to-end pipeline (PRD §74), as an async event stream.

    understand -> retrieve -> filter -> shortlist -> debate -> judge -> rank

Every stage emits an event. The HTTP layer forwards those events to the browser
over SSE, which is what lets the interface show the debate happening rather than
a spinner followed by a list. The same generator is used by the evaluation
harness with the events discarded, so there is exactly one implementation of the
pipeline and the numbers in the report describe the code that actually runs.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from .agents.debate import DebateEngine
from .config import settings
from .domains.registry import get_adapter, load_domain
from .llm.base import LLMClient
from .llm.factory import create_llm, llm_status
from .nlp.preferences import spec_debug, understand
from .recommender.retrieval import diversify, intra_list_diversity, retrieve
from .schemas import DebateResult, QuerySpec


async def recommend_stream(
    query: str,
    domain: str = "auto",
    top_k: int | None = None,
    method: str = "debate",
    llm: LLMClient | None = None,
    curated_only: bool = False,
) -> AsyncIterator[dict]:
    started = time.perf_counter()
    top_k = top_k or settings.results_final
    llm = llm if llm is not None else create_llm()
    if method in {"retrieval"}:
        llm = None

    # ---- stage 1: understand ------------------------------------------------
    yield {"type": "stage", "stage": "understanding", "status": "start",
           "label": "Reading your request"}
    t0 = time.perf_counter()
    try:
        spec: QuerySpec = await understand(query, domain, llm)
    except KeyError as exc:
        yield {"type": "error", "message": f"Unknown domain {exc}."}
        return
    except Exception as exc:
        if "rate limit" in str(exc).lower() or "quota" in str(exc).lower():
            yield {"type": "error", "message": str(exc)}
            return
        raise
    adapter = get_adapter(spec.domain)
    nlp_seconds = round(time.perf_counter() - t0, 3)

    yield {
        "type": "stage", "stage": "understanding", "status": "end",
        "seconds": nlp_seconds,
        "domain": spec.domain, "domain_label": adapter.label, "accent": adapter.accent,
        "icon": adapter.icon,
        "understanding": spec_debug(spec),
    }

    # ---- stage 2: retrieve --------------------------------------------------
    pool_size = len(load_domain(spec.domain, curated_only))
    yield {"type": "stage", "stage": "retrieval", "status": "start",
           "label": f"Searching {pool_size:,} {adapter.label.lower()}"}
    t0 = time.perf_counter()
    result = retrieve(spec, curated_only=curated_only)
    shortlist = diversify(result.candidates, settings.candidates_debate)
    retrieval_seconds = round(time.perf_counter() - t0, 3)

    if not shortlist:
        yield {"type": "error",
               "message": f"Nothing in the {adapter.label.lower()} catalogue matches that request."}
        return

    yield {
        "type": "stage", "stage": "retrieval", "status": "end",
        "seconds": retrieval_seconds,
        "pool": result.pool_size,
        "filtered_out": result.filtered_out,
        "relaxed": result.relaxed,
        "stage1": result.stage1_size,
        "shortlist": [
            {
                "item_id": c.item.item_id, "title": c.item.title, "subtitle": c.item.subtitle,
                "score": c.hybrid, "semantic": c.semantic, "metadata": c.metadata,
                "accent": c.item.accent,
            }
            for c in shortlist
        ],
    }
    if result.relaxed:
        yield {
            "type": "notice",
            "message": "No option satisfies every hard requirement, so the filter was relaxed. "
                       "The conflicts are shown on each card.",
        }

    # ---- stage 3: debate ----------------------------------------------------
    engine = DebateEngine(llm)
    yield {
        "type": "stage", "stage": "debate", "status": "start",
        "label": f"{len(shortlist)} candidates enter the debate",
        "mode": engine.mode, "provider": llm_status(),
        "rounds": ["supporter", "critic"] + (["rebuttal"] if settings.debate_rebuttal else []) + ["judge"],
    }
    t0 = time.perf_counter()
    results: list[DebateResult] = []
    try:
        async for event in _stream_debate(engine, spec, shortlist, method, results):
            yield event
    except Exception as exc:
        if "rate limit" in str(exc).lower() or "quota" in str(exc).lower():
            yield {"type": "error", "message": str(exc)}
            return
        raise
    debate_seconds = round(time.perf_counter() - t0, 3)
    yield {"type": "stage", "stage": "debate", "status": "end", "seconds": debate_seconds}

    # If a model was configured but its calls failed, say so. Silently serving
    # rule-written arguments while the interface claims to be using an LLM is
    # the single most misleading thing this system could do.
    degraded = bool(llm is not None and llm.usage.failures)
    if degraded:
        yield {
            "type": "notice",
            "message": (
                f"{llm.usage.failures} model call(s) failed, so those candidates fell back to the "
                "deterministic agents. Run `python setup_key.py --check` to diagnose it."
            ),
        }

    # ---- stage 4: rank ------------------------------------------------------
    yield {"type": "stage", "stage": "ranking", "status": "start", "label": "Ranking the verdicts"}
    results.sort(key=lambda r: (r.judge.decision == "reject", -r.final_score, -r.judge.confidence))
    final = results[:top_k]
    for i, r in enumerate(final, start=1):
        r.rank = i

    cards = [r.as_card() for r in final]
    for card in cards:
        yield {"type": "result", "card": card}
    yield {"type": "stage", "stage": "ranking", "status": "end", "seconds": 0.001}

    total = round(time.perf_counter() - started, 3)
    usage = llm.usage.as_dict() if llm is not None else {"llm_calls": 0}
    yield {
        "type": "done",
        "domain": spec.domain,
        "domain_label": adapter.label,
        "method": method,
        "mode": engine.mode,
        "pool": "curated" if curated_only else "full",
        "provider": llm_status(),
        "results": cards,
        "metrics": {
            "total_seconds": total,
            "nlp_seconds": nlp_seconds,
            "retrieval_seconds": retrieval_seconds,
            "debate_seconds": debate_seconds,
            "catalogue_size": result.pool_size,
            "stage1_candidates": result.stage1_size,
            "debated_candidates": len(shortlist),
            "returned": len(final),
            "intra_list_diversity": intra_list_diversity([r.item for r in final]),
            "degraded": degraded,
            **usage,
        },
        "understanding": spec_debug(spec),
    }


async def _stream_debate(engine, spec, shortlist, method, sink: list[DebateResult]):
    """Run the debate in the background and forward its events as they happen.

    A queue rather than a list is what makes this genuinely live: the browser
    sees "Critic is examining Pixel 8a" while that call is still in flight,
    instead of receiving the whole transcript once the work is already over.
    """
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def emit(payload: dict) -> None:
        await queue.put(payload)

    worker = asyncio.create_task(engine.run(spec, shortlist, method=method, emit=emit))

    while True:
        getter = asyncio.create_task(queue.get())
        done, _pending = await asyncio.wait({getter, worker}, return_when=asyncio.FIRST_COMPLETED)
        if getter in done:
            yield getter.result()
            continue
        getter.cancel()
        break

    while not queue.empty():
        yield queue.get_nowait()

    sink.extend(await worker)


async def recommend(
    query: str,
    domain: str = "auto",
    top_k: int | None = None,
    method: str = "debate",
    llm: LLMClient | None = None,
    curated_only: bool = False,
) -> dict:
    """Non-streaming convenience wrapper — used by /recommend and by evaluation."""
    payload: dict = {}
    async for event in recommend_stream(query, domain, top_k, method, llm, curated_only):
        if event.get("type") == "done":
            payload = event
        elif event.get("type") == "error":
            raise ValueError(event["message"])
    return payload
