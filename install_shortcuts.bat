@echo off
rem Creates "GTNH Field Guide" shortcuts on the desktop and in the Start menu (run once).
rem   install_shortcuts.bat           create or update the shortcuts
rem   install_shortcuts.bat --remove  delete them
setlocal EnableExtensions
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [X] .venv was not found in %CD%. Install the app first, see README step 2.
  pause
  exit /b 1
)
"%PY%" -m gtnh_assistant.shortcuts %*
if errorlevel 1 (
  echo [X] The shortcuts could not be changed.
  pause
  exit /b 1
)
if /i not "%~1"=="--remove" (
  echo.
  echo Double-click "GTNH Field Guide" on your desktop to open the app. Close its window to quit.
  echo Tip: right-click the shortcut and choose "Pin to taskbar" or "Pin to Start".
)
timeout /t 8
