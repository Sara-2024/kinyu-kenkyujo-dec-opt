@echo off
chcp 932 >nul
title AI Trader Connect ｜ MT5を選び直す
cd /d "%~dp0.."
if exist dist\AITrader.exe (
  dist\AITrader.exe --choose
) else (
  py -3 connect.py --choose --console
)
echo.
echo   選び直しました。この画面は閉じて構いません。
echo.
pause
