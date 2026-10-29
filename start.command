#!/bin/bash
# =============================================================================
#  DebateRec launcher for macOS / Linux.  Double-click this file.
#  (If macOS refuses to run it, first run:  chmod +x start.command)
#
#  Lets you pick a reasoning backend, and for OFFLINE mode it starts the Ollama
#  service, lets you choose a local model, pulls it if it is missing, and only
#  then launches the app.  ONLINE mode uses the Gemini API; MOCK mode runs the
#  deterministic rule-based debate with no network at all.
# =============================================================================
cd "$(dirname "$0")" || exit 1

# ---- locate Python ----------------------------------------------------------
PY=""
if command -v python3 >/dev/null 2>&1; then PY="python3"
elif command -v python >/dev/null 2>&1; then PY="python"
else
  echo
  echo "  Python 3 was not found."
  echo "  Install it from https://www.python.org/downloads/"
  echo
  read -r -p "  Press return to close."
  exit 1
fi

# ---- make sure dependencies are present -------------------------------------
if ! "$PY" -c "import fastapi, uvicorn, httpx, dotenv, numpy, sklearn" >/dev/null 2>&1; then
  echo
  echo "  Installing dependencies (first run only)..."
  if ! "$PY" -m pip install -r requirements.txt; then
    echo
    echo "  Dependency install failed. Fix the error above, then rerun this file."
    read -r -p "  Press return to close."
    exit 1
  fi
fi

launch() {
  echo
  echo "  Starting DebateRec...  (the browser opens automatically)"
  echo "  Leave this window open. Press Ctrl+C here to stop the server."
  echo
  exec "$PY" run.py
}

# ---- OFFLINE (Ollama) -------------------------------------------------------
run_offline() {
  if ! command -v ollama >/dev/null 2>&1; then
    echo
    echo "  Ollama is not installed."
    echo "  Download and install it from  https://ollama.com/download"
    echo "  Then run this file again and pick Offline."
    echo
    read -r -p "  Press return to go back."
    return 1
  fi

  # Start the Ollama service if it is not already answering.
  if ! ollama list >/dev/null 2>&1; then
    echo
    echo "  Starting the Ollama service..."
    (ollama serve >/dev/null 2>&1 &)
    tries=0
    until ollama list >/dev/null 2>&1; do
      sleep 1
      tries=$((tries + 1))
      if [ "$tries" -ge 30 ]; then
        echo "  Ollama did not come up in time. Try running  ollama serve  manually."
        read -r -p "  Press return to go back."
        return 1
      fi
    done
  fi

  echo
  echo "  Installed Ollama models:"
  ollama list
  echo
  read -r -p "  Model to use [default llama3.1:8b]: " MODEL
  MODEL="${MODEL:-llama3.1:8b}"

  # Pull it if it is not already present.
  if ! ollama list | grep -qiF "$MODEL"; then
    echo
    echo "  $MODEL is not pulled yet. Downloading it now..."
    echo "  (llama3.1:8b is about 4.7 GB - this can take a while the first time.)"
    echo
    if ! ollama pull "$MODEL"; then
      echo
      echo "  Could not pull $MODEL. Check the name and your connection."
      read -r -p "  Press return to go back."
      return 1
    fi
  fi

  echo
  echo "  Configuring DebateRec for OFFLINE mode with $MODEL ..."
  "$PY" setup_key.py --ollama "$MODEL"
  launch
}

# ---- ONLINE (Gemini) --------------------------------------------------------
run_online() {
  "$PY" setup_key.py --gemini >/dev/null
  echo
  echo "  Checking your Gemini configuration..."
  if ! "$PY" setup_key.py --check; then
    echo
    echo "  No working key yet. Let's set one up."
    if ! "$PY" setup_key.py; then
      echo
      echo "  Key setup was not completed. You can still run in deterministic mode."
      read -r -p "  Press return to continue."
    fi
  fi
  launch
}

# ---- MOCK -------------------------------------------------------------------
run_mock() {
  "$PY" setup_key.py --mock
  launch
}

# ---- menu -------------------------------------------------------------------
while true; do
  echo
  echo "  ==========================================================="
  echo "     DebateRec  -  choose how the agents should reason"
  echo "  ==========================================================="
  echo
  echo "    1.  Offline  -  Ollama (local model, no API key)      [default]"
  echo "    2.  Online   -  Gemini API (needs a free key)"
  echo "    3.  Mock     -  deterministic, instant, no network"
  echo "    4.  Just start with the current .env settings"
  echo
  read -r -p "  Select 1-4 and press return: " CHOICE
  CHOICE="${CHOICE:-1}"
  case "$CHOICE" in
    1) run_offline ;;
    2) run_online ;;
    3) run_mock ;;
    4) launch ;;
    *) echo "  Please type 1, 2, 3 or 4." ;;
  esac
done
