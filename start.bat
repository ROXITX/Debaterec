@echo off
REM ===========================================================================
REM  DebateRec launcher for Windows.  Double-click this file.
REM
REM  Lets you pick a reasoning backend, and for OFFLINE mode it will start the
REM  Ollama service, let you choose a local model, pull it if it is missing,
REM  and only then launch the app.  ONLINE mode uses the Gemini API; MOCK mode
REM  runs the deterministic rule-based debate with no network at all.
REM ===========================================================================
setlocal
cd /d "%~dp0"
title DebateRec

REM ---- locate Python --------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto no_python

REM ---- make sure dependencies are present ------------------------------------
%PY% -c "import fastapi, uvicorn, httpx, dotenv, numpy, sklearn" >nul 2>nul
if not errorlevel 1 goto menu
echo.
echo   Installing dependencies (first run only)...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto deps_failed

REM ===========================================================================
REM  MENU
REM ===========================================================================
:menu
echo.
echo   ===========================================================
echo      DebateRec  -  choose how the agents should reason
echo   ===========================================================
echo.
echo     1.  Offline  -  Ollama (local model, no API key)      [default]
echo     2.  Online   -  Gemini API (needs a free key)
echo     3.  Mock     -  deterministic, instant, no network
echo     4.  Just start with the current .env settings
echo.
set "CHOICE="
set /p "CHOICE=  Select 1-4 and press Enter: "
if not defined CHOICE set "CHOICE=1"

if "%CHOICE%"=="1" goto offline
if "%CHOICE%"=="2" goto online
if "%CHOICE%"=="3" goto mock
if "%CHOICE%"=="4" goto launch
echo   Please type 1, 2, 3 or 4.
goto menu

REM ===========================================================================
REM  OFFLINE  -  Ollama   (no labels inside () blocks: batch forbids that)
REM ===========================================================================
:offline
where ollama >nul 2>nul
if errorlevel 1 goto no_ollama

REM Is the daemon already answering?
ollama list >nul 2>nul
if not errorlevel 1 goto ollama_ready

echo.
echo   Starting the Ollama service...
start "Ollama" /min ollama serve
set /a TRIES=0

:waitollama
timeout /t 1 /nobreak >nul
ollama list >nul 2>nul
if not errorlevel 1 goto ollama_ready
set /a TRIES+=1
if %TRIES% geq 30 goto ollama_timeout
goto waitollama

:ollama_ready
echo.
echo   Installed Ollama models:
ollama list
echo.
set "MODEL="
set /p "MODEL=  Model to use [default llama3.1:8b]: "
if not defined MODEL set "MODEL=llama3.1:8b"

REM Pull it if it is not already present.
ollama list | findstr /I /C:"%MODEL%" >nul
if not errorlevel 1 goto have_model
echo.
echo   %MODEL% is not pulled yet. Downloading it now...
echo   (llama3.1:8b is about 4.7 GB - this can take a while the first time.)
echo.
ollama pull %MODEL%
if errorlevel 1 goto pull_failed

:have_model
echo.
echo   Configuring DebateRec for OFFLINE mode with %MODEL% ...
%PY% setup_key.py --ollama %MODEL%
goto launch

REM ===========================================================================
REM  ONLINE  -  Gemini
REM ===========================================================================
:online
%PY% setup_key.py --gemini >nul
echo.
echo   Checking your Gemini configuration...
%PY% setup_key.py --check
if not errorlevel 1 goto launch
echo.
echo   No working key yet. Let's set one up.
%PY% setup_key.py
goto launch

REM ===========================================================================
REM  MOCK
REM ===========================================================================
:mock
%PY% setup_key.py --mock
goto launch

REM ===========================================================================
REM  LAUNCH
REM ===========================================================================
:launch
echo.
echo   Starting DebateRec...  (the browser opens automatically)
echo   Leave this window open. Press Ctrl+C here to stop the server.
echo.
%PY% run.py
echo.
pause
goto end

REM ===========================================================================
REM  ERROR / EXIT PATHS
REM ===========================================================================
:ollama_timeout
echo.
echo   Ollama did not come up in time. Try running  ollama serve  in another
echo   window, then run this launcher again.
echo.
pause
goto menu

:pull_failed
echo.
echo   Could not pull %MODEL%. Check the model name and your connection.
echo.
pause
goto menu

:no_ollama
echo.
echo   Ollama is not installed.
echo   Download and install it from  https://ollama.com/download
echo   Then run this file again and pick Offline.
echo.
pause
goto menu

:deps_failed
echo.
echo   Dependency install failed. Fix the error above, then rerun this file.
echo.
pause
goto end

:no_python
echo.
echo   Python was not found on this machine.
echo   Install it from https://www.python.org/downloads/
echo   During install, tick "Add Python to PATH".
echo.
pause
goto end

:end
endlocal
