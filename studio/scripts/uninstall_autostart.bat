@echo off
rem ---------------------------------------------------------------------------
rem ClipBlitz Studio - stop starting with the machine.
rem
rem Deletes the single launcher scripts\install_autostart.bat wrote. It does not
rem touch the studio, your data, your choices or a studio that is already
rem running - only the shortcut that starts it at sign-in.
rem ---------------------------------------------------------------------------
setlocal
title ClipBlitz Studio - remove autostart

set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ClipBlitz Studio.cmd"
if not exist "%LINK%" (
  echo Nothing to remove - the Startup launcher is not there:
  echo   %LINK%
  pause
  exit /b 0
)

del "%LINK%"
if exist "%LINK%" (
  echo Could not delete %LINK%
  pause
  exit /b 1
)

echo.
echo Removed:
echo   %LINK%
echo.
echo The studio will no longer start at sign-in. Your clips, choices and the
echo models trained from them are untouched.
echo.
pause
exit /b 0
