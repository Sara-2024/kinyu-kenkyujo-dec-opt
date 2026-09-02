@echo off
chcp 65001 >nul
title トレード研究所 ｜ はじめる
cd /d "%~dp0"
cls

echo.
echo  ============================================================
echo    トレード研究所  接続ツール
echo  ============================================================
echo.
echo    このファイルは「あなたが確認するとき」用です。
echo    経過が見えるように、わざと画面を出しています。
echo    お客様が使うときは何も表示されません（TrelabConnect.vbs）。
echo.
echo  ------------------------------------------------------------
echo.

REM ============================================================
REM  1/5  MT5 が起動してログインしているか
REM ============================================================
echo   [1/5]  MT5 の確認
tasklist /fi "imagename eq terminal64.exe" 2>nul | find /i "terminal64.exe" >nul
if errorlevel 1 (
  echo.
  echo          MT5 がまだ起動していません。
  echo          MT5 を開いて、いつも通り口座にログインしてください。
  echo          （口座番号が MT5 の左上に出ていれば大丈夫です）
  echo.
  echo          ログインできたら Enter を押してください...
  pause >nul
) else (
  echo          OK  MT5 は起動しています
)
echo.

REM ============================================================
REM  2/5  Python があるか
REM ============================================================
echo   [2/5]  Python の確認
where py >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [!]  Python が入っていません。
  echo.
  echo        https://www.python.org から 64bit 版を入れてください。
  echo        インストール画面の「Add python.exe to PATH」に
  echo        必ずチェックを入れてください。
  echo.
  echo        入れ終わったら、このファイルをもう一度開いてください。
  echo.
  pause
  exit /b 1
)
echo          OK  Python はあります
echo.

REM ============================================================
REM  3/5  はじめての準備（2回目からは飛ばします）
REM ============================================================
echo   [3/5]  必要なものの準備
if exist bridge\venv\Scripts\python.exe (
  echo          OK  準備ずみ
) else (
  echo          はじめての準備をしています。3分ほどかかります...
  py -3 -m venv bridge\venv
  if errorlevel 1 (
    echo.
    echo   [!]  準備に失敗しました。Python が 64bit 版か確認してください。
    echo.
    pause
    exit /b 1
  )
  bridge\venv\Scripts\python.exe -m pip install --upgrade pip -q
  bridge\venv\Scripts\python.exe -m pip install -q -r bridge\requirements.txt
  if errorlevel 1 (
    echo.
    echo   [!]  必要なものを入れられませんでした。
    echo        インターネットにつながっているか確認してください。
    echo.
    pause
    exit /b 1
  )
  echo          OK  準備できました
)
echo.

REM ============================================================
REM  4/5  どちらで確認するか
REM ============================================================
echo   [4/5]  どちらで確認しますか？
echo.
echo            1 ... 本番のサイトで確認する（おすすめ・この1台で完結）
echo            2 ... このパソコンの中だけで確認する（Node.js が要ります）
echo.
set "MODE=1"
set /p MODE=         番号を入れて Enter（そのまま Enter なら 1）:
echo.

if "%MODE%"=="2" goto LOCAL

REM ---- 本番のサイトにつなぐ ----
> bridge\.env echo TRELAB_WS_URL=wss://kinyu-relay.onrender.com/bridge
>> bridge\.env echo BRIDGE_ID=vps-01
>> bridge\.env echo GV_NAME=AI_TRADING_ALLOWED
>> bridge\.env echo GV_DEFAULT=1
>> bridge\.env echo LOG_LEVEL=INFO
set "SITE=https://kinyu-kenkyujo-dec-opt.vercel.app"
echo          接続先: クラウドの中継サーバー
echo          届くか確認しています。しばらくお待ちください...
curl -s -m 45 https://kinyu-relay.onrender.com/health >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [!]  クラウドの中継サーバーに届きませんでした。
  echo        Render の中継が止まっている可能性があります。
  echo        いったん 2「このパソコンの中だけ」で試すこともできます。
  echo.
  echo        このまま続けるなら Enter を押してください...
  pause >nul
) else (
  echo          OK  中継サーバーは動いています
)
goto CONNECT

:LOCAL
REM ---- このパソコンの中だけでつなぐ ----
where node >nul 2>&1
if errorlevel 1 (
  echo   [!]  Node.js が入っていません。
  echo        https://nodejs.org から LTS 版を入れるか、1 を選んでください。
  echo.
  pause
  exit /b 1
)
> bridge\.env echo TRELAB_WS_URL=ws://127.0.0.1:8080/bridge
>> bridge\.env echo BRIDGE_ID=vps-01
>> bridge\.env echo GV_NAME=AI_TRADING_ALLOWED
>> bridge\.env echo GV_DEFAULT=1
>> bridge\.env echo LOG_LEVEL=INFO
if not exist server\node_modules (
  echo          中継サーバーの準備をしています...
  call npm install --prefix server --silent
)
if not exist node_modules (
  echo          画面の準備をしています...
  call npm install --silent
)
echo          中継サーバーと画面を裏側で起動します...
wscript "%~dp0tools\run-hidden.vbs" "cmd /c npm start" "%~dp0server"
wscript "%~dp0tools\run-hidden.vbs" "cmd /c npm run dev" "%~dp0"
set "SITE=http://localhost:5181"
echo          接続先: このパソコンの中継サーバー
goto CONNECT

REM ============================================================
REM  5/5  つなぐ（MT5の確認・システム配置・ブリッジ起動・登録）
REM ============================================================
:CONNECT
echo.
echo   [5/5]  つなぎます
echo  ------------------------------------------------------------
bridge\venv\Scripts\python.exe connect.py --console
echo  ------------------------------------------------------------
echo.

timeout /t 3 /nobreak >nul
echo   サイトを開きます: %SITE%
start "" "%SITE%"

echo.
echo  ============================================================
echo    ここからサイトで試せます
echo.
echo      1. アルゴ（自動売買）をクリック
echo      2. 「自動売買をはじめる」を押す
echo         → 数秒で接続まで進みます
echo      3. 「今日の成績」「過去の成績」「いまのポジション」
echo      4. リン（チャート分析）→「トレードを添削して」
echo.
echo    次からは、このファイルを開く必要はありません。
echo    サイトのボタンだけでつながります。
echo    （パソコンを立ち上げ直したときも自動でつながります）
echo.
echo    うまくいかないときの記録:
echo      %%LOCALAPPDATA%%\Trelab\connect.log
echo  ============================================================
echo.
pause
