@echo off
title トレード研究所 ｜ はじめる
cd /d "%~dp0"
cls

echo.
echo  ============================================================
echo    トレード研究所  接続ツール
echo  ============================================================
echo.
echo    はじめての準備をします。このファイルを開くのは最初の1回だけです。
echo    経過が見えるように、この画面には途中の様子を出しています。
echo    次からはサイトのボタンだけでつながります（画面は出ません）。
echo.
echo  ------------------------------------------------------------
echo.

set "LOCALMODE="
set "HASCURL="
where curl >nul 2>&1
if not errorlevel 1 set "HASCURL=1"

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
REM  4/5  どちらで動かすか
REM ============================================================
echo   [4/5]  つなぎ先
echo.
echo            そのまま Enter ... トレード研究所のサイトにつなぐ（ふつうはこちら）
echo            1 を入れて Enter ... テスト（このパソコンの中だけ。Node.js が要ります）
echo.
set "MODE=2"
set /p MODE=         Enter を押してください:
echo.

if not "%MODE%"=="1" goto HONBAN

REM ------------------------------------------------------------
REM  テスト … 中継も画面も、このパソコンの中で動かす
REM ------------------------------------------------------------
set "LOCALMODE=1"
where node >nul 2>&1
if errorlevel 1 (
  echo   [!]  Node.js が入っていません。
  echo.
  echo        テストは、このパソコンの中に中継サーバーを立てるので
  echo        Node.js が要ります。https://nodejs.org の LTS 版を入れて、
  echo        このファイルをもう一度開いてください。
  echo.
  echo        入れずに進めるなら、いったん 2（本番のサイト）を選んでください。
  echo.
  pause
  exit /b 1
)

REM 画面が見にいく中継（.env より .env.local が優先されます）
> .env.local echo VITE_RELAY_URL=ws://localhost:8080/app
REM ブリッジがつなぐ中継。bridge\.env を丸ごと書き直すと、サイトから
REM 受け取った部屋（会員ID）が消えてしまうので、接続先の1項目だけ直す
set "RELAY=ws://127.0.0.1:8080/bridge"

if not exist server\node_modules (
  echo          中継サーバーの準備をしています。数分かかります...
  call npm install --prefix server --silent
)
if not exist node_modules (
  echo          画面の準備をしています。数分かかります...
  call npm install --silent
)

echo          中継サーバーと画面を、裏側で起動します...
wscript "%~dp0tools\run-hidden.vbs" "cmd /c npm start" "%~dp0server"
wscript "%~dp0tools\run-hidden.vbs" "cmd /c npm run dev" "%~dp0"
set "SITE=http://localhost:5181"

REM 中継が応えるまで待つ（最大30秒）
if not defined HASCURL (
  timeout /t 10 /nobreak >nul
  goto CONNECT
)
set /a TRY=0
:WAITRELAY
curl -s -o nul -m 2 http://127.0.0.1:8080/health
if not errorlevel 1 goto RELAYOK
set /a TRY+=1
if %TRY% geq 15 goto RELAYNG
timeout /t 2 /nobreak >nul
goto WAITRELAY
:RELAYOK
echo          OK  中継サーバーが動きました
goto CONNECT
:RELAYNG
echo   [!]  中継サーバーが立ち上がりませんでした。
echo        Node.js が正しく入っているか確認してください。
echo        このまま続けるなら Enter を押してください...
pause >nul
goto CONNECT

REM ------------------------------------------------------------
REM  本番 … クラウドの中継につなぐ
REM ------------------------------------------------------------
:HONBAN
REM テストのときに書いた「画面の接続先」は本番では邪魔になるので消す
if exist .env.local del .env.local
set "RELAY=wss://kinyu-relay.onrender.com/bridge"
set "SITE=https://kinyu-kenkyujo-dec-opt.vercel.app"
echo          接続先: クラウドの中継サーバー
if not defined HASCURL goto CONNECT
echo          届くか確認しています。しばらくお待ちください...
curl -s -m 45 -o nul https://kinyu-relay.onrender.com/health
if errorlevel 1 (
  echo.
  echo   [!]  クラウドの中継サーバーに届きませんでした。
  echo        Render の中継がまだ立っていない可能性があります。
  echo        その場合は 1（テスト）で試してください。
  echo.
  echo        このまま続けるなら Enter を押してください...
  pause >nul
) else (
  echo          OK  中継サーバーは動いています
)
goto CONNECT

REM ============================================================
REM  5/5  つなぐ（MT5の確認・システム配置・ブリッジ起動・登録）
REM ============================================================
:CONNECT
echo.
echo   [5/5]  つなぎます
echo  ------------------------------------------------------------
bridge\venv\Scripts\python.exe connect.py --console --relay %RELAY%
echo  ------------------------------------------------------------
echo.

REM テストのときは、画面が立ち上がるのを待ってから開く（最大60秒）
if not defined LOCALMODE goto OPENSITE
if not defined HASCURL (
  timeout /t 10 /nobreak >nul
  goto OPENSITE
)
echo   画面の準備を待っています...
set /a TRY=0
:WAITSITE
curl -s -o nul -m 2 http://localhost:5181
if not errorlevel 1 goto OPENSITE
set /a TRY+=1
if %TRY% geq 30 goto SITENG
timeout /t 2 /nobreak >nul
goto WAITSITE
:SITENG
echo   [!]  画面が立ち上がりませんでした。
echo        別のものが 5181 番を使っている可能性があります。
echo        Enter を押すと、そのままブラウザを開いてみます...
pause >nul

:OPENSITE
echo   サイトを開きます: %SITE%
start "" "%SITE%"

echo.
echo  ============================================================
echo    ここからサイトで試せます
echo.
echo      1. 受付のユイをクリック →「初期設定をはじめる」
echo         → 数秒で連携まで進みます
echo         （サイトの初期設定の途中なら、そのまま自動で先に進みます）
echo      2. アルゴ（自動売買）→「自動売買をはじめる」で稼働
echo      3. 「今日の成績」「過去の成績」「いまのポジション」
echo      4. リン（チャート分析）→「トレードを添削して」
echo.
echo    次からは、このファイルを開く必要はありません。
echo    サイトのボタンだけでつながります。
echo    （パソコンを立ち上げ直したときも自動でつながります）
echo.
echo    止めたいとき:  tools\停止する.bat
echo    連携をやめるとき: tools\連携を解除する.bat
echo.
echo    うまくいかないときの記録:
echo      %%LOCALAPPDATA%%\AITrader\connect.log
echo  ============================================================
echo.
echo    この画面は閉じても大丈夫です（裏側で動き続けます）。
echo.
pause
