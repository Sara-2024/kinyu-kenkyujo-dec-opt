@echo off
cd /d "%~dp0..\bridge"

if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
)

echo.
echo Starting bridge - MT5 must be logged in.
echo Waiting for relay on port 8080...
echo Do NOT close this window.
echo.

where py >nul 2>&1
if %errorlevel%==0 (
  py -3 bridge.py
) else (
  python bridge.py
)
pause
