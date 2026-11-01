@echo off
setlocal
title TestPilot - Live Web Dashboard

echo ===================================================================
echo [TestPilot] Initializing Web Server & Automation Engine
echo ===================================================================

cd /d "%~dp0\.."

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

echo [INFO] Starting Live Dashboard on http://127.0.0.1:8000 ...
python dashboard.py --port 8000

pause
endlocal

