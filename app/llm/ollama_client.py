"""Ollama client — local, offline, no API key (PRD §72)."""

from __future__ import annotations

import httpx

from ..config import settings
from .base import LLMClient, LLMError


class OllamaClient(LLMClient):
    name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        super().__init__()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))

    async def _generate(self, system_prompt: str, user_prompt: str, *, json_mode: bool, model: str | None) -> str:
        payload = {
            "model": model or self.model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {"temperature": 0.35, "top_p": 0.9, "num_predict": 1200},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            resp = await self._client.post(f"{self.base_url}/api/generate", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Could not reach Ollama at {self.base_url}. Is `ollama serve` running? ({exc})"
            ) from exc
        if resp.status_code != 200:
            raise LLMError(f"Ollama HTTP {resp.status_code}: {resp.text[:300]}")
        text = resp.json().get("response", "")
        if not text.strip():
            raise LLMError("Ollama returned an empty completion")
        return text

    async def close(self) -> None:
        await self._client.aclose()
