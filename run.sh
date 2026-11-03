#!/usr/bin/env bash
# GPU & System Sentry - Linux Launcher
set -e

cd "$(dirname "$0")"

if command -v uv &> /dev/null; then
    exec uv run python main.py "$@"
fi

if ! command -v python3 &> /dev/null; then
    echo "[!] Error: python3 is not installed or not in PATH."
    exit 1
fi

if [ -d ".venv" ] && [ -f ".venv/bin/python" ]; then
    PYTHON_EXEC=".venv/bin/python"
elif [ -n "$VIRTUAL_ENV" ]; then
    PYTHON_EXEC="python"
else
    if [ ! -d ".venv" ]; then
        echo "[*] Creating virtual environment (.venv)..."
        python3 -m venv .venv
        .venv/bin/pip install --upgrade pip
        .venv/bin/pip install -r requirements.txt
    fi
    PYTHON_EXEC=".venv/bin/python"
fi

echo "[*] Starting GPU & System Sentry on Linux..."
exec "$PYTHON_EXEC" main.py "$@"
