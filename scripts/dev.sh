#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
if [ ! -x .venv/bin/python ] || [ ! -d frontend/node_modules ]; then
  echo "Сначала установите зависимости по README.md."
  exit 1
fi
API_PID=""
UI_PID=""
cleanup() {
  if [ -n "$API_PID" ]; then kill "$API_PID" 2>/dev/null || true; fi
  if [ -n "$UI_PID" ]; then kill "$UI_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM
.venv/bin/python -m uvicorn orel.app:app --host 127.0.0.1 --port 8127 &
API_PID=$!
cd frontend
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort &
UI_PID=$!
echo "orel dev: http://127.0.0.1:5173 — остановка Ctrl+C"
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$UI_PID" 2>/dev/null; do sleep 1; done
exit 1
