@echo off
cd /d "%~dp0"

echo.
echo ========================================================
echo   Trelab connection tool
echo   Log in inside MT5 as usual. Never type the password here.
echo ========================================================
echo.

if not exist bridge\venv\Scripts\python.exe (
  echo Run setup-windows.bat once before this tool.
  pause
  exit /b 1
)

call bridge\venv\Scripts\activate.bat
python connect.py
pause
