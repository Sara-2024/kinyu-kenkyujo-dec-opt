@echo off
title AIトレーダー ｜ 状態を見る
cd /d "%~dp0.."

echo.
echo  ============================================================
echo    いまの状態を表示します（うまくつながらないときに）
echo  ============================================================
echo.
echo    この画面を写真に撮って送ってください。
echo.

if not exist bridge\venv\Scripts\python.exe (
  echo   [!] まだ準備ができていません（はじめる.bat を先に実行してください）。
  echo.
  pause
  exit /b 1
)

bridge\venv\Scripts\python.exe connect.py --status --console

echo.
pause
