@echo off
setlocal EnableExtensions
REM Emily AI launcher — creates .venv if missing, installs deps, runs main.py
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "FIRST_SETUP=0"

where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo [Emily] Python not found. Install Python 3.10+ and add it to PATH.
        pause
        exit /b 1
    )
    set "PYLAUNCHER=py -3"
) else (
    set "PYLAUNCHER=python"
)

if not exist "%VENV_PY%" (
    echo [Emily] Creating virtual environment in %VENV_DIR%...
    %PYLAUNCHER% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [Emily] Failed to create virtual environment.
        pause
        exit /b 1
    )
    set "FIRST_SETUP=1"
)

echo [Emily] Installing dependencies...
"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [Emily] pip install failed.
    pause
    exit /b 1
)

echo [Emily] Configuring ONNX Runtime for Supertonic TTS...
"%VENV_PY%" "%~dp0scripts\ensure_onnxruntime.py"
if errorlevel 1 (
    echo [Emily] ONNX Runtime setup failed. Supertonic will try CPU fallback.
)

if "%FIRST_SETUP%"=="1" (
    echo [Emily] Installing Playwright browsers ^(first-time setup^)...
    "%VENV_PY%" -m playwright install
    if errorlevel 1 (
        echo [Emily] Playwright browser install failed. Browser automation may not work.
    )
)

echo [Emily] Starting E.M.I.L.Y....
"%VENV_PY%" -W ignore main.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [Emily] Exited with code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
