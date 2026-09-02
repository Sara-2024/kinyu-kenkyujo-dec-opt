@echo off
REM MT5 につながるかだけ確かめる（画面に結果を出す調査用）
cd /d "%~dp0..\bridge"

if not exist venv (
  echo プロジェクト直下の「はじめる.bat」を先に一度実行してください。
  pause
  exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo ========================================================
echo   MT5 接続チェック
echo   MT5 を起動してログインした状態で実行してください。
echo ========================================================
echo.

python bridge.py --check

echo.
pause
