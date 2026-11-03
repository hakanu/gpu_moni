#!/usr/bin/env bash
# GPU & System Sentry - bpytop-inspired Terminal UI (TUI) Launcher for Linux/Ubuntu
set -e

cd "$(dirname "$0")"

if command -v uv &> /dev/null; then
    exec uv run python main.py --tui "$@"
fi

if [ -d ".venv" ] && [ -f ".venv/bin/python" ]; then
    exec .venv/bin/python main.py --tui "$@"
fi

exec python3 main.py --tui "$@"
