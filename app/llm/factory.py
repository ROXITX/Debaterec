"""Builds the configured LLM client.

Returning `None` is a first-class outcome, not an error: it means "run the
deterministic debate". Every agent has a rule-based fallback that reasons from
the code-computed constraint audit, so the application is fully usable with no
API key and no local model — which is also exactly what the no-LLM ablation
condition needs (PRD §46, Experiment A).
"""

from __future__ import annotations

from ..config import settings
from .base import LLMClient

_client: LLMClient | None = None
_built = False
_status: str = "not initialised"


def create_llm(force: bool = False) -> LLMClient | None:
    global _client, _built, _status
    if _built and not force:
        return _client

    _built = True
    provider = settings.llm_provider

    if provider == "mock":
        _client, _status = None, "deterministic mode (LLM_PROVIDER=mock)"
        return None

    if provider == "gemini":
        if not settings.gemini_api_key:
            _client = None
            _status = "no GEMINI_API_KEY found — running the deterministic debate instead"
            return None
        try:
            from .gemini_client import GeminiClient

            _client = GeminiClient()
            _status = f"gemini · {settings.gemini_model}"
        except Exception as exc:  # noqa: BLE001 - never let config kill the server
            _client, _status = None, f"gemini unavailable ({exc}) — deterministic mode"
        return _client

    if provider == "ollama":
        try:
            from .ollama_client import OllamaClient

            _client = OllamaClient()
            _status = f"ollama · {settings.ollama_model}"
        except Exception as exc:  # noqa: BLE001
            _client, _status = None, f"ollama unavailable ({exc}) — deterministic mode"
        return _client

    _client, _status = None, f"unknown provider {provider!r} — deterministic mode"
    return None


def llm_status() -> str:
    if not _built:
        create_llm()
    return _status


async def verify_llm() -> dict:
    """Prove the configured provider works, once, at startup.

    Running this at boot rather than lazily means the console banner and the
    status pill tell the truth from the first page load. A key that is present
    but rejected is a much more common situation than a key that is absent, and
    it is the one that silently degrades.
    """
    global _status
    client = create_llm()
    if client is None:
        return {"ok": False, "provider": settings.llm_provider, "message": _status, "verified": False}

    if settings.llm_provider == "gemini":
        from .check import verify

        result = await verify(settings.gemini_api_key, settings.gemini_model)
        if result["ok"]:
            # Adopt whatever the check proved actually works.
            client.model = result["model"]  # type: ignore[attr-defined]
            client._resolved = True  # type: ignore[attr-defined]
            _status = f"gemini · {result['model']}"
            return {"ok": True, "provider": "gemini", "model": result["model"],
                    "message": result["message"], "verified": True}
        _status = f"gemini unavailable — {result['message'][:80]}"
        return {"ok": False, "provider": "gemini", "message": result["message"], "verified": True}

    if settings.llm_provider == "ollama":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=8.0) as http:
                resp = await http.get(f"{settings.ollama_base_url}/api/tags")
            names = [m.get("name", "") for m in resp.json().get("models", [])]

            # Match leniently: Ollama reports "llama3.1:8b" but a config value of
            # "llama3.1" (or vice-versa via the implicit ":latest" tag) is the
            # same model. Comparing exact strings falsely reported it as missing.
            def _base(tag: str) -> str:
                return tag.split(":", 1)[0]

            want = settings.ollama_model
            if want not in names and not any(
                n == want or _base(n) == _base(want) for n in names
            ):
                _status = f"ollama reachable but {want} is not pulled"
                return {"ok": False, "provider": "ollama", "message":
                        f"Run: ollama pull {want}", "verified": True}
            _status = f"ollama · {settings.ollama_model}"
            return {"ok": True, "provider": "ollama", "model": settings.ollama_model,
                    "message": "Ollama is reachable.", "verified": True}
        except Exception as exc:  # noqa: BLE001
            _status = f"ollama unreachable ({exc})"
            return {"ok": False, "provider": "ollama", "message": str(exc), "verified": True}

    return {"ok": True, "provider": settings.llm_provider, "message": _status, "verified": False}


async def shutdown_llm() -> None:
    global _client, _built
    if _client is not None:
        await _client.close()
    _client, _built = None, False
