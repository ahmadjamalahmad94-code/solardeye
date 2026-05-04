@echo off
chcp 65001 >nul
title Solardeye - Local Preview
cd /d "%~dp0"

echo ============================================================
echo   Solardeye - Local Preview Launcher
echo ============================================================
echo.

REM ---- 1) Check Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python not found. Please install Python 3.11 from python.org
    pause
    exit /b 1
)

REM ---- 2) Create venv if missing ----
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [X] Failed to create venv
        pause
        exit /b 1
    )
)

REM ---- 3) Activate venv ----
call ".venv\Scripts\activate.bat"

REM ---- 4) Install/upgrade dependencies ----
echo [*] Installing dependencies (first run takes a minute) ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [X] Failed to install requirements
    pause
    exit /b 1
)

REM ---- 5) Load .env.local into environment ----
echo [*] Loading .env.local ...
for /f "usebackq tokens=1* delims==" %%A in (".env.local") do (
    set "line=%%A"
    setlocal enabledelayedexpansion
    if not "!line:~0,1!"=="#" if not "!line!"=="" (
        endlocal
        set "%%A=%%B"
    ) else (
        endlocal
    )
)

REM ---- 6) Open browser after short delay ----
start "" cmd /c "timeout /t 4 >nul & start http://localhost:5000"

echo.
echo ============================================================
echo   Starting Flask on http://localhost:5000
echo   Press Ctrl+C to stop the server
echo ============================================================
echo.

python app.py

pause
