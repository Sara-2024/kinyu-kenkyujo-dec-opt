@echo off
cd /d "%~dp0bridge"

if not exist venv (
  echo Run setup-windows.bat first.
  pause
  exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo Starting bridge - MT5 must be logged in.
echo Waiting for relay on port 8080...
echo Do NOT close this window.
echo.
python bridge.py
pause
