@echo off
set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME_PATH% set CHROME_PATH="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

set PROFILE_DIR="%LOCALAPPDATA%\Google\Chrome\DiagnosticProfile"

echo Launching Chrome with remote debugging on port 9222...
start "" %CHROME_PATH% --remote-debugging-port=9222 --remote-allow-origins="*" --user-data-dir=%PROFILE_DIR%

