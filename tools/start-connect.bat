@echo off
REM 調査用。ふだんは AITrader.vbs（画面が出ない方）を使う。
REM こちらは経過を画面に出しながら同じ処理を行う。
cd /d "%~dp0.."

if not exist bridge\venv\Scripts\python.exe (
  echo プロジェクト直下の「はじめる.bat」を先に一度実行してください。
  pause
  exit /b 1
)

call bridge\venv\Scripts\activate.bat
python connect.py --console
