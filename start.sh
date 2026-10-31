#!/usr/bin/env bash
# Start the app.
#   ./start.sh         API + built UI on http://localhost:8000
#   ./start.sh --dev   API with auto-reload on :8000 and the Vite dev UI on http://localhost:5173
# Environment: PORT (default 8000), HOST (default 127.0.0.1)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
DEV=false
[ "${1:-}" = "--dev" ] && DEV=true

[ -x .venv/bin/python ] || { echo "Run 'bash setup.sh' first (no .venv found)."; exit 1; }
[ -f backend/.env ] || { echo "Run 'bash setup.sh' first (no backend/.env found)."; exit 1; }

# Read settings exactly as the backend does (pydantic-settings over backend/.env).
setting() {
  (cd backend && ../.venv/bin/python -c \
    'import sys; from app.config import get_settings; print(getattr(get_settings(), sys.argv[1]))' "$1")
}
OLLAMA_URL="$(setting ollama_host)" || { echo "Could not read backend/.env (see the error above)."; exit 1; }

# Start Ollama if it isn't running. Its parallelism matches the extraction concurrency.
if ! curl -fsS "${OLLAMA_URL}/api/version" >/dev/null 2>&1; then
  if command -v ollama >/dev/null 2>&1; then
    echo "Starting Ollama..."
    mkdir -p backend/data
    OLLAMA_NUM_PARALLEL="$(setting extraction_concurrency)" nohup ollama serve >backend/data/ollama.log 2>&1 &
    for _ in $(seq 1 20); do curl -fsS "${OLLAMA_URL}/api/version" >/dev/null 2>&1 && break; sleep 0.5; done
  else
    echo "Warning: Ollama is not running at ${OLLAMA_URL}. The status bar will show it as offline."
  fi
fi

# A single uvicorn worker: the ingestion queue lives in this process.
cd backend
if $DEV; then
  ../.venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload &
  API_PID=$!
  trap 'kill $API_PID 2>/dev/null' EXIT INT TERM
  cd ../frontend
  [ -d node_modules ] || npm ci --no-audit --no-fund
  echo "UI (dev): http://localhost:5173"
  API_URL="http://localhost:${PORT}" npm run dev
else
  if [ ! -f ../frontend/dist/index.html ]; then
    echo "Building the UI..."
    (cd ../frontend && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build)
  fi
  echo "Legal GraphRAG: http://localhost:${PORT}   (API docs: http://localhost:${PORT}/docs)"
  ( sleep 2; command -v open >/dev/null 2>&1 && open "http://localhost:${PORT}" ) >/dev/null 2>&1 &
  exec ../.venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
fi
