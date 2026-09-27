#!/usr/bin/env bash
# ClipBlitz Studio launcher for macOS, Linux, and Android (Termux).
# ffmpeg ships in bin/ for Windows; on other platforms it comes from the package
# manager, so the launcher checks and says exactly what to install.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed."
  echo "  macOS:   brew install python3   (or from https://www.python.org/downloads/)"
  echo "  Ubuntu:  sudo apt install python3 ffmpeg"
  echo "  Termux:  pkg install python ffmpeg"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  bundled="$(find bin -name ffmpeg -type f 2>/dev/null | head -1)"
  if [ -z "$bundled" ]; then
    echo "note: ffmpeg is not in bin/ or on PATH."
    echo "  Ubuntu:  sudo apt install ffmpeg      Termux:  pkg install ffmpeg"
    echo "  macOS:   brew install ffmpeg"
    echo "The studio starts anyway and will refuse to render until ffmpeg exists."
  fi
fi

echo ""
echo "  ClipBlitz Studio - engines: ProX v5 / B2 Pro X / Both"
echo "  The address for your phone prints below once the server is up."
echo ""
exec python3 run.py
