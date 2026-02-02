@echo off
chcp 65001 >nul 2>&1
title GMAT Focus AI Tutor - LAN Mode

echo.
echo ========================================
echo   GMAT Focus AI Tutor - LAN Mode
echo   Phone access via WiFi
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+
    pause
    exit /b 1
)

REM Install deps
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install streamlit pandas pypdf openai -q
)

REM Try to add firewall rule (needs admin, will silently fail if not admin)
netsh advfirewall firewall delete rule name="GMAT Tutor Streamlit" >nul 2>&1
netsh advfirewall firewall add rule name="GMAT Tutor Streamlit" dir=in action=allow protocol=TCP localport=8501 >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARNING] Could not add firewall rule automatically.
    echo If your phone cannot connect, please either:
    echo   1. Right-click this file and "Run as administrator"
    echo   2. Or manually allow port 8501 in Windows Firewall
    echo.
)

REM Get local IP
set LOCAL_IP=unknown
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4" 2^>nul') do (
    for /f "tokens=1" %%b in ("%%a") do (
        set LOCAL_IP=%%b
    )
)

echo.
echo ================================================
echo.
echo   Open this URL on your phone browser:
echo.
echo   http://%LOCAL_IP%:8501
echo.
echo   Make sure phone and PC are on the same WiFi.
echo.
echo   If phone cannot connect:
echo     - Right-click this file, Run as administrator
echo     - Or allow port 8501 in Windows Firewall
echo.
echo ================================================
echo.
echo Press Ctrl+C to stop the server.
echo.

python -m streamlit run app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true --browser.gatherUsageStats=false

echo.
echo Server stopped.
pause
