@echo off
REM ViralCut one-click start for Windows. Double-click this file.
cd /d "%~dp0\.."

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo FFmpeg is missing. Install it by opening PowerShell and running:  winget install ffmpeg
  echo Then close and re-open this window.
  pause
  exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
  echo Python is missing. Install Python 3.10+ from https://www.python.org/downloads/  ^(tick "Add Python to PATH"^)
  pause
  exit /b 1
)

if not exist .venv (
  echo First run: setting up ViralCut ^(a few minutes^)...
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r viralcut\requirements.txt
)
if not exist viralcut\settings.env copy viralcut\settings.example.env viralcut\settings.env >nul

start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
echo ViralCut is running at http://127.0.0.1:8000 - keep this window open, close it to stop.
.venv\Scripts\python -m uvicorn viralcut.app:app --host 127.0.0.1 --port 8000
pause
