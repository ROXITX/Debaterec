#!/usr/bin/env python3
"""Interactive API key setup.

    python setup_key.py

Prompts for a Gemini key, verifies it against the live API, discovers which
model that key can actually use, and writes .env. Nothing is written unless the
verification passes, so you cannot end up with a .env that looks configured but
does not work.

    python setup_key.py --check     verify what is already in .env
    python setup_key.py --ollama    switch to a local model instead
    python setup_key.py --mock      switch to deterministic mode
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def read_env() -> str:
    if ENV.exists():
        return ENV.read_text(encoding="utf-8")
    if EXAMPLE.exists():
        return EXAMPLE.read_text(encoding="utf-8")
    return "LLM_PROVIDER=gemini\nGEMINI_API_KEY=\nGEMINI_MODEL=\n"


def set_value(text: str, key: str, value: str) -> str:
    """Replace or append `KEY=value`, preserving the rest of the file."""
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(f"{key}={value}", text)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + f"{key}={value}\n"


def write_env(updates: dict[str, str]) -> None:
    text = read_env()
    for key, value in updates.items():
        text = set_value(text, key, value)
    ENV.write_text(text, encoding="utf-8")


def looks_like_a_key(value: str) -> bool:
    # Gemini keys are ~39 characters and begin with "AIza". Checked before any
    # network call so an obvious paste error gets an instant, specific answer.
    return bool(re.fullmatch(r"AIza[0-9A-Za-z_\-]{30,50}", value))


def rule() -> None:
    print("  " + "─" * 66)


async def configure_gemini() -> int:
    from app.llm.check import verify

    print("\n  Gemini setup")
    rule()
    print("  1. Open  https://aistudio.google.com/apikey")
    print("  2. Sign in with a Google account and click 'Create API key'")
    print("  3. Copy the key (it starts with AIza) and paste it below")
    print("\n  Nothing is saved until the key is verified against the live API.")
    print("  The key is written only to .env on this machine, which is gitignored.\n")

    try:
        key = input("  Paste your key: ").strip().strip('"').strip("'")
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.\n")
        return 1

    if not key:
        print("\n  Nothing entered. Cancelled.\n")
        return 1

    if not looks_like_a_key(key):
        print("\n  That does not look like a Gemini API key.")
        print("  A Gemini key starts with 'AIza' and is about 39 characters long.")
        print("  You may have copied a project ID or an OAuth client secret instead.")
        try:
            if input("  Try it anyway? [y/N] ").strip().lower() not in {"y", "yes"}:
                print("  Cancelled.\n")
                return 1
        except (EOFError, KeyboardInterrupt):
            return 1

    print("\n  Checking with Google…")
    result = await verify(key)

    if not result["ok"]:
        print("\n  Verification failed.")
        rule()
        print(f"  {result['message']}")
        if result.get("models"):
            print(f"\n  Models this key can see: {', '.join(result['models'][:8])}")
        print("\n  Nothing was written to .env.\n")
        return 1

    # Tune the cost knobs for a free-tier key. Eight debated candidates is 25
    # calls per query; on a ~10 rpm free tier that is two and a half minutes of
    # waiting for one search. Five candidates keeps the debate meaningful and the
    # wait tolerable. Both values are plain .env settings to raise later.
    write_env({
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": key,
        "GEMINI_MODEL": result["model"],
        "GEMINI_RPM": "10",
        "CANDIDATES_DEBATE": "5",
    })

    print("\n  Verified.")
    rule()
    print(f"  Model chosen : {result['model']}")
    print(f"  Test reply   : {result.get('sample', '')}")
    print(f"  Written to   : {ENV}")
    print()
    print("  Tuned for a free-tier key:")
    print("    GEMINI_RPM=10         paces requests so you do not hit HTTP 429")
    print("    CANDIDATES_DEBATE=5   16 LLM calls per search instead of 25")
    print("  Raise both in .env if your quota allows.")
    print(f"\n  {len(result['models'])} models are available to this key. To use a different one,")
    print("  edit GEMINI_MODEL in .env. Candidates:")
    for model in result["models"][:6]:
        print(f"    - {model}")
    print("\n  Now run:  python run.py")
    print("  The status pill in the top right should read 'gemini · " + result["model"] + "'.\n")
    return 0


async def check_existing() -> int:
    from app.config import settings
    from app.llm.check import verify

    print(f"\n  Checking the configuration in {ENV.name}")
    rule()
    print(f"  Provider : {settings.llm_provider}")

    if settings.llm_provider == "mock":
        print("  Deterministic mode. No key needed; no network calls are made.\n")
        return 0

    if settings.llm_provider == "ollama":
        import httpx

        print(f"  Endpoint : {settings.ollama_base_url}")
        print(f"  Model    : {settings.ollama_model}")
        try:
            resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=8)
            names = [m.get("name", "") for m in resp.json().get("models", [])]
            print(f"\n  Ollama is reachable. Installed: {', '.join(names) or 'nothing yet'}")
            if settings.ollama_model not in names:
                print(f"\n  {settings.ollama_model!r} is not installed. Run:")
                print(f"    ollama pull {settings.ollama_model}")
                return 1
            print("  Ready.\n")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"\n  Could not reach Ollama: {exc}")
            print("  Start it with:  ollama serve\n")
            return 1

    if not settings.gemini_api_key:
        print("  No GEMINI_API_KEY is set.")
        print("\n  Run:  python setup_key.py\n")
        return 1

    masked = settings.gemini_api_key[:8] + "…" + settings.gemini_api_key[-4:]
    print(f"  Key      : {masked}")
    print(f"  Model    : {settings.gemini_model or '(auto)'}")
    print("\n  Checking with Google…")

    result = await verify(settings.gemini_api_key, settings.gemini_model)
    rule()
    if result["ok"]:
        print(f"  Working. {result['message']}")
        if settings.gemini_model and settings.gemini_model != result["model"]:
            print(f"\n  Note: GEMINI_MODEL is {settings.gemini_model!r}, which this key cannot use.")
            print(f"  {result['model']!r} was used for the test instead. Updating .env.")
            write_env({"GEMINI_MODEL": result["model"]})
        print()
        return 0

    print(f"  Not working. {result['message']}")
    if result.get("models"):
        print(f"\n  Models this key can see: {', '.join(result['models'][:8])}")
    print("\n  To replace the key:  python setup_key.py\n")
    return 1


def configure_simple(provider: str, model: str | None = None) -> int:
    updates = {"LLM_PROVIDER": provider}
    if provider == "ollama" and model:
        updates["OLLAMA_MODEL"] = model
    write_env(updates)
    print(f"\n  Switched LLM_PROVIDER to {provider}.")
    if provider == "ollama":
        chosen = model or "llama3.1:8b"
        print(f"  Offline mode. Local model: {chosen}")
        print("  Make sure Ollama is running and the model is pulled:")
        print("    ollama serve")
        print(f"    ollama pull {chosen}")
        print("  Then check it with:  python setup_key.py --check")
    elif provider == "gemini":
        print("  Online mode. Add a key with:  python setup_key.py")
    else:
        print("  DebateRec will use the deterministic rule-based agents.")
        print("  Every feature works; no network calls are made.")
    print()
    return 0


def main() -> int:
    argv = sys.argv[1:]
    args = set(argv)
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    if "--check" in args:
        return asyncio.run(check_existing())
    if "--mock" in args:
        return configure_simple("mock")
    if "--gemini" in args:
        # Set the provider to online without prompting for a key. Used by the
        # launcher; the interactive key flow is the no-argument path below.
        return configure_simple("gemini")
    if "--ollama" in args:
        # An optional model name may follow --ollama, e.g. "--ollama llama3.1:8b".
        model = None
        idx = argv.index("--ollama")
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
            model = argv[idx + 1]
        return configure_simple("ollama", model)
    return asyncio.run(configure_gemini())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelled.\n")
        sys.exit(1)
