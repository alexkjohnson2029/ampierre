#!/bin/sh
# Capture the Input, Board (equalizer) and About pages at laptop width.
# Usage: sh design-review/shoot.sh before|after   (app must be running on :8000)
set -e
out="$(cd "$(dirname "$0")" && pwd -W 2>/dev/null || pwd)/$1"
mkdir -p "$out"
chrome="/c/Program Files/Google/Chrome/Application/chrome.exe"
shot() {
  "$chrome" --headless=new --disable-gpu --hide-scrollbars --window-size=1440,"$3" \
    --virtual-time-budget=9000 --screenshot="$out/$1.png" "$2" >/dev/null 2>&1
  echo "$out/$1.png"
}
shot input "http://127.0.0.1:8000/" 1400
shot board "http://127.0.0.1:8000/?example=three_band_equalizer" 2600
shot about "http://127.0.0.1:8000/about.html" 3200
