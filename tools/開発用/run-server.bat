@echo off
cd /d "%~dp0..\server"

if not exist node_modules (
  echo Installing relay server...
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install failed. Is Node.js installed?
    pause
    exit /b 1
  )
)

echo.
echo Starting relay on port 8080...
echo Do NOT close this window.
echo.
npm start
pause
