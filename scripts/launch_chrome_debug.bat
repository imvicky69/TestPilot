@echo off
setlocal
title TestPilot - Launch Chrome with Remote Debugging (Port 9222)

echo ===================================================================
echo [TestPilot] Starting Google Chrome with Remote Debugging...
echo ===================================================================

set "CHROME_PATH="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
) else if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
) else if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%LocalAppData%\Google\Chrome\Application\chrome.exe"
)

if "%CHROME_PATH%"=="" (
    echo [ERROR] Google Chrome executable not found in standard directories.
    pause
    exit /b 1
)

set "USER_DATA_DIR=%TEMP%\chrome_cdp_profile"
if not exist "%USER_DATA_DIR%" mkdir "%USER_DATA_DIR%"

echo [INFO] Chrome Path: "%CHROME_PATH%"
echo [INFO] Debug Port: 9222
echo [INFO] User Profile: "%USER_DATA_DIR%"
echo.
echo Launching Chrome... Navigate to your exam or test tab.

start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="%USER_DATA_DIR%" --no-first-run --no-default-browser-check https://www.pw.live/practice-v2

echo [SUCCESS] Chrome launched on port 9222.
endlocal

