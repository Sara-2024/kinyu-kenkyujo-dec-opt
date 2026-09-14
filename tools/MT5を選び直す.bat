@echo off
chcp 932 >nul
title MT5 Automatic ｜ MT5を選び直す
cd /d "%~dp0.."

REM ソースから動かす（こちらの道具なので Python がある前提）。
REM exe を先に使うと、作り直すまで直したものが反映されない。
py -3 connect.py --choose --console
if errorlevel 9009 (
  echo Python が無いので、作ってある exe で動かします
  dist\AITrader.exe --choose
)
echo.
echo   選び直しました。この画面は閉じて構いません。
echo.
pause
