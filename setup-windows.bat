@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ========================================================
echo   金融研究所 - 初回セットアップ（1回だけ）
echo ========================================================
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [エラー] Node.js が見つかりません。
  echo https://nodejs.org から LTS版 をインストールして、もう一度実行してください。
  pause
  exit /b 1
)

where py >nul 2>&1
if errorlevel 1 (
  echo [エラー] Python が見つかりません。
  echo https://www.python.org から 64bit版 をインストールしてください。
  echo インストール時に「Add python.exe to PATH」にチェックを入れてください。
  pause
  exit /b 1
)

echo [1/3] ブリッジの準備...
cd bridge
if not exist venv (
  py -3 -m venv venv
)
call venv\Scripts\activate.bat
pip install -r requirements.txt
cd ..

echo.
echo [2/3] 中継サーバーの準備...
cd server
call npm install
cd ..

echo.
echo [3/3] 画面の準備...
call npm install

echo.
echo ========================================================
echo   セットアップ完了！
echo.
echo   次にやること:
echo     1. MT5 を起動してログイン
echo     2. check-mt5.bat をダブルクリック（つながるか確認）
echo     3. start-windows.bat をダブルクリック（本番起動）
echo ========================================================
echo.
pause
