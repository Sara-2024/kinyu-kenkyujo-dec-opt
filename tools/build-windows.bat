@echo off
REM ================================================================
REM  お客様に配る接続ツール（AITrader.exe / 表示名 AIトレーダー）を作る
REM
REM  Windows で一度だけ実行する。できあがった exe は
REM  Python も Node も入っていないPCで動き、黒い画面も出ない。
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

echo.
echo [2/3] exe を作っています（数分かかります）...
py -3 -m PyInstaller --noconfirm --clean ^
  --onefile --noconsole ^
  --name AITrader ^
  --add-data "bridge;bridge" ^
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

echo.
echo ================================================================
echo   できました: dist\AITrader.exe
echo   表示名: AIトレーダー
echo.
echo   お客様は、この1本をダウンロードして一度開くだけです。
echo   （黒い画面は出ません。以後はサイトのボタンから起動できます）
echo ================================================================
echo.
pause
