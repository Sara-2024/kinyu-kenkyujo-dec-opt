@echo off
title MT5 Automatic ｜ 接続をやめる
cd /d "%~dp0.."

echo.
echo  ============================================================
echo    裏で動いている接続を止めます
echo  ============================================================
echo.
echo    MT5 と サイト のつなぎ役（ブリッジ）を終了します。
echo    MT5 そのものは閉じません。
echo.
echo    もう一度つなぐときは「はじめる.bat」か、
echo    サイトの「自動売買をはじめる」を押してください。
echo.

if not exist bridge\venv\Scripts\python.exe (
  echo   [!] まだ準備ができていません（はじめる.bat を先に実行してください）。
  echo.
  pause
  exit /b 1
)

bridge\venv\Scripts\python.exe connect.py --stop --console

echo.
echo  ------------------------------------------------------------
echo    PCを立ち上げ直したときの自動接続まで止めるには、
echo    このあと「連携を解除する.bat」を実行してください。
echo  ------------------------------------------------------------
echo.
pause
