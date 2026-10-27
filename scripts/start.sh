#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then
  echo "Сначала подготовьте окружение и соберите интерфейс по README.md."
  exit 1
fi
echo "orel: http://127.0.0.1:8127 — остановка Ctrl+C"
exec .venv/bin/python -m uvicorn orel.app:app --host 127.0.0.1 --port 8127
