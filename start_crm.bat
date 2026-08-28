@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment .venv was not found.
    echo Create it and install requirements before starting the CRM.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m flask --app run.py db upgrade
if errorlevel 1 (
    echo Database migration failed.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" run.py
endlocal

