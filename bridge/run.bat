@echo off
rem VPSで常駐させる用。落ちても5秒後に自動で立ち上げ直す。
cd /d "%~dp0"
:loop
py -3 bridge.py
echo [run.bat] bridge.py が終了しました。5秒後に再起動します。
timeout /t 5 /nobreak >nul
goto loop
