"""Provider-agnostic LLM interface (PRD §32).

Everything above this file talks to `LLMClient`. Swapping Gemini for a local
Ollama model — or for the deterministic mock used in tests — is a config change,
not a code change, which is what makes the model-strategy experiments in PRD §71
possible at all.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMUsage:
    """Per-request telemetry — feeds the latency/cost experiments (PRD §47)."""

    calls: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    seconds: float = 0.0
    retries: int = 0
    failures: int = 0
    by_role: dict[str, int] = field(default_factory=dict)

    def record(self, role: str, prompt: str, completion: str, seconds: float) -> None:
        self.calls += 1
        self.prompt_chars += len(prompt)
        self.completion_chars += len(completion)
        self.seconds += seconds
        self.by_role[role] = self.by_role.get(role, 0) + 1

    def as_dict(self) -> dict:
        # ~4 characters per token is the usual rough conversion.
        return {
            "llm_calls": self.calls,
            "approx_prompt_tokens": self.prompt_chars // 4,
            "approx_completion_tokens": self.completion_chars // 4,
            "llm_seconds": round(self.seconds, 2),
            "retries": self.retries,
            "parse_failures": self.failures,
            "calls_by_role": self.by_role,
        }


class LLMError(RuntimeError):
    pass


class LLMClient(ABC):
    name: str = "base"

    def __init__(self) -> None:
        self.usage = LLMUsage()

    @abstractmethod
    async def _generate(self, system_prompt: str, user_prompt: str, *, json_mode: bool, model: str | None) -> str: ...

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        role: str = "generic",
        json_mode: bool = True,
        model: str | None = None,
    ) -> str:
        started = time.perf_counter()
        text = await self._generate(system_prompt, user_prompt, json_mode=json_mode, model=model)
        self.usage.record(role, system_prompt + user_prompt, text, time.perf_counter() - started)
        return text

    async def structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        *,
        role: str = "generic",
        model: str | None = None,
        retries: int = 1,
    ) -> T | None:
        """Generate and validate against a Pydantic model (PRD §34).

        On a parse failure we retry once with the validation error fed back to
        the model, then give up and return None so the caller can fall back to a
        deterministic result rather than crash the request.
        """
        prompt = user_prompt
        for attempt in range(retries + 1):
            try:
                raw = await self.generate(system_prompt, prompt, role=role, json_mode=True, model=model)
                payload = extract_json(raw)
                return schema.model_validate(payload)
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                if attempt >= retries:
                    self.usage.failures += 1
                    return None
                self.usage.retries += 1
                prompt = (
                    f"{user_prompt}\n\n---\nYour previous reply could not be parsed.\n"
                    f"Error: {str(exc)[:400]}\n"
                    "Reply again with ONLY a single valid JSON object and no other text."
                )
            except LLMError as exc:
                if "rate limit" in str(exc).lower() or "quota" in str(exc).lower():
                    raise
                self.usage.failures += 1
                return None
        return None

    async def close(self) -> None:  # pragma: no cover - overridden where needed
        return None


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Recover a JSON object from a reply that may be fenced or chatty."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start: end + 1]
        # Trailing commas are the single most common malformation.
        candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
        return json.loads(candidate)
    raise ValueError(f"no JSON object found in response: {text[:200]}")


async def gather_limited(coros: list, limit: int = 6) -> list:
    """Run coroutines concurrently with a ceiling, so a wide debate does not
    open forty simultaneous connections to the provider."""
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)
