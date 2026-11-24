@echo off
REM ===========================================
REM TradingBot "Крон" — Windows Launcher
REM ===========================================

echo =========================================
echo  TradingBot Крон - Quick Start (Windows)
echo =========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Install Python 3.10+ first.
    pause
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist ".venv" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
)

REM Activate venv
echo [2/4] Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install requirements
if not exist ".venv\Lib\site-packages\MetaTrader5" (
    echo [3/4] Installing dependencies...
    pip install -r requirements.txt
)

REM Check if .env exists
if not exist ".env" (
    echo [WARNING] .env file not found! Create it from .env.example
    echo [INFO]   Copy your MT5 credentials, BOT_TOKEN etc.
    pause
) else (
    echo [4/4] Configuration found! Starting bot...
)

echo.
echo =========================================
echo  Choose mode:
echo   1) Demo account (MT5 orders)
echo   2) Real mode
echo   3) Analyze only (exit after analysis)
echo ========================================= 
echo.
set /p MODE="Enter choice (1, 2, 3): "

if "%MODE%"=="1" (
    echo [INFO] Starting on DEMO account...
    python main.py --demo
) else if "%MODE%"=="2" (
    echo [WARNING] Starting on REAL account! 
    python main.py
) else if "%MODE%"=="3" (
    set /p SYMBOL="Enter symbol to analyze (e.g., EURUSD): "
    python main.py --analyze %SYMBOL%
) else (
    echo [ERROR] Unknown mode. Defaulting to demo.
    python main.py --demo
)

echo.
pause
