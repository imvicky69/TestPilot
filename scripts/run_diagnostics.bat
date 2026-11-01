@echo off
setlocal
title Exam Solver - DOM & Browser Diagnostics

echo ===================================================================
echo [Diagnostics] Running Chrome DOM Inspection & Security Audit...
echo ===================================================================

cd /d "%~dp0\.."

python main.py --port 9222 --open-report

pause
endlocal
