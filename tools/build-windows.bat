@echo off
REM ================================================================
REM  お客様に配る接続ツール（AITrader.exe / 表示名 AIトレーダー）を作る
REM
REM  Windows で一度だけ実行する。できあがった exe は
REM  Python も Node も入っていないPCで動き、黒い画面も出ない。
REM  同梱するのはブリッジ本体と EA だけ（venv や .env は入れない。
REM  接続先はクラウドの中継に固定されている）。
REM
REM    dist\AITrader.exe   … これをお客様にお渡しする
REM ================================================================
cd /d "%~dp0.."

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python が見つかりません。https://www.python.org から 64bit 版を入れてください。
  pause
  exit /b 1
)

echo [1/3] 必要なものを入れています...
py -3 -m pip install --upgrade pip >nul
py -3 -m pip install pyinstaller MetaTrader5 websockets python-dotenv
if errorlevel 1 (
  echo [ERROR] pip install に失敗しました。
  pause
  exit /b 1
)

REM AIリスク監督の合言葉。bridge\risk_secret.py があれば exe に同梱する
set RISKARG=
if exist bridge\risk_secret.py (
  set RISKARG=--add-data "bridge\risk_secret.py;bridge"
  echo   AIリスク監督の合言葉を同梱します
) else (
  echo   bridge\risk_secret.py が無いので、AIの見張りは「切」で出荷されます
)

echo.
echo [2/3] exe を作っています（数分かかります）...
py -3 -m PyInstaller --noconfirm --clean %RISKARG% ^
  --onefile --noconsole ^
  --name AITrader ^
  --add-data "bridge\bridge.py;bridge" ^
  --add-data "bridge\mt5_terminal.py;bridge" ^
  --add-data "bridge\OrbitGoldEA_v5.mq5;bridge" ^
  --add-data "bridge\TradingGate.mqh;bridge" ^
  --hidden-import bridge ^
  --hidden-import mt5_terminal ^
  --hidden-import MetaTrader5 ^
  --hidden-import websockets ^
  --hidden-import websockets.asyncio.client ^
  --hidden-import dotenv ^
  connect.py
if errorlevel 1 (
  echo [ERROR] ビルドに失敗しました。
  pause
  exit /b 1
)

echo.
echo [3/3] 確認...
if not exist dist\AITrader.exe (
  echo [ERROR] dist\AITrader.exe ができていません。
  pause
  exit /b 1
)

REM サイトが配る場所へそのまま置く（あとは commit と push だけ）
if not exist public\download mkdir public\download
copy /Y dist\AITrader.exe public\download\AITrader.exe >nul
if errorlevel 1 (
  echo [ERROR] public\download\AITrader.exe に置けませんでした。
  pause
  exit /b 1
)

echo.
echo ================================================================
echo   できました: public\download\AITrader.exe
echo   表示名: AIトレーダー
echo.
echo   あとは、このファイルを commit して push すれば、サイトから配られます。
echo     git add public/download/AITrader.exe
echo     git commit -m "exe を作り直す"
echo     git push
echo ================================================================
echo.
pause
