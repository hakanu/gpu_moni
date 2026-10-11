@echo off
title GPU Sentry - Shortcut Installer
cd /d "%~dp0"

echo ========================================================
echo     GPU Sentry - Windows Shortcut Installer
echo ========================================================
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py --install-shortcut --desktop
) else (
    python main.py --install-shortcut --desktop
)

echo.
echo Shortcut created in Windows Start Menu and Desktop!
echo Press any key to exit.
pause >nul
