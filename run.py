#!/usr/bin/env python3
"""Cross-platform launcher.

    python run.py

Works identically on Windows, macOS and Linux: no shell script, no Makefile,
no activate step to forget. It checks dependencies, warns about a missing API
key without refusing to start, and opens the browser once the server is up.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

BANNER = r"""
  ___     _         _       ___
 |   \ ___| |__  __ _| |_ ___| _ \___ __
 | |) / -_) '_ \/ _` |  _/ -_)   / -_) _|
 |___/\___|_.__/\__,_|\__\___|_|_\___\__|

 Evidence-grounded, debate-based recommendation
"""

REQUIRED = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("pydantic", "pydantic"),
    ("dotenv", "python-dotenv"),
    ("httpx", "httpx"),
    ("numpy", "numpy"),
    ("sklearn", "scikit-learn"),
]


def check_python() -> None:
    if sys.version_info < (3, 10):
        sys.exit(
            f"DebateRec needs Python 3.10 or newer. You are running {sys.version.split()[0]}.\n"
            "Download a current version from https://www.python.org/downloads/"
        )


def check_dependencies() -> None:
    import importlib

    missing = []
    for module, package in REQUIRED:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    if missing:
        pip = "pip" if os.name == "nt" else "pip3"
        sys.exit(
            "Missing dependencies: " + ", ".join(missing) + "\n\n"
            f"Install them with:\n    {pip} install -r requirements.txt\n"
        )


def free_port(preferred: int, host: str) -> int:
    """If the preferred port is taken, walk upward rather than crashing."""
    for candidate in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
                return candidate
            except OSError:
                continue
    return preferred


def open_browser_later(url: str) -> None:
    def worker() -> None:
        time.sleep(2.0)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a headless machine is not an error
            pass

    threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    check_python()
    check_dependencies()

    print(BANNER)

    env_file = ROOT / ".env"
    if not env_file.exists():
        example = ROOT / ".env.example"
        if example.exists():
            env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            print("  Created .env from .env.example.")

    from app.config import settings  # imported after the dependency check

    if settings.llm_provider == "gemini" and not settings.gemini_api_key:
        print("  No GEMINI_API_KEY found in .env.")
        print("  DebateRec will run its deterministic debate instead — every feature works,")
        print("  the arguments are just rule-written rather than model-written.\n")
        if sys.stdin is not None and sys.stdin.isatty() and "--no-setup" not in sys.argv:
            try:
                answer = input("  Set up a free Gemini key now? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer in {"y", "yes"}:
                import subprocess

                subprocess.run([sys.executable, str(ROOT / "setup_key.py")], check=False)
                # Re-read .env so the server starts with whatever was just saved.
                from importlib import reload

                from app import config as config_module

                reload(config_module)
        print()

    host = settings.host
    port = free_port(settings.port, host)
    if port != settings.port:
        print(f"  Port {settings.port} was busy; using {port} instead.\n")

    url = f"http://{host}:{port}"
    if "--no-browser" not in sys.argv:
        open_browser_later(url)

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload="--reload" in sys.argv,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
