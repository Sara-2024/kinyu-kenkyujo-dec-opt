@echo off
chcp 932 >nul
title AI Trader Connect ｜ 最新にする
cd /d "%~dp0.."

echo.
echo ================================================================
echo   最新のものを取り込みます
echo ================================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] git が見つかりません。
  echo         https://git-scm.com/download/win から入れてください。
  pause
  exit /b 1
)

REM 作ったもの（ea_manifest.json など）が邪魔をして取り込めないので、
REM いったん脇に置いてから取り込み、あとで戻す。
set STASHED=0
git diff --quiet
if errorlevel 1 set STASHED=1
git diff --cached --quiet
if errorlevel 1 set STASHED=1

if "%STASHED%"=="1" (
  echo 手元の変更をいったん脇に置きます...
  git stash push -u -m "最新にする.bat"
)

git pull
if errorlevel 1 (
  echo.
  echo [ERROR] 取り込めませんでした。この画面をそのまま送ってください。
  if "%STASHED%"=="1" git stash pop
  pause
  exit /b 1
)

if "%STASHED%"=="1" (
  echo 脇に置いた変更を戻します...
  git stash pop
)

echo.
echo ================================================================
echo   取り込みました。
echo.
echo   次は  2_リリースする.bat  を押してください。
echo ================================================================
echo.
pause
