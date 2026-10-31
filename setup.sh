#!/usr/bin/env bash
# One-time setup: Python venv + backend deps, frontend deps + build, backend/.env, Ollama models.
# Safe to re-run. Usage: ./setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }

# ---------------------------------------------------------------- Python backend
bold "1/4  Python environment (.venv)"
if command -v uv >/dev/null 2>&1; then
  # uv downloads Python 3.12 automatically if it isn't installed.
  [ -x .venv/bin/python ] || uv venv .venv --python 3.12
  uv pip install --python .venv/bin/python -r backend/requirements.txt
else
  PY=""
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)'; then
      PY="$candidate"; break
    fi
  done
  [ -n "$PY" ] || die "Python 3.11-3.14 not found. Install it (brew install python@3.12) or install uv (brew install uv)."
  [ -x .venv/bin/python ] || "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip --quiet
  .venv/bin/python -m pip install -r backend/requirements.txt
fi
ok "Backend dependencies installed ($(.venv/bin/python --version))"

# ---------------------------------------------------------------- Frontend
bold "2/4  Frontend (React + Vite)"
command -v npm >/dev/null 2>&1 || die "Node.js not found. Install Node 20.19+ (brew install node)."
node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=19)?0:1)' \
  || die "Node $(node --version) is too old. Install Node 20.19 or newer."
(cd frontend && npm ci --no-audit --no-fund && npm run build)
ok "UI built into frontend/dist"

# ---------------------------------------------------------------- Configuration
bold "3/4  Configuration (backend/.env)"
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  if [ -t 0 ]; then
    read -r -s -p "  Neo4j password for user 'neo4j' (Enter to set it later): " NEO_PW; echo
    if [ -n "$NEO_PW" ]; then
      NEO_PW="$NEO_PW" .venv/bin/python - <<'EOF'
import os, pathlib
p = pathlib.Path("backend/.env")
p.write_text(p.read_text().replace("NEO4J_PASSWORD=change-me", "NEO4J_PASSWORD=" + os.environ["NEO_PW"]))
EOF
    fi
  fi
  ok "Created backend/.env"
else
  ok "backend/.env already exists (left unchanged)"
fi
if grep -q '^NEO4J_PASSWORD=change-me' backend/.env; then
  warn "Set NEO4J_PASSWORD in backend/.env before starting."
fi

# ---------------------------------------------------------------- Ollama models
bold "4/4  Ollama models"
# Read settings exactly as the backend does (pydantic-settings over backend/.env), so quotes,
# inline comments, spaces and Windows line endings are handled identically.
setting() {
  (cd backend && ../.venv/bin/python -c \
    'import sys; from app.config import get_settings; print(getattr(get_settings(), sys.argv[1]))' "$1")
}
LLM_MODEL="$(setting llm_model)" || die "Could not read backend/.env (see the error above)."
EMBEDDING_MODEL="$(setting embedding_model)" || die "Could not read backend/.env (see the error above)."
OLLAMA_HOST_URL="$(setting ollama_host)" || die "Could not read backend/.env (see the error above)."

# Ollama rejects names containing spaces, quotes or control characters with "invalid model name".
clean_name() {
  case "$1" in "" | *[[:space:]]* | *[[:cntrl:]]* | *\"* | *\'* | *\#*) return 1 ;; esac
}

if ! command -v ollama >/dev/null 2>&1; then
  warn "Ollama not installed. Install it from https://ollama.com/download, then run:"
  warn "  ollama pull ${LLM_MODEL} && ollama pull ${EMBEDDING_MODEL}"
elif ! curl -fsS "${OLLAMA_HOST_URL}/api/version" >/dev/null 2>&1; then
  warn "Ollama is not reachable at ${OLLAMA_HOST_URL}. Open the Ollama app (or run 'ollama serve'), then run:"
  warn "  ollama pull ${LLM_MODEL} && ollama pull ${EMBEDDING_MODEL}"
else
  PULL_FAILED=0
  for MODEL in "$LLM_MODEL" "$EMBEDDING_MODEL"; do
    if ! clean_name "$MODEL"; then
      warn "Invalid model name in backend/.env: $(printf '%q' "$MODEL")  (fix LLM_MODEL / EMBEDDING_MODEL)"
      PULL_FAILED=1
      continue
    fi
    printf '  Pulling %s\n' "$MODEL"
    if ! OLLAMA_HOST="$OLLAMA_HOST_URL" ollama pull "$MODEL"; then
      warn "Could not pull '${MODEL}'. Check the name at https://ollama.com/library, then run: ollama pull ${MODEL}"
      PULL_FAILED=1
    fi
  done
  if [ "$PULL_FAILED" = 0 ]; then
    ok "Models ready: ${LLM_MODEL}, ${EMBEDDING_MODEL}"
  else
    warn "Some models are missing. The status bar will show which one until it is pulled."
  fi
fi

bold "Setup complete"
cat <<EOF
  Before the first start, in Neo4j Desktop:
    - create/start a local DBMS (Neo4j 5.18+), and install the APOC plugin for it
    - put its password in backend/.env (NEO4J_PASSWORD)

  Then run:  bash start.sh      and open http://localhost:8000
EOF
