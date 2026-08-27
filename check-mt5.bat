@echo off
chcp 65001 >nul
cd /d "%~dp0\bridge"

if not exist venv (
  echo.
  echo 先に setup-windows.bat をダブルクリックして実行してください。
  echo.
  pause
  exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo ========================================================
echo   MT5 接続チェック
echo ========================================================
echo.
echo  MT5 が起動していて、口座にログインしていることを確認してください。
echo  （画面左上に口座番号が出ていれば OK）
echo.
pause

python bridge.py --check

echo.
echo 口座番号が表示されれば成功です。
echo 次は start-windows.bat をダブルクリックしてください。
echo.
pause
