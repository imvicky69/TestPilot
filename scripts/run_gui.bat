@echo off
setlocal
title TestPilot - Desktop GUI

echo ===================================================================
echo [TestPilot] Starting Desktop Interface...
echo ===================================================================

cd /d "%~dp0\.."

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    pause
    exit /b 1
)

python main.py --gui

pause
endlocal

