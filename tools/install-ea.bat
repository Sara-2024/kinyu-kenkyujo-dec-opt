@echo off
cd /d "%~dp0.."

echo.
echo ========================================================
echo   Install EA into logged-in MT5
echo   (no relay / bridge - files only)
echo ========================================================
echo.

if not exist bridge\venv\Scripts\python.exe (
  echo プロジェクト直下の「はじめる.bat」を先に一度実行してください。
  pause
  exit /b 1
)

call bridge\venv\Scripts\activate.bat
python connect.py --install-ea
pause
