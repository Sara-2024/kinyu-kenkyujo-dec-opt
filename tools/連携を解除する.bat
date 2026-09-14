@echo off
title MT5 Automatic ｜ 連携を解除する
cd /d "%~dp0.."

echo.
echo  ============================================================
echo    このパソコンの連携をすべて解除します
echo  ============================================================
echo.
echo    ・裏で動いている接続を止めます
echo    ・PC起動時の自動接続を消します
echo    ・サイトのボタンからの起動（trelab://）を消します
echo.
echo    MT5 と、配置ずみのシステム(EA)はそのまま残ります。
echo.
set "YN=n"
set /p YN=   解除してよければ y を入れて Enter:
if /i not "%YN%"=="y" (
  echo.
  echo   やめました。
  echo.
  pause
  exit /b 0
)
echo.

if not exist bridge\venv\Scripts\python.exe (
  echo   [!] まだ準備ができていません。
  echo.
  pause
  exit /b 1
)

bridge\venv\Scripts\python.exe connect.py --uninstall --console

echo.
echo    解除しました。もう一度使うときは「はじめる.bat」から。
echo.
pause
