#!/usr/bin/env bash
# MT5 Automatic の Mac 版（MT5 Automatic.app）を作って、サイトの置き場に ZIP で置く。
#
#   bash tools/mac/build-mac.sh
#
# できるもの:
#   dist/MT5 Automatic.app                 … 配るアプリ（署名なし。右クリック→開く で通る）
#   public/download/MT5Automatic-mac.zip   … サイトの「接続ツールをダウンロード（Mac）」が配るもの
#
# 中身:
#   Contents/Resources/bin/MT5Automatic … PyInstaller で 1 ファイルにした本体（connect_mac.py）
#   Contents/MacOS/applet               … tools/mac/launcher.applescript（URL を本体に渡すだけ）
#   Contents/Info.plist                 … aitrader:// を受ける登録を書き足したもの
#
# GitHub Actions（.github/workflows/build-mac.yml）がこれを macOS で回す。
# 手元の Mac でも同じように動く（python3 と pip があればよい）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

APP_NAME="MT5 Automatic"
BIN_NAME="MT5Automatic"
BUNDLE_ID="jp.trelab.mt5automatic"
DIST="$ROOT/dist"
APP="$DIST/$APP_NAME.app"
ZIP="$ROOT/public/download/MT5Automatic-mac.zip"
PY="${PYTHON:-python3}"

echo "== 1/5 同梱する EA を確かめる"
EX5="$(ls "$ROOT"/bridge/*Yumekku*.ex5 2>/dev/null | head -1 || true)"
if [ -z "$EX5" ]; then
  echo "bridge/ に Yumekku の .ex5 がありません。2_EAを入れ替える.bat（Windows）で入れてください" >&2
  exit 1
fi
if [ ! -f "$ROOT/bridge/ea_manifest.json" ]; then
  "$PY" "$ROOT/tools/make-ea-manifest.py"
fi
echo "   EA: $(basename "$EX5")"

echo "== 2/5 Python の部品"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$ROOT/bridge/requirements-mac.txt"

echo "== 3/5 本体を 1 ファイルにする（PyInstaller）"
rm -rf "$DIST/$BIN_NAME" "$ROOT/build/$BIN_NAME" "$ROOT/$BIN_NAME.spec"
ADD_DATA=(
  --add-data "$ROOT/connect.py:."
)
# bridge/ の Python と同梱物（EA・控え・TradingGate.mqh・合言葉）をそのまま bridge/ に置く。
# connect.py / connect_mac.py は実行時に sys.path へ入れて読む（Windows 版と同じ）
for f in "$ROOT"/bridge/*.py "$ROOT"/bridge/*.ex5 "$ROOT"/bridge/ea_manifest.json "$ROOT"/bridge/TradingGate.mqh; do
  [ -f "$f" ] || continue
  case "$(basename "$f")" in *_test.py) continue ;; esac
  ADD_DATA+=(--add-data "$f:bridge")
done
"$PY" -m PyInstaller --noconfirm --clean --onefile \
  --name "$BIN_NAME" \
  --distpath "$DIST" \
  --workpath "$ROOT/build" \
  --specpath "$ROOT/build" \
  --paths "$ROOT/bridge" \
  --hidden-import websockets \
  --hidden-import websockets.asyncio.client \
  --hidden-import websockets.exceptions \
  --hidden-import tkinter \
  --hidden-import tkinter.font \
  --hidden-import dotenv \
  --hidden-import certifi \
  --collect-data certifi \
  --exclude-module pyi_splash \
  "${ADD_DATA[@]}" \
  "$ROOT/connect_mac.py"
[ -x "$DIST/$BIN_NAME" ] || { echo "本体ができていません" >&2; exit 1; }

echo "== 4/5 .app に包む（AppleScript の起動ラッパー + Info.plist）"
rm -rf "$APP"
osacompile -o "$APP" "$ROOT/tools/mac/launcher.applescript"
mkdir -p "$APP/Contents/Resources/bin"
cp "$DIST/$BIN_NAME" "$APP/Contents/Resources/bin/$BIN_NAME"
chmod +x "$APP/Contents/Resources/bin/$BIN_NAME"
"$PY" - "$APP/Contents/Info.plist" "$BUNDLE_ID" "$APP_NAME" <<'PYEOF'
import plistlib, sys
path, bundle_id, app_name = sys.argv[1:4]
with open(path, "rb") as fh:
    info = plistlib.load(fh)
info["CFBundleIdentifier"] = bundle_id
info["CFBundleName"] = app_name
info["CFBundleDisplayName"] = app_name
info["CFBundleShortVersionString"] = "1.0"
# サイトのボタン（aitrader://）で起こせるように
info["CFBundleURLTypes"] = [{
    "CFBundleURLName": "MT5 Automatic connect",
    "CFBundleURLSchemes": ["aitrader"],
    "LSHandlerRank": "Owner",
}]
# Dock に居座らない（起こすだけのラッパーなので）
info["LSUIElement"] = True
with open(path, "wb") as fh:
    plistlib.dump(info, fh)
print("   Info.plist に aitrader:// を書きました")
PYEOF
# 署名は無い（Gatekeeper には右クリック→開く で通す）。隔離属性だけ外しておく
xattr -cr "$APP" 2>/dev/null || true

echo "== 5/5 ZIP にしてサイトの置き場へ"
mkdir -p "$(dirname "$ZIP")"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
SIZE=$(stat -f%z "$ZIP" 2>/dev/null || stat -c%s "$ZIP")
echo "   $ZIP ($SIZE bytes)"
if [ "$SIZE" -lt 5000000 ]; then
  echo "ZIP が小さすぎます（本体が入っていない？）" >&2
  exit 1
fi
echo "できました: $APP"
