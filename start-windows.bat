@echo off
cd /d "%~dp0"

if not exist bridge\venv (
  echo.
  echo Run setup-windows.bat first.
  echo.
  pause
  exit /b 1
)

echo.
echo ========================================================
echo   Starting demo (3 windows will open)
echo ========================================================
echo.
echo  Confirm MT5 is running and logged in.
echo  Do NOT close the 3 black windows.
echo.
timeout /t 4 /nobreak >nul

start "Relay" cmd /k "cd /d %~dp0server && npm start"
timeout /t 5 /nobreak >nul

start "Bridge" cmd /k "cd /d %~dp0bridge && call venv\Scripts\activate.bat && echo Waiting for relay on port 8080... && python bridge.py"
timeout /t 4 /nobreak >nul

start "WebUI" cmd /k "cd /d %~dp0 && npm run dev"
timeout /t 4 /nobreak >nul

echo Opening browser...
start http://localhost:5181

echo.
echo ========================================================
echo   Open http://localhost:5181 in browser
echo.
echo   Demo flow:
echo     1. Click Yui (reception)
echo     2. Click Algo (auto trading)
echo     3. Start auto trading, enter email, wait 4 sec
echo     4. Open control panel, press STOP
echo     5. In MT5 press F3 to see AI_TRADING_ALLOWED change
echo ========================================================
echo.
pause
