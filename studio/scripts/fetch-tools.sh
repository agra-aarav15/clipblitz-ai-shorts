#!/usr/bin/env bash
# fetch-tools.sh — download the two binaries ClipBlitz needs into ./bin/
#
# macOS / Linux / Windows-Git-Bash version. Run from the project folder:
#     bash scripts/fetch-tools.sh
#
# What it fetches (both free, no account needed):
#   * ffmpeg  — a static build                     -> bin/ffmpeg-*/bin/ffmpeg  (Windows: bin/ffmpeg-*/bin/ffmpeg.exe)
#   * yt-dlp  — the standalone binary              -> bin/yt-dlp  (Windows: bin/yt-dlp.exe)
#
# ClipBlitz finds them automatically (clipblitz/config.py) — you never touch PATH.
# Safe to re-run: existing files are skipped unless you pass --force.

set -u
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/bin"
mkdir -p "$BIN"

echo
echo "ClipBlitz tool fetch"
echo "  target: $BIN"
echo

OS="$(uname -s)"
case "$OS" in
  MINGW*|MSYS*|CYGWIN*) PLATFORM="windows" ;;
  Darwin)               PLATFORM="macos" ;;
  *)                    PLATFORM="linux" ;;
esac
echo "  platform detected: $PLATFORM"

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- yt-dlp
YTDLP="$BIN/yt-dlp"
[ "$PLATFORM" = "windows" ] && YTDLP="$BIN/yt-dlp.exe"

if [ -f "$YTDLP" ] && [ "$FORCE" -eq 0 ]; then
  echo "[skip] yt-dlp already present"
else
  echo "[get ] yt-dlp ..."
  if [ "$PLATFORM" = "windows" ]; then
    URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
  elif [ "$PLATFORM" = "macos" ]; then
    URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
  else
    URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
  fi
  if have curl; then
    curl -L --fail -o "$YTDLP" "$URL" && chmod +x "$YTDLP" && echo "       ok" || {
      echo "       FAILED — download manually from https://github.com/yt-dlp/yt-dlp/releases"
      echo "       and save it as: $YTDLP"
    }
  elif have wget; then
    wget -O "$YTDLP" "$URL" && chmod +x "$YTDLP" && echo "       ok" || echo "       FAILED"
  else
    echo "       neither curl nor wget found. Install one, or download manually:"
    echo "       $URL  ->  $YTDLP"
  fi
fi

# ---------------------------------------------------------------- ffmpeg
FF_FOUND="$(find "$BIN" -maxdepth 3 -type f -name 'ffmpeg' -o -maxdepth 3 -type f -name 'ffmpeg.exe' 2>/dev/null | head -1)"

if [ -n "$FF_FOUND" ] && [ "$FORCE" -eq 0 ]; then
  echo "[skip] ffmpeg already present ($FF_FOUND)"
else
  echo "[get ] ffmpeg ..."
  TMP="$BIN/.cb-ffmpeg-dl"
  mkdir -p "$TMP"
  if [ "$PLATFORM" = "windows" ]; then
    URL="https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    OUT="$TMP/ff.zip"
    ( have curl && curl -L --fail -o "$OUT" "$URL" ) || ( have wget && wget -O "$OUT" "$URL" )
    if [ -f "$OUT" ]; then
      have unzip && unzip -q -o "$OUT" -d "$BIN" && echo "       ok" || echo "       unzip missing — extract $OUT into $BIN manually"
      rm -rf "$TMP"
    else
      echo "       FAILED — download $URL and extract into $BIN"
      echo "       (result must be bin/ffmpeg-<version>/bin/ffmpeg.exe)"
    fi
  elif [ "$PLATFORM" = "macos" ]; then
    if have brew; then
      echo "       Homebrew found — installing ffmpeg system-wide (simplest on macOS)"
      brew install ffmpeg && echo "       ok" || echo "       brew install failed — see https://ffmpeg.org/download.html"
    else
      echo "       No Homebrew. Either install it (https://brew.sh) then run 'brew install ffmpeg',"
      echo "       or download a static build from https://evermeet.cx/ffmpeg/ and put the binary in:"
      echo "       $BIN/ffmpeg-7/bin/ffmpeg"
    fi
  else
    URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    OUT="$TMP/ff.tar.xz"
    ( have curl && curl -L --fail -o "$OUT" "$URL" ) || ( have wget && wget -O "$OUT" "$URL" )
    if [ -f "$OUT" ]; then
      tar -xJf "$OUT" -C "$TMP" && mv "$TMP"/ffmpeg-*-static "$BIN/" && mv "${BIN}"/ffmpeg-*-static "$BIN/ffmpeg-linux" \
        && echo "       ok" || echo "       extraction failed — extract $OUT into $BIN"
      rm -rf "$TMP"
    else
      echo "       FAILED — download $URL and extract into $BIN"
    fi
  fi
fi

# ---------------------------------------------------------------- verify
echo
echo "Verifying:"
OK=0
if [ -f "$YTDLP" ]; then
  V="$("$YTDLP" --version 2>/dev/null)" && { echo "  yt-dlp  $V"; OK=$((OK+1)); } || echo "  yt-dlp  present but would not run"
else
  echo "  yt-dlp  MISSING"
fi

FF="$(find "$BIN" -maxdepth 3 -type f \( -name 'ffmpeg' -o -name 'ffmpeg.exe' \) 2>/dev/null | head -1)"
if [ -n "$FF" ]; then
  V="$("$FF" -version 2>/dev/null | head -1)" && { echo "  ffmpeg  $V"; OK=$((OK+1)); } || echo "  ffmpeg  present but would not run"
elif have ffmpeg; then
  echo "  ffmpeg  found on PATH ($(ffmpeg -version 2>/dev/null | head -1))"; OK=$((OK+1))
else
  echo "  ffmpeg  MISSING"
fi

echo
if [ "$OK" -ge 2 ]; then
  echo "Both tools ready. Start the app with:  python run.py"
else
  echo "Some tools are missing — see the messages above, then run this script again."
fi
echo