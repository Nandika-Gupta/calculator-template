#!/usr/bin/env bash
# ViralCut one-click start for macOS / Linux. Double-click or run: bash viralcut/start.sh
set -e
cd "$(dirname "$0")/.."

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg is missing. Install it first:"
  echo "  macOS:  brew install ffmpeg        (Homebrew: https://brew.sh)"
  echo "  Linux:  sudo apt install ffmpeg"
  exit 1
fi
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then echo "Python 3.10+ is missing. Download it from https://www.python.org/downloads/"; exit 1; fi

if [ ! -d .venv ]; then
  echo "First run: setting up ViralCut (a few minutes)…"
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r viralcut/requirements.txt
fi
[ -f viralcut/settings.env ] || cp viralcut/settings.example.env viralcut/settings.env

URL=http://127.0.0.1:8000
( sleep 3; (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true ) &
echo "ViralCut is running at $URL - keep this window open, press Ctrl+C to stop."
exec .venv/bin/python -m uvicorn viralcut.app:app --host 127.0.0.1 --port 8000
