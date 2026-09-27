#!/usr/bin/env bash
# One-time setup: Python environment, frontend dependencies, sample database, .env.
# Safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
fail() { printf '\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }

# --- prerequisites -------------------------------------------------------------

step "Checking prerequisites"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  done
fi
[ -n "$PYTHON" ] || fail "Python 3.11 or newer is required (set PYTHON=/path/to/python to choose one)."
echo "Python: $("$PYTHON" --version)"

command -v node >/dev/null 2>&1 || fail "Node.js 20.19+ or 22.12+ is required."
node -e '
  const [major, minor] = process.versions.node.split(".").map(Number);
  process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1);
' || fail "Node.js 20.19+ or 22.12+ is required (found $(node --version))."
echo "Node:   $(node --version)"

# --- backend -------------------------------------------------------------------

step "Setting up the Python environment (backend/.venv)"
[ -d backend/.venv ] || "$PYTHON" -m venv backend/.venv
backend/.venv/bin/python -m pip install --quiet --upgrade pip
backend/.venv/bin/python -m pip install --quiet -e "./backend[dev]"

# --- frontend ------------------------------------------------------------------

step "Installing frontend dependencies"
if [ -f frontend/package-lock.json ]; then
  (cd frontend && npm ci --no-fund --no-audit --loglevel=error)
else
  (cd frontend && npm install --no-fund --no-audit --loglevel=error)
fi

# --- data and config -----------------------------------------------------------

step "Building the sample database (database/sample.db)"
backend/.venv/bin/python database/init_db.py

step "Checking configuration"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi
key_set() { grep -Eq "^$1=.+" .env; }
if ! key_set NVIDIA_API_KEY && ! key_set GOOGLE_API_KEY; then
  warn "No API key in .env yet. Add NVIDIA_API_KEY (https://build.nvidia.com) and/or"
  warn "GOOGLE_API_KEY (https://aistudio.google.com/apikey) before chatting."
else
  key_set NVIDIA_API_KEY && echo "NVIDIA_API_KEY: set" || warn "NVIDIA_API_KEY: empty"
  key_set GOOGLE_API_KEY && echo "GOOGLE_API_KEY: set" || warn "GOOGLE_API_KEY: empty"
fi

step "Done"
cat <<'MSG'
Start the app:     scripts/dev.sh        then open http://localhost:5173
Run the tests:     cd backend && .venv/bin/pytest
Terminal chat:     cd backend && .venv/bin/python -m app.cli
MSG
