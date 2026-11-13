@echo off
rem Stops the GTNH Field Guide and frees GPU memory.
rem   stop_gtnh.bat         stop the app and unload the model (Ollama keeps running for other apps)
rem   stop_gtnh.bat --all   also stop the Ollama service
setlocal EnableExtensions
cd /d "%~dp0"
set "PORT=8501"
set "PY=.venv\Scripts\python.exe"

echo Stopping the web app on port %PORT% ...
powershell -NoProfile -Command "$p = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if ($p) { $p | ForEach-Object { Stop-Process -Id $_ -Force }; 'Stopped.' } else { 'The app was not running.' }"

if exist "%PY%" (
  for /f "usebackq delims=" %%V in (`%PY% -m gtnh_assistant.cli config-value llm_model 2^>nul`) do set "MODEL=%%V"
)
where ollama >nul 2>nul
if errorlevel 1 goto :done
if defined MODEL (
  echo Unloading %MODEL% from GPU memory...
  ollama stop %MODEL% 2>nul
)
if /i "%~1"=="--all" (
  echo Stopping the Ollama service...
  taskkill /im "ollama app.exe" /f >nul 2>nul
  taskkill /im ollama.exe /f >nul 2>nul
)

:done
echo Done. Your wiki data and settings are unchanged.
timeout /t 3 >nul
