@echo off
chcp 65001 >nul 2>&1
title GMAT Focus AI Tutor

echo.
echo ========================================
echo   GMAT Focus AI Tutor
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [1/3] Checking dependencies...
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo       Installing streamlit...
    pip install streamlit pandas pypdf openai -q
)

echo [2/3] Dependencies OK
echo [3/3] Starting app...
echo.
echo ----------------------------------------
echo   Browser will open automatically.
echo   If not, visit: http://localhost:8501
echo   Press Ctrl+C to stop.
echo ----------------------------------------
echo.

python -m streamlit run app.py --server.headless=false --browser.gatherUsageStats=false

echo.
echo App stopped.
pause
