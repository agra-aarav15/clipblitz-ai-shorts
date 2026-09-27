@echo off
setlocal
title ClipBlitz Studio
cd /d "%~dp0"

REM ---------------------------------------------------------------------------
REM ClipBlitz Studio one-click launcher for Windows.
REM Finds Python, installs it silently if the machine has none (user scope, no
REM admin prompt), then starts the studio. ffmpeg and yt-dlp ship in bin\, so
REM nothing else is ever downloaded.
REM ---------------------------------------------------------------------------

set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY ( python --version >nul 2>&1 && set PY=python )
if defined PY goto :run

echo Python is not installed. Installing it for you (one time, about a minute)...
echo.
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
if errorlevel 1 (
  echo winget is not available - downloading Python from python.org instead...
  powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile \"$env:TEMP\python-setup.exe\" -UseBasicParsing } catch { exit 1 }"
  if errorlevel 1 (
    echo.
    echo Could not install Python automatically.
    echo Install it from https://www.python.org/downloads/ and run START.bat again.
    pause
    exit /b 1
  )
  echo Running the Python installer (user scope, adds Python to PATH)...
  "%TEMP%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
)

REM a fresh install is not on this window's PATH yet - add the standard location
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY ( python --version >nul 2>&1 && set PY=python )
if not defined PY (
  echo Python was installed but is not detected in this window.
  echo Close this window, open a new one, and run START.bat again.
  pause
  exit /b 1
)

:run
echo.
echo   ClipBlitz Studio - engines: ProX v5 / B2 Pro X / Both
echo   The address for your phone prints below once the server is up.
echo.
%PY% run.py
pause
