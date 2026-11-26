@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" /B ".venv\Scripts\pythonw.exe" main.py %*
) else (
    where pythonw >nul 2>nul
    if %errorlevel%==0 (
        start "" /B pythonw main.py %*
    ) else if exist ".venv\Scripts\python.exe" (
        start "" /B ".venv\Scripts\python.exe" main.py %*
    ) else (
        start "" /B python main.py %*
    )
)
exit /b 0
