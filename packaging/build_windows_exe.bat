@echo off
setlocal enabledelayedexpansion
title Build Windows Executable - Exam Solver

echo ===================================================================
echo [Exam Solver Build Engine] Compiling Standalone Windows Executable
echo ===================================================================

cd /d "%~dp0\.."

REM Verify python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in system PATH.
    pause
    exit /b 1
)

REM Verify PyInstaller
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] PyInstaller not detected. Installing pyinstaller...
    pip install pyinstaller
)

REM Install playwright browsers if needed
echo [INFO] Ensuring Playwright browser drivers are installed...
python -m playwright install chromium

echo.
echo [BUILD] Running PyInstaller build with packaging\pyinstaller.spec...
python -m PyInstaller --clean --noconfirm packaging\pyinstaller.spec

if errorlevel 1 (
    echo [ERROR] Build failed! Check terminal output above for errors.
    pause
    exit /b 1
)

echo.
echo ===================================================================
echo [SUCCESS] Build finished successfully!
echo Executable location: dist\ExamSolverDashboard.exe
echo ===================================================================
pause
endlocal
