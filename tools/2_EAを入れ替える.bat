@echo off
chcp 932 >nul
title MT5 Automatic b EA‚ğ“ü‚ê‘Ö‚¦‚é
cd /d "%~dp0.."
py -3 tools\swap-ea.py %*
