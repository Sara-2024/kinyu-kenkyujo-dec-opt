#!/usr/bin/env bash
# ================================================================
#  サイトの「接続ツールをダウンロード」ボタンで配るファイルを作る
#
#    public/download/AITrader.zip  … 接続ツール一式（Python 版）
#    public/download/AITrader.exe  … Windows で tools/build-windows.bat を
#                                    実行して dist/AITrader.exe ができていれば、それも置く
#
#  Mac / Linux で:  bash tools/pack-connector.sh
#  作ったファイルはコミットする（Vercel が public/ をそのまま配る）。
#  サイトの既定は exe。ZIP を配るときは VITE_CONNECTOR_URL=/download/AITrader.zip にする。
# ================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=public/download
STAGE="$(mktemp -d)/AITrader"
mkdir -p "$OUT" "$STAGE/bridge" "$STAGE/tools"

# お客様のPCで使うものだけ。venv・.env・ログ・中継サーバー・画面は入れない
cp AITrader.vbs connect.py はじめる.bat "$STAGE/"
cp bridge/bridge.py bridge/mt5_terminal.py bridge/OrbitGoldEA_v6.mq5 bridge/TradingGate.mqh \
   bridge/mt5_detect.py bridge/ea_manager.py bridge/connect_state.py bridge/installer_ui.py \
   bridge/requirements.txt bridge/README.md "$STAGE/bridge/"
cp tools/run-hidden.vbs tools/start-connect.bat tools/停止する.bat tools/状態を見る.bat tools/連携を解除する.bat "$STAGE/tools/"

cat > "$STAGE/はじめに.txt" <<'TXT'
トレード研究所 ｜ AIトレーダー 接続ツール

1. このフォルダの「はじめる.bat」を開いてください（最初の1回だけ）。
   画面の案内どおり Enter を押すだけです。初回は準備に数分かかります。
2. MT5 は、いつも通り口座にログインしたままにしておいてください。
3. 準備が終わると、サイトの画面が自動で先に進みます。

次からはサイトのボタンだけでつながります。パソコンを立ち上げ直したときも自動でつながります。
MT5 のパスワードを入力する場面はありません。

止めたいとき      : tools\停止する.bat
連携をやめるとき  : tools\連携を解除する.bat
うまくいかないとき: %LOCALAPPDATA%\AITrader\connect.log をお送りください
TXT

rm -f "$OUT/AITrader.zip"
# macOS の zip は日本語ファイル名に UTF-8 の印を付けないので、Windows で展開すると
# 文字化けする。Python の zipfile なら印が付く。
python3 - "$STAGE" "$OUT/AITrader.zip" <<'PY'
import os, sys, zipfile
stage, out = sys.argv[1], sys.argv[2]
root = os.path.dirname(stage)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for d, _, files in sorted(os.walk(stage)):
        for f in sorted(files):
            full = os.path.join(d, f)
            name = os.path.relpath(full, root)
            if f.endswith((".bat", ".vbs", ".txt", ".md")):
                # Windows 向けの文字ファイルは CRLF に（bat は LF だと goto が迷子になることがある）
                data = open(full, "rb").read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                z.writestr(name, data)
            else:
                z.write(full, name)
PY
rm -rf "$(dirname "$STAGE")"
echo "できました: $OUT/AITrader.zip ($(du -h "$OUT/AITrader.zip" | cut -f1))"

if [ -f dist/AITrader.exe ]; then
  cp dist/AITrader.exe "$OUT/AITrader.exe"
  echo "できました: $OUT/AITrader.exe"
fi
