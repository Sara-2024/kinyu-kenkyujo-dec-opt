@echo off
REM ================================================================
REM  サイト側で直したものを、このPCに取り込む（git pull）
REM
REM    ダブルクリックするだけ。黒い画面は出るが、終わったら閉じてよい。
REM    exe を作り直す前に、これを実行しておく。
REM ================================================================
cd /d "%~dp0.."

echo.
echo ================================================================
echo   最新のものを取り込みます
echo ================================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] git が見つかりません。https://git-scm.com/download/win から入れてください。
  pause
  exit /b 1
)

git pull
if errorlevel 1 (
  echo.
  echo [ERROR] 取り込めませんでした。
  echo         この画面をそのまま送ってください。
  echo.
  pause
  exit /b 1
)

echo.
echo ================================================================
echo   取り込みました。
echo   このあと exe を作り直すときは:
echo     1. tools\build-windows.bat
echo     2. tools\exeを配る.bat
echo ================================================================
echo.
pause
