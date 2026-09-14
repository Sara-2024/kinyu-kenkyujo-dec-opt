@echo off
chcp 932 >nul
title MT5 Automatic b ó‘Ô‚ğŒ©‚é
cd /d "%~dp0.."
py -3 tools\check-install.py
echo.
pause
