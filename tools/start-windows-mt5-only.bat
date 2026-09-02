@echo off
cd /d "%~dp0.."

if not exist bridge\venv (
  echo プロジェクト直下の「はじめる.bat」を先に一度実行してください。
  pause
  exit /b 1
)

echo.
echo ========================================================
echo   Relay + Bridge only (Web UI runs on another PC)
echo ========================================================
echo.
echo  MT5 must be running and logged in on this PC.
echo  Do NOT close the 2 black windows.
echo.
timeout /t 3 /nobreak >nul

start "Relay" cmd /k "cd /d %~dp0..\server && npm start"
timeout /t 2 /nobreak >nul

start "Bridge" cmd /k "cd /d %~dp0..\bridge && call venv\Scripts\activate.bat && python bridge.py"

echo.
echo ========================================================
echo   Running on this PC:
echo     Relay  ws://THIS_PC_IP:8080
echo     Bridge -^> MT5
echo.
echo   On your Mac, set in .env:
echo     VITE_RELAY_URL=ws://THIS_PC_IP:8080/app
echo.
echo   Find THIS_PC_IP: open cmd and run  ipconfig
echo   Use the IPv4 address (e.g. 192.168.1.5)
echo ========================================================
echo.
pause
