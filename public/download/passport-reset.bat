@echo off
REM ドリームランド・パスポートの紐づけを消して、最初からやり直せるようにする。
REM （2 つ目の口座で 1 つ目が入れ替わってしまった VPS を戻すときに使う）
REM   1. 動いているパスポートを止める
REM   2. 紐づけの記録（state.json / bridge.env / accounts）を消す
REM   3. ロビーを開く → 1 つ目の口座から「パスポートの発行」をやり直す
REM MT5 と EA はそのまま。口座や建玉には触らない。
title ドリームランド・パスポートをやり直す
echo.
echo  ドリームランド・パスポートの紐づけを消して、やり直せるようにします。
echo  （MT5 や口座、建玉には触りません）
echo.
taskkill /f /im DreamlandPassport.exe >nul 2>&1
taskkill /f /im MT5Automatic.exe >nul 2>&1
taskkill /f /im AITrader.exe >nul 2>&1
taskkill /f /im pythonw.exe >nul 2>&1
timeout /t 2 /nobreak >nul
set "D=%LOCALAPPDATA%\AITrader"
del /f /q "%D%\state.json" >nul 2>&1
del /f /q "%D%\bridge.env" >nul 2>&1
del /f /q "%D%\intent.json" >nul 2>&1
rd /s /q "%D%\accounts" >nul 2>&1
if exist "%D%\state.json" (
  echo  [NG] まだ消せていません。もう一度このファイルを開いてください。
  pause
  exit /b 1
)
echo  [OK] 消しました。
echo.
echo  このあと：
echo    1. MT5 を 2 つとも開いてログインしておく
echo    2. 開いたロビーで、合言葉 → 1 つ目の口座から「パスポートの発行」
echo    3. つながったら「2 つ目の口座を今から設置する」→ 2 つ目の口座番号
echo.
start "" https://dreamland-lobby.vercel.app/#connect
pause
