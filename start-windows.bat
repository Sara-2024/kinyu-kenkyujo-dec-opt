@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist bridge\venv (
  echo.
  echo 先に setup-windows.bat をダブルクリックして実行してください。
  echo.
  pause
  exit /b 1
)

echo.
echo ========================================================
echo   自動連携デモを起動します
echo ========================================================
echo.
echo  MT5 が起動してログイン済みか、今確認してください。
echo  3つの黒い画面が開きます。閉じないでください。
echo.
timeout /t 4 /nobreak >nul

start "①中継サーバー" cmd /k "cd /d %~dp0server && npm start"
timeout /t 2 /nobreak >nul

start "②ブリッジ" cmd /k "cd /d %~dp0bridge && call venv\Scripts\activate.bat && python bridge.py"
timeout /t 3 /nobreak >nul

start "③画面" cmd /k "cd /d %~dp0 && npm run dev"
timeout /t 4 /nobreak >nul

echo  ブラウザを開きます...
start http://localhost:5181

echo.
echo ========================================================
echo   ブラウザで http://localhost:5181 が開きます
echo.
echo   操作の流れ:
echo     1. ユイ をクリック
echo     2. アルゴ をクリック
echo     3. 「自動売買をはじめる」
echo     4. メールを入れて 4秒待つ
echo     5. 管理画面で「停止」を押す
echo        （MT5 で F3 を押すと変数が変わるのが見える）
echo ========================================================
echo.
pause
