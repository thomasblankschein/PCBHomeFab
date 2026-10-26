#!/usr/bin/env bash
# Lint, type check and test one service: scripts/check_service.sh panel
# Uses the python on PATH (CI) or the repository's .venv (local work).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
py="${PYTHON:-}"
if [ -z "$py" ]; then
    if [ -x "$root/.venv/Scripts/python.exe" ]; then py="$root/.venv/Scripts/python.exe"
    elif [ -x "$root/.venv/bin/python" ]; then py="$root/.venv/bin/python"
    else py=python; fi
fi
cd "$root/services/$1"
"$py" -m ruff check .
"$py" -m ruff format --check .
"$py" -m mypy
"$py" -m pytest -q
