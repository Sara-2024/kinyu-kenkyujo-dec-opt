@echo off
cd /d "%~dp0.."

echo.
echo ========================================================
echo   Trelab - First-time setup (run once)
echo ========================================================
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not found.
  echo Install LTS from https://nodejs.org then run this again.
  pause
  exit /b 1
)

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python not found.
  echo Install 64-bit Python from https://www.python.org
  echo Check "Add python.exe to PATH" during install.
  pause
  exit /b 1
)

echo [1/3] Bridge...
cd bridge
if not exist venv (
  py -3 -m venv venv
)
call venv\Scripts\activate.bat
pip install -r requirements.txt
cd ..

echo.
echo [2/3] Relay server...
cd server
call npm install
cd ..

echo.
echo [3/3] Web UI...
call npm install

echo.
echo ========================================================
echo   Setup complete!
echo.
echo   Next:
echo     1. Open MT5 and log in
echo     2. Double-click check-mt5.bat
echo     3. Double-click start-windows.bat
echo ========================================================
echo.
pause
