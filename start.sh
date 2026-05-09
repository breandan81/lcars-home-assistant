#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -f .venv-lcars/bin/activate ]; then
    python3 -m venv .venv-lcars
    .venv-lcars/bin/pip install -r requirements.txt
fi
source .venv-lcars/bin/activate
exec python -m uvicorn main:app --host 0.0.0.0 --port 8080
