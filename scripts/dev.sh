#!/usr/bin/env bash
# Run the backend (FastAPI, port 8000) and frontend (Vite, port 5173) together.
# Ctrl-C stops both. Extra arguments go to Vite, e.g. `scripts/dev.sh --host`
# to open the app from other devices on your network.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[ -x backend/.venv/bin/uvicorn ] || { echo "Run scripts/setup.sh first." >&2; exit 1; }
[ -d frontend/node_modules ] || { echo "Run scripts/setup.sh first." >&2; exit 1; }

trap 'trap - EXIT; kill 0' INT TERM EXIT

(cd backend && exec .venv/bin/uvicorn app.api.main:app --port 8000 --reload) &
(cd frontend && exec npm run dev -- --port 5173 --strictPort "$@") &

wait
