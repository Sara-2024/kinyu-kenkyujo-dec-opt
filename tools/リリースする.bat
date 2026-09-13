@echo off
chcp 932 >nul
title AI Trader Connect b ì‚é
cd /d "%~dp0.."
py -3 tools\build-release.py
echo.
pause
