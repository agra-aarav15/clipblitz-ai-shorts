@echo off
rem ---------------------------------------------------------------------------
rem ClipBlitz Studio - the boot line. Started by the Startup launcher that
rem scripts\install_autostart.bat installs, and safe to run by hand.
rem
rem It resolves everything from its own location, so it works from any drive or
rem folder and hardcodes nothing. The server itself decides whether to work: if
rem the port is already taken it prints that and exits, and its own heartbeat
rem runs the day's cycle when one is due - so booting twice is harmless.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0.."

set "PY="
if exist "%~dp0..\bin\python.exe" set "PY=%~dp0..\bin\python.exe"
if not defined PY (
  py -3 --version >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo ClipBlitz Studio: no Python found. Run START.bat once, or install Python 3.12.
  exit /b 1
)

start "ClipBlitz Studio" /min cmd /c "%PY% -u run.py >> boot.log 2>&1"
exit /b 0
