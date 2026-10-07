#!/usr/bin/env bash
# GPU & System Sentry - Linux Launcher
set -e

# Change directory to script directory
cd "$(dirname "$0")"

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "[!] Error: python3 is not installed or not in PATH."
    exit 1
fi

# Detect virtual environment
if [ -d ".venv" ] && [ -f ".venv/bin/python" ]; then
    PYTHON_EXEC=".venv/bin/python"
elif [ -n "$VIRTUAL_ENV" ]; then
    PYTHON_EXEC="python"
else
    # Prompt / create virtual environment if not present
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
