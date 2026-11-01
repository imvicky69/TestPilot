#!/usr/bin/env bash
CHROME_PATH="/c/Program Files/Google/Chrome/Application/chrome.exe"
if [ ! -f "$CHROME_PATH" ]; then
    CHROME_PATH="/c/Program Files (x86)/Google/Chrome/Application/chrome.exe"
fi

PROFILE_DIR="$LOCALAPPDATA/Google/Chrome/DiagnosticProfile"
mkdir -p "$PROFILE_DIR"

echo "Launching Chrome with remote debugging on port 9222..."
"$CHROME_PATH" --remote-debugging-port=9222 --remote-allow-origins="*" --user-data-dir="$PROFILE_DIR" &

