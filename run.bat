@echo off
title GPU Sentry Launcher
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" main.py
) else (
    start "" python main.py
)
exit
