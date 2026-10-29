"""Google Gemini client (REST, no vendor SDK required)."""

from __future__ import annotations

import asyncio
import random
import re
import time

import httpx

from ..config import settings
from .base import LLMClient, LLMError

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class RateLimiter:
    """A simple request-per-minute throttle.

    The free tier allows on the order of ten requests a minute. One full debate
    over eight candidates is twenty-five calls, fired in bursts — so without a
    throttle the very first query exhausts the minute's budget and everything
    after it returns 429. Pacing the calls is far better than retrying them:
    a retried 429 has already cost the wall-clock time.
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._times: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.per_minute <= 0:
            return
        async with self._lock:
            while True:
                now = time.monotonic()
                self._times = [t for t in self._times if now - t < 60.0]
                if len(self._times) < self.per_minute:
                    self._times.append(now)
                    return
                wait = 60.0 - (now - self._times[0]) + 0.05
                await asyncio.sleep(max(wait, 0.05))


_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


def _suggested_delay(body: str, attempt: int) -> float:
    """Google returns a retryDelay in the 429 body. Honour it when present."""
    match = _RETRY_DELAY.search(body or "")
    if match:
        return min(float(match.group(1)) + 0.4, 65.0)
    return min(2.0 * (2 ** attempt) + random.uniform(0, 1.2), 45.0)


class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__()
        self.api_keys = [api_key] if api_key else settings.gemini_api_keys
        self.model = model or settings.gemini_model
        if not self.api_keys:
            raise LLMError(
                "GEMINI_API_KEY is not set. Run `python setup_key.py` to add one."
            )
        self._resolved = False
        self.limiter = RateLimiter(settings.gemini_rpm * len(self.api_keys))
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0))
        self._key_index = 0

    async def resolve_model(self) -> str:
        """Find a model this key can actually use, and remember it.

        Called when a configured model returns 404 — usually because the ID in
        .env has been retired. Self-healing here matters because the alternative
        is a silent fall back to the rule-based agents, which looks like the
        system working rather than like a misconfiguration.
        """
        if self._resolved:
            return self.model
        from .check import list_models, pick_model

        models, error = await list_models(self.api_keys[0])
        if error or not models:
            self._resolved = True
            return self.model
        chosen = pick_model(models)
        if chosen:
            print(f"[llm] {self.model!r} is unavailable; switching to {chosen!r}.")
            self.model = chosen
        self._resolved = True
        return self.model

    async def _generate(self, system_prompt: str, user_prompt: str, *, json_mode: bool, model: str | None) -> str:
        target = model or self.model
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.35,
                "topP": 0.9,
                "maxOutputTokens": 1600,
                **({"responseMimeType": "application/json"} if json_mode else {}),
            },
        }
        url = f"{BASE}/{target}:generateContent"
        last_error = ""
        for attempt in range(5):
            await self.limiter.acquire()
            key_to_use = self.api_keys[self._key_index % len(self.api_keys)]
            self._key_index += 1
            try:
                resp = await self._client.post(url, params={"key": key_to_use}, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
                await asyncio.sleep(1.2 * (attempt + 1))
                continue

            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    raise LLMError(f"Gemini returned no candidates: {str(data)[:300]}")
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                if not text.strip():
                    raise LLMError("Gemini returned an empty completion")
                return text

            if resp.status_code == 429:
                if "exceeded your current quota" in resp.text.lower():
                    raise LLMError("API keys have hit their daily quota limit.")
                if attempt >= 1:
                    raise LLMError("API rate limit hit. Switch to Mock mode to continue instantly.")
                last_error = f"HTTP 429 (rate limited): {resp.text[:160]}"
                await asyncio.sleep(_suggested_delay(resp.text, attempt))
                continue

            if resp.status_code in (500, 502, 503, 504):
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                await asyncio.sleep(min(1.5 * (2 ** attempt), 20.0) + random.uniform(0, 0.8))
                continue

            if resp.status_code == 404 and not model:
                # The configured model ID no longer exists. Discover a live one
                # and retry against it rather than failing the request.
                resolved = await self.resolve_model()
                if resolved != target:
                    target = resolved
                    url = f"{BASE}/{target}:generateContent"
                    continue

            if resp.status_code in (401, 403):
                raise LLMError(
                    f"Gemini rejected the API key (HTTP {resp.status_code}). "
                    "Run `python setup_key.py --check` to diagnose it."
                )

            raise LLMError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")

        raise LLMError(f"Gemini unavailable after retries — {last_error}")

    async def close(self) -> None:
        await self._client.aclose()
