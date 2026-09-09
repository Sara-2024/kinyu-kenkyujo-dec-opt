@echo off
REM ================================================================
REM  作り直した AITrader.exe を GitHub に上げて、サイトから配る
REM
REM    先に tools\build-windows.bat を実行しておくこと。
REM    （public\download\AITrader.exe まで置き換わる）
REM
REM    このファイルをダブルクリックするだけ。黒い画面は出るが、
REM    終わったら閉じてよい。
REM ================================================================
chcp 65001 >nul
cd /d "%~dp0.."

echo.
echo ================================================================
echo   接続ツール（AITrader.exe）をサイトに配ります
echo ================================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] git が見つかりません。https://git-scm.com/download/win から入れてください。
  pause
  exit /b 1
)

if not exist public\download\AITrader.exe (
  echo [ERROR] public\download\AITrader.exe がありません。
  echo         先に tools\build-windows.bat を実行してください。
  pause
  exit /b 1
)

echo [1/4] 新しい exe かどうか確認しています...
git add public/download/AITrader.exe
git diff --cached --quiet -- public/download/AITrader.exe
if not errorlevel 1 (
  echo.
  echo   いまの exe は、すでに GitHub に上がっているものと同じでした。
  echo   作り直していない可能性があります。tools\build-windows.bat を先に実行してください。
  echo.
  pause
  exit /b 0
)

echo [2/4] 記録しています...
git commit -m "接続ツールの exe を作り直す" >nul
if errorlevel 1 (
  echo [ERROR] コミットできませんでした。
  pause
  exit /b 1
)

echo [3/4] GitHub へ送っています...
git push
if errorlevel 1 (
  echo.
  echo [ERROR] push できませんでした。
  echo         ユーザー名とパスワードを聞かれた場合は、ブラウザで GitHub にログインし直してください。
  echo.
  pause
  exit /b 1
)

echo [4/4] 完了。
echo.
echo ================================================================
echo   送りました。1〜2分でサイトから新しい接続ツールが配られます。
echo   確認: https://kinyu-kenkyujo-dec-opt.vercel.app/download/AITrader.exe
echo ================================================================
echo.
pause
