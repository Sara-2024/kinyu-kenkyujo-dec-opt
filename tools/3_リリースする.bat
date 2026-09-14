@echo off
chcp 932 >nul
title MT5 Automatic b ì‚é
cd /d "%~dp0.."
py -3 tools\build-release.py
echo.
pause
