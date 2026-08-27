@echo off
cd /d "%~dp0\bridge"

if not exist venv (
  echo.
  echo Run setup-windows.bat first.
  echo.
  pause
  exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo ========================================================
echo   MT5 connection check
echo ========================================================
echo.
echo  Make sure MT5 is running and you are logged in.
echo  Account number should show at top-left of MT5.
echo.
pause

python bridge.py --check

echo.
echo If account number appeared above, OK.
echo Next: double-click start-windows.bat
echo.
pause
