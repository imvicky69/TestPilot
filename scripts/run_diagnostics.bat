@echo off
setlocal
title TestPilot - DOM & Browser Diagnostics

echo ===================================================================
echo [TestPilot] Running Chrome DOM Inspection & Security Audit...
echo ===================================================================

cd /d "%~dp0\.."

python main.py --port 9222 --open-report

pause
endlocal

