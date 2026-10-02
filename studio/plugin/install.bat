@echo off
REM One command to put ClipBlitz Studio in an agent host:
REM
REM   plugin\install.bat
REM
REM It registers the marketplace this checkout ships (cloned from GitHub), installs
REM the plugin, and prints where it landed. The plugin talks to the Studio checkout
REM next to it on this machine only: nothing uploads, no API key, no account.
REM If the Claude Code CLI is missing, install it first and re-run this script.
setlocal
set REPO=agra-aarav15/clipblitz-ai-shorts
set MARKET=clipblitz
set PLUGIN=clipblitz-studio

where claude >nul 2>&1
if errorlevel 1 (
  echo The Claude Code CLI ^("claude"^) is not on PATH.
  echo Install Claude Code, then run this script again - or do two commands by hand:
  echo   claude plugin marketplace add %REPO%
  echo   claude plugin install %PLUGIN%@%MARKET%
  exit /b 1
)

call claude plugin marketplace add %REPO%
if errorlevel 1 exit /b 1
call claude plugin install %PLUGIN%@%MARKET%
if errorlevel 1 exit /b 1

echo installed %PLUGIN%@%MARKET%
echo ask for clips in plain words, or run: /cut ^<video or URL^> [how many]
exit /b 0
