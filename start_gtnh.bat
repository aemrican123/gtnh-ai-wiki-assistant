@echo off
rem GTNH Field Guide launcher: checks Ollama and the model, then starts the local web app.
setlocal EnableExtensions
cd /d "%~dp0"
title GTNH Field Guide
set "PORT=8501"
set "PY=.venv\Scripts\python.exe"

echo [1/5] Checking the Python environment...
if not exist "%PY%" (
  echo   [X] .venv was not found in %CD%
  echo       Create it once with:
  echo         python -m venv .venv
  echo         .venv\Scripts\python -m pip install -e ".[dev]"
  goto :fail
)

for /f "usebackq delims=" %%V in (`%PY% -m gtnh_assistant.cli config-value llm_model 2^>nul`) do set "MODEL=%%V"
for /f "usebackq delims=" %%V in (`%PY% -m gtnh_assistant.cli config-value ollama_host 2^>nul`) do set "HOST=%%V"
if not defined MODEL (
  echo   [X] Could not read the settings. Reinstall with: .venv\Scripts\python -m pip install -e ".[dev]"
  goto :fail
)
if not defined HOST set "HOST=http://127.0.0.1:11434"
rem Ollama's own OLLAMA_HOST may be a bind address such as 0.0.0.0; always talk to it locally.
set "HOST=%HOST:0.0.0.0=127.0.0.1%"

echo [2/5] Checking that Ollama is installed...
where ollama >nul 2>nul
if errorlevel 1 (
  echo   [X] Ollama is not installed or not on PATH.
  echo       Install it from https://ollama.com/download/windows and run this script again.
  goto :fail
)

echo [3/5] Checking the Ollama service at %HOST% ...
curl.exe -s -o nul -m 3 "%HOST%/api/version"
if not errorlevel 1 goto :ollama_ready
echo   Ollama is not running; starting it in the background...
start "Ollama" /min ollama serve
for /l %%I in (1,1,30) do (
  timeout /t 1 /nobreak >nul
  curl.exe -s -o nul -m 2 "%HOST%/api/version" && goto :ollama_ready
)
echo   [X] Ollama did not start within 30 seconds.
echo       Open the Ollama app from the Start menu, or run "ollama serve" in a terminal to see the error.
goto :fail

:ollama_ready
echo   Ollama is running.

echo [4/5] Checking that the model %MODEL% is installed...
ollama list | findstr /i /c:"%MODEL%" >nul
if not errorlevel 1 goto :model_ready
echo   %MODEL% is not downloaded yet.
choice /c YN /m "  Download it now (several GB, one time only)"
if errorlevel 2 (
  echo   You can download it later with: ollama pull %MODEL%
  echo   Or set GTNH_LLM_MODEL in .env to a model you already have.
  goto :fail
)
ollama pull %MODEL%
if errorlevel 1 (
  echo   [X] The download failed. Check your internet connection and try: ollama pull %MODEL%
  goto :fail
)

:model_ready
echo   %MODEL% is available.

echo [5/5] Starting the GTNH Field Guide on http://127.0.0.1:%PORT% ...
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo   The app already seems to be running. Opening it in your browser.
  start "" "http://127.0.0.1:%PORT%"
  goto :eof
)
echo   Close this window or press Ctrl+C to stop the app. Run stop_gtnh.bat to also free GPU memory.
start "" cmd /c "timeout /t 5 /nobreak >nul & start http://127.0.0.1:%PORT%"
"%PY%" -m streamlit run app.py --server.address 127.0.0.1 --server.port %PORT% --server.headless true --browser.gatherUsageStats false
goto :eof

:fail
echo.
pause
exit /b 1
