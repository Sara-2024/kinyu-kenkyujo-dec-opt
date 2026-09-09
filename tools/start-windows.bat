@echo off
REM ================================================================
REM  開発・商談用のローカル一式（中継 + 画面）を、黒い画面を出さずに起動する。
REM  お客様が使うのは AITrader.vbs（または AITrader.exe）だけ。
REM ================================================================
cd /d "%~dp0.."

if not exist bridge\venv (
  echo プロジェクト直下の「はじめる.bat」を先に一度実行してください。
  pause
  exit /b 1
)

REM 中継サーバー（ポート 8080）
wscript "%~dp0run-hidden.vbs" "cmd /c npm start" "%~dp0..\server"

REM 画面（Vite 開発サーバー）
wscript "%~dp0run-hidden.vbs" "cmd /c npm run dev" "%~dp0.."

REM 接続ツール（MT5 の確認・システム配置・ブリッジ起動）
wscript "%~dp0..\AITrader.vbs"

REM 画面が立ち上がるのを少し待ってからブラウザを開く
timeout /t 6 /nobreak >nul
start http://localhost:5181

exit /b 0
