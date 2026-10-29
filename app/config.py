"""Central configuration.

Every tunable lives here so experiments (RQ5: latency/cost vs. debate depth)
can be run by changing environment variables rather than editing code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that contains app/, data/, frontend/
ROOT = Path(__file__).resolve().parent.parent

# Load .env if present; real environment variables always win.
load_dotenv(ROOT / ".env", override=False)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


# NOTE: intentionally NOT frozen. The provider (and the local model name) can be
# switched at runtime from the UI's online/offline toggle via /api/settings/llm,
# which assigns to these fields. A frozen dataclass raised FrozenInstanceError
# there and crashed the switch, silently trapping the app in one provider.
@dataclass
class Settings:
    # --- paths (all resolved with pathlib so Windows backslashes are handled) --
    root: Path = ROOT
    data_raw: Path = ROOT / "data" / "raw"
    data_processed: Path = ROOT / "data" / "processed"
    prompts_dir: Path = ROOT / "prompts"
    frontend_dir: Path = ROOT / "frontend"

    # --- llm ---------------------------------------------------------------
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "gemini").strip().lower())
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip())
    gemini_judge_model: str = field(default_factory=lambda: os.getenv("GEMINI_JUDGE_MODEL", "").strip())
    # Requests per minute. The free tier is roughly 10-15; one full debate over
    # eight candidates is 25 calls, so without pacing the first query burns the
    # minute's quota and everything after it is rejected. 0 disables the throttle.
    gemini_rpm: int = field(default_factory=lambda: _int("GEMINI_RPM", 10))
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip())
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip())

    # --- retrieval ---------------------------------------------------------
    retrieval_mode: str = field(default_factory=lambda: os.getenv("RETRIEVAL_MODE", "lexical").strip().lower())
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2").strip()
    )
    # HybridScore = alpha * semantic + (1 - alpha) * metadata   (PRD §37)
    hybrid_alpha: float = 0.70

    # --- pipeline sizing ---------------------------------------------------
    candidates_stage1: int = field(default_factory=lambda: _int("CANDIDATES_STAGE1", 50))
    candidates_debate: int = field(default_factory=lambda: _int("CANDIDATES_DEBATE", 8))
    results_final: int = field(default_factory=lambda: _int("RESULTS_FINAL", 5))
    debate_rebuttal: bool = field(default_factory=lambda: _bool("DEBATE_REBUTTAL", False))

    # --- scoring weights (PRD §19) — treat as tunable hyperparameters -------
    # The PRD's starting point is 0.35/0.25/0.20/0.10/0.10. That weighting was
    # measured to be too kind to items that read well but miss a stated
    # preference, so constraint and preference satisfaction carry more here.
    # `evaluation/experiments.py` sweeps these; they are not settled values.
    w_retrieval: float = 0.28
    w_support: float = 0.22
    w_evidence: float = 0.15
    w_constraint: float = 0.20
    w_preference: float = 0.15
    critic_penalty_lambda: float = 1.1

    # Decision boundaries for the judge's verdict.
    threshold_recommend: float = 8.2
    threshold_consider: float = 6.0

    # --- server ------------------------------------------------------------
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1").strip())
    port: int = field(default_factory=lambda: _int("PORT", 8000))

    @property
    def llm_ready(self) -> bool:
        """True when the configured provider actually has what it needs."""
        if self.llm_provider == "gemini":
            return bool(self.gemini_api_keys)
        if self.llm_provider == "ollama":
            return True  # reachability is checked lazily at call time
        return True  # mock

    @property
    def gemini_api_keys(self) -> list[str]:
        return [k.strip() for k in self.gemini_api_key.split(",") if k.strip()]

    def describe(self) -> dict:
        return {
            "llm_provider": self.llm_provider,
            "llm_ready": self.llm_ready,
            "model": self.gemini_model if self.llm_provider == "gemini" else self.ollama_model,
            "retrieval_mode": self.retrieval_mode,
            "candidates_stage1": self.candidates_stage1,
            "candidates_debate": self.candidates_debate,
            "results_final": self.results_final,
            "rebuttal_enabled": self.debate_rebuttal,
        }

    def apply_llm(self, provider: str, *, ollama_model: str | None = None,
                  persist: bool = True) -> None:
        """Switch the active LLM backend at runtime (online ⇆ offline).

        Backs the UI toggle. `persist=True` also writes the choice to .env so a
        server restart keeps the mode the user last selected, rather than
        silently reverting to whatever the file said at boot.
        """
        provider = (provider or "").strip().lower()
        if provider not in {"gemini", "ollama", "mock"}:
            raise ValueError(f"unknown provider {provider!r}")
        self.llm_provider = provider
        updates = {"LLM_PROVIDER": provider}
        if provider == "ollama" and ollama_model:
            self.ollama_model = ollama_model.strip()
            updates["OLLAMA_MODEL"] = self.ollama_model
        if persist:
            persist_env(updates)


def persist_env(updates: dict[str, str]) -> None:
    """Write KEY=value pairs into .env, preserving everything else.

    Kept here (rather than only in setup_key.py) so the running server can
    remember a mode switch without shelling out to the setup script.
    """
    import re

    env_path = ROOT / ".env"
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    for key, value in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(f"{key}={value}", text)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{key}={value}\n"
    env_path.write_text(text, encoding="utf-8")


settings = Settings()
