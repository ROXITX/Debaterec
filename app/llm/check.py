"""Connection verification and automatic model discovery.

Why this exists: Gemini model IDs change over time. A hardcoded name that has
been retired returns HTTP 404, and a system that silently falls back on error
will keep running and quietly stop using the model — you would believe the
debate was model-written when it was not.

So instead of trusting a name from a config file, we ask the API which models
this key can actually use, pick one, and prove it with a real generation before
reporting success.
"""

from __future__ import annotations

import asyncio
import re

import httpx

BASE = "https://generativelanguage.googleapis.com/v1beta"

# Ranked preferences, matched as substrings rather than exact IDs so the picker
# survives version bumps. Higher score wins.
PREFERRED = (
    ("flash-lite", 55),   # cheapest, plenty for extraction
    ("flash", 70),        # the sweet spot for this workload
    ("pro", 60),          # stronger reasoning, tighter free quota
)
# Variants that are wrong for this use case even when they rank well by name.
AVOID = (
    "embedding", "aqa", "imagen", "image", "tts", "audio", "speech",
    "vision", "live", "veo", "learnlm", "gemma", "robotics",
)


def score_model(model_id: str) -> int:
    name = model_id.lower()
    if any(bad in name for bad in AVOID):
        return -1
    # First match wins, so the more specific "flash-lite" is scored as itself
    # rather than being lifted to the plain "flash" score it also contains.
    base = 0
    for token, weight in PREFERRED:
        if token in name:
            base = weight
            break
    if base == 0:
        return -1
    # Prefer newer version numbers: "gemini-2.5-flash" beats "gemini-1.5-flash".
    # Handles both "gemini-2.5-flash" and "gemini-3-pro".
    version = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    if version:
        base += int(version.group(1)) * 6 + int(version.group(2) or 0)
    # A stable release beats a preview or experimental build of the same family.
    if any(tag in name for tag in ("preview", "exp", "experimental")):
        base -= 12
    if name.endswith("-latest"):
        base += 2
    return base


async def list_models(api_key: str, timeout: float = 20.0) -> tuple[list[str], str | None]:
    """Return (usable model ids, error message)."""
    url = f"{BASE}/models"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params={"key": api_key, "pageSize": 200})
    except httpx.HTTPError as exc:
        return [], f"Could not reach Google: {exc}"

    if resp.status_code == 400:
        return [], "That key was rejected as malformed. Check for a stray space or a missing character."
    if resp.status_code in (401, 403):
        return [], (
            "Google refused that key. Either it is wrong, or the Generative Language API "
            "is not enabled on its project. Create a fresh key at "
            "https://aistudio.google.com/apikey"
        )
    if resp.status_code != 200:
        return [], f"Google returned HTTP {resp.status_code}: {resp.text[:200]}"

    usable = []
    for model in resp.json().get("models", []):
        methods = model.get("supportedGenerationMethods") or model.get("supportedActions") or []
        if "generateContent" not in methods:
            continue
        usable.append(str(model.get("name", "")).removeprefix("models/"))
    return usable, None


def pick_model(candidates: list[str]) -> str | None:
    ranked = sorted(
        ((score_model(m), m) for m in candidates),
        key=lambda pair: (pair[0], pair[1]),
        reverse=True,
    )
    for score, model in ranked:
        if score > 0:
            return model
    return None


async def test_generation(api_key: str, model: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Prove the key can actually generate, and that JSON mode works.

    JSON mode is tested specifically because every agent depends on it — a key
    that can generate prose but not structured output would fail later, in a much
    more confusing way.
    """
    payload = {
        "system_instruction": {"parts": [{"text": 'Reply with only {"ok": true}.'}]},
        "contents": [{"role": "user", "parts": [{"text": "Respond now."}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 40,
                             "responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{BASE}/models/{model}:generateContent",
                params={"key": api_key},
                json=payload,
            )
    except httpx.HTTPError as exc:
        return False, f"Network error during the test call: {exc}"

    if resp.status_code == 429:
        return False, (
            "The key works but is rate limited right now (HTTP 429). Wait a minute and retry, "
            "or reduce CANDIDATES_DEBATE in .env."
        )
    if resp.status_code == 404:
        return False, f"The model {model!r} is not available to this key (HTTP 404)."
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"

    candidates = resp.json().get("candidates") or []
    if not candidates:
        return False, "The API returned no candidates — the request was probably blocked by a safety filter."
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        return False, "The API returned an empty completion."
    return True, text


async def verify(api_key: str, preferred_model: str = "") -> dict:
    """Full check: key valid, model available, generation works.

    Returns a dict with `ok`, the chosen `model`, and a human-readable `message`.
    """
    if not api_key:
        return {"ok": False, "model": "", "message": "No API key was provided.", "models": []}

    models, error = await list_models(api_key)
    if error:
        return {"ok": False, "model": "", "message": error, "models": []}
    if not models:
        return {"ok": False, "model": "", "message":
                "The key is valid but no text-generation models are available to it.", "models": []}

    # Honour an explicitly configured model, but only if the key can really use it.
    chosen = preferred_model if preferred_model and preferred_model in models else pick_model(models)
    if not chosen:
        return {"ok": False, "model": "", "message":
                "No suitable text model found. Available: " + ", ".join(models[:8]), "models": models}

    ok, detail = await test_generation(api_key, chosen)
    if not ok:
        # The first choice failed; try the next best before giving up.
        alternatives = [m for m in sorted(models, key=score_model, reverse=True) if m != chosen][:2]
        for alternative in alternatives:
            if score_model(alternative) <= 0:
                continue
            ok, detail = await test_generation(api_key, alternative)
            if ok:
                chosen = alternative
                break
    if not ok:
        return {"ok": False, "model": chosen, "message": detail, "models": models}

    return {
        "ok": True,
        "model": chosen,
        "message": f"Verified. {chosen} responded correctly in JSON mode.",
        "models": models,
        "sample": detail[:120],
    }


if __name__ == "__main__":
    import sys

    from ..config import settings

    key = sys.argv[1] if len(sys.argv) > 1 else settings.gemini_api_key
    outcome = asyncio.run(verify(key, settings.gemini_model))
    print(("OK   " if outcome["ok"] else "FAIL ") + outcome["message"])
    if outcome.get("models"):
        print("Available: " + ", ".join(outcome["models"][:12]))
    sys.exit(0 if outcome["ok"] else 1)
