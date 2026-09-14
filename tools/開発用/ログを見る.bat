@echo off
chcp 932 >nul
title MT5‚ÌƒƒO‚ğŒ©‚é
cd /d "%~dp0..\.."
py -3 tools\log-peek.py
echo.
pause
