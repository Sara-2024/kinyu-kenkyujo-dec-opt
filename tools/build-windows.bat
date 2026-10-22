@echo off
REM ================================================================
REM  お客様に配る接続ツール（DreamlandPassport.exe / 表示名 ドリームランド・パスポート）を作る
REM
REM  Windows で一度だけ実行する。できあがった exe は
REM  Python も Node も入っていないPCで動き、黒い画面も出ない。
REM  同梱するのはブリッジ本体と EA だけ（venv や .env は入れない。
REM  接続先はクラウドの中継に固定されている）。
REM
REM    dist\DreamlandPassport.exe   … これをお客様にお渡しする
REM ================================================================
cd /d "%~dp0.."
REM Python は 3.12 を使う（MetaTrader5 の部品は新しすぎる Python 向けがまだ無い。
REM GitHub の Windows は py -3 が 3.15 を選ぶので、setup-python が置いた %pythonLocation% を優先する）
set "PY=py -3"
if defined pythonLocation if exist "%pythonLocation%\python.exe" set "PY="%pythonLocation%\python.exe""
py -3.12 -c "import sys" >nul 2>&1 && if not defined pythonLocation set "PY=py -3.12"


where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python が見つかりません。https://www.python.org から 64bit 版を入れてください。
  pause
  exit /b 1
)

echo [1/3] 必要なものを入れています...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install pyinstaller MetaTrader5 websockets python-dotenv certifi
if errorlevel 1 (
  echo [ERROR] pip install に失敗しました。
  pause
  exit /b 1
)

REM AIリスク監督の合言葉。bridge\risk_secret.py があれば exe に同梱する
set RISKARG=
if exist bridge\risk_secret.py (
  findstr /R /C:"TOKEN *= *\"\"" bridge\risk_secret.py >nul
  if not errorlevel 1 (
    echo.
    echo [ERROR] bridge\risk_secret.py の TOKEN が空のままです。
    echo         メモ帳で開いて、最後の行を次のように書き換えて保存してください:
    echo             TOKEN = "（サイトと同じ合言葉）"
    echo.
    pause
    exit /b 1
  )
  set RISKARG=--add-data "bridge\risk_secret.py;bridge"
  echo   AIリスク監督の合言葉を同梱します
) else (
  echo   bridge\risk_secret.py が無いので、AIの見張りは「切」で出荷されます
)

echo.
echo [2/3] exe を作っています（数分かかります）...
REM 出荷する EA はコンパイル済みだけ。名前は変わりうるので Yumekku で探す
set EA_FILE=
for %%f in (bridge\*Yumekku*.ex5) do set EA_FILE=%%f
if "%EA_FILE%"=="" (
  echo [ERROR] bridge\ にコンパイル済みの EA（*Yumekku*.ex5）がありません。
  echo         2_EAを入れ替える.bat で .ex5 を入れてから実行してください。
  pause
  exit /b 1
)
echo   同梱する EA: %EA_FILE%
if not exist bridge\ea_manifest.json (
  echo [ERROR] bridge\ea_manifest.json がありません。
  echo         %PY% tools\make-ea-manifest.py を実行してください。
  pause
  exit /b 1
)
REM 追加口座（ロイヤルファーストクラスの 2 つ目）に置く EA「安定低月利ver」。bridge\growth\ に分けて同梱する
set GROWTH_EA=
for %%f in (bridge\growth\*Yumekku*.ex5) do set GROWTH_EA=%%f
if "%GROWTH_EA%"=="" (
  echo [ERROR] bridge\growth\ に追加口座用の EA（*Yumekku*.ex5）がありません。
  echo         Mac で bash tools/mac/compile-ea.sh growth を実行して .ex5 を入れてください。
  pause
  exit /b 1
)
echo   同梱する EA（追加口座用）: %GROWTH_EA%
REM 控えは毎回作り直す（.ex5 を差し替えたのに古い控えが残ると「壊れている」扱いになる）
%PY% tools\make-ea-manifest.py --dir bridge\growth --quiet
if not exist bridge\growth\ea_manifest.json (
  echo [ERROR] bridge\growth\ea_manifest.json を作れませんでした。
  pause
  exit /b 1
)

%PY% -m PyInstaller --noconfirm --clean %RISKARG% ^
  --onefile --noconsole ^
  --name DreamlandPassport ^
  --splash tools\splash.png ^
  --add-data "bridge\bridge.py;bridge" ^
  --add-data "bridge\mt5_terminal.py;bridge" ^
  --add-data "bridge\mt5_detect.py;bridge" ^
  --add-data "bridge\gold_symbol.py;bridge" ^
  --add-data "bridge\ea_manager.py;bridge" ^
  --add-data "bridge\connect_state.py;bridge" ^
  --add-data "bridge\installer_ui.py;bridge" ^
  --add-data "bridge\risk_gate.py;bridge" ^
  --add-data "bridge\risk_features.py;bridge" ^
  --paths bridge ^
  --add-data "%EA_FILE%;bridge" ^
  --add-data "bridge\ea_manifest.json;bridge" ^
  --add-data "%GROWTH_EA%;bridge\growth" ^
  --add-data "bridge\growth\ea_manifest.json;bridge\growth" ^
  --add-data "bridge\TradingGate.mqh;bridge" ^
  --hidden-import bridge ^
  --hidden-import mt5_terminal ^
  --hidden-import mt5_detect ^
  --hidden-import gold_symbol ^
  --hidden-import ea_manager ^
  --hidden-import connect_state ^
  --hidden-import installer_ui ^
  --hidden-import tkinter ^
  --hidden-import tkinter.font ^
  --hidden-import MetaTrader5 ^
  --collect-all numpy ^
  --hidden-import logging.handlers ^
  --hidden-import concurrent.futures ^
  --hidden-import urllib.error ^
  --hidden-import urllib.request ^
  --hidden-import argparse ^
  --hidden-import inspect ^
  --hidden-import dataclasses ^
  --hidden-import functools ^
  --hidden-import random ^
  --hidden-import signal ^
  --hidden-import risk_features ^
  --hidden-import risk_gate ^
  --hidden-import websockets.exceptions ^
  --hidden-import websockets ^
  --hidden-import websockets.asyncio.client ^
  --hidden-import dotenv ^
  --hidden-import certifi ^
  --collect-data certifi ^
  connect.py
if errorlevel 1 (
  echo [ERROR] ビルドに失敗しました。
  pause
  exit /b 1
)

echo.
echo [3/3] 確認...
if not exist dist\DreamlandPassport.exe (
  echo [ERROR] dist\DreamlandPassport.exe ができていません。
  pause
  exit /b 1
)

REM 画面の部品（tkinter）が入っているか確かめる。
REM 入っていないと、お客様がダブルクリックしても窓が出ない（無言で終わる）。
%PY% -c "import sys;d=open(r'dist\DreamlandPassport.exe','rb').read();sys.exit(0 if b'_tkinter' in d else 1)"
if errorlevel 1 (
  echo [ERROR] 画面の部品が入っていません。この exe は配らないでください。
  echo         %PY% -m pip install --upgrade pyinstaller を試してから、もう一度実行してください。
  pause
  exit /b 1
)

REM サイトが配る場所へそのまま置く（あとは commit と push だけ）
if not exist public\download mkdir public\download
copy /Y dist\DreamlandPassport.exe public\download\DreamlandPassport.exe >nul
if errorlevel 1 (
  echo [ERROR] public\download\DreamlandPassport.exe に置けませんでした。
  pause
  exit /b 1
)

REM 3_リリースする.bat から呼ばれたときは、ここで止まらない。
REM （途中で「キーを押してください」と出ると、終わったように見えてしまう）
if "%~1"=="--from-release" exit /b 0

echo.
echo ================================================================
echo   できました: public\download\DreamlandPassport.exe
echo   表示名: ドリームランド・パスポート
echo.
echo   あとは、このファイルを commit して push すれば、サイトから配られます。
echo     git add public/download/DreamlandPassport.exe
echo     git commit -m "exe を作り直す"
echo     git push
echo ================================================================
echo.
pause
