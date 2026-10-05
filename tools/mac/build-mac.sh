#!/usr/bin/env bash
# MT5 Automatic の Mac 版（MT5 Automatic.app）を作って、サイトの置き場に ZIP で置く。
#
#   bash tools/mac/build-mac.sh              … 本体を作って .app に包む（この Mac で作れる機種ぶん）
#   bash tools/mac/build-mac.sh --binary     … 本体（dist/MT5Automatic-<機種>）だけ作る
#   bash tools/mac/build-mac.sh --assemble   … dist/MT5Automatic-* を集めて .app に包み、ZIP にする
#
# できるもの:
#   dist/MT5Automatic-arm64 / dist/MT5Automatic-x86_64 … PyInstaller で 1 ファイルにした本体
#   dist/MT5 Automatic.app                 … 配るアプリ（署名なし。右クリック→開く で通る）
#   public/download/MT5Automatic-mac.zip   … サイトの「接続ツールをダウンロード（Mac）」が配るもの
#
# .app の中身:
#   Contents/Resources/bin/MT5Automatic-arm64   … Apple シリコン用
#   Contents/Resources/bin/MT5Automatic-x86_64  … Intel 用
#   Contents/MacOS/applet                       … tools/mac/launcher.applescript（機種を見て本体を起こす）
#   Contents/Info.plist                         … aitrader:// を受ける登録を書き足したもの
#
# GitHub Actions（.github/workflows/build-mac.yml）は、Apple シリコンと Intel のランナーで
# --binary を 1 つずつ作り、--assemble で 1 つの .app にまとめる。
# 手元の Mac（Apple シリコン）では、Rosetta と universal2 の Python があれば
# 引数なしで両方の本体を作る。
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
MODE="${1:-all}"

check_ea() {
  echo "== 同梱する EA を確かめる"
  EX5="$(ls "$ROOT"/bridge/*Yumekku*.ex5 2>/dev/null | head -1 || true)"
  if [ -z "$EX5" ]; then
    echo "bridge/ に Yumekku の .ex5 がありません。2_EAを入れ替える.bat（Windows）で入れてください" >&2
    exit 1
  fi
  if [ ! -f "$ROOT/bridge/ea_manifest.json" ]; then
    "$PY" "$ROOT/tools/make-ea-manifest.py"
  fi
  echo "   EA: $(basename "$EX5")"
}

build_binary() {
  # この python が動いている機種（arm64 / x86_64）ぶんの本体を作る
  local arch
  arch="$("$PY" -c 'import platform; print(platform.machine())')"
  local out="$BIN_NAME-$arch"
  # macOS 付属の bash 3.2 は全角かっこの直前の変数を読み違えるので ${arch} と書く
  echo "== 本体を作る（${arch}）"
  # 部品は機種ごとに別の仮想環境に入れる。共有の site-packages だと、Rosetta で Intel 用を
  # 作るときに Apple シリコン用の websockets の部品を拾ってしまい、PyInstaller が止まる
  local venv="$ROOT/build/venv-$arch"
  if [ ! -x "$venv/bin/python" ]; then
    "$PY" -m venv "$venv"
  fi
  local vpy="$venv/bin/python"
  "$vpy" -m pip install --quiet --upgrade pip
  "$vpy" -m pip install --quiet --force-reinstall --no-cache-dir -r "$ROOT/bridge/requirements-mac.txt"
  rm -rf "$DIST/$out" "$ROOT/build/$out" "$ROOT/build/$out.spec"
  local add_data=(--add-data "$ROOT/connect.py:.")
  # bridge/ の Python と同梱物（EA・控え・TradingGate.mqh・合言葉）をそのまま bridge/ に置く。
  # connect.py / connect_mac.py は実行時に sys.path へ入れて読む（Windows 版と同じ）
  for f in "$ROOT"/bridge/*.py "$ROOT"/bridge/*.ex5 "$ROOT"/bridge/ea_manifest.json "$ROOT"/bridge/TradingGate.mqh; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in *_test.py) continue ;; esac
    add_data+=(--add-data "$f:bridge")
  done
  "$vpy" -m PyInstaller --noconfirm --clean --onefile \
    --name "$out" \
    --distpath "$DIST" \
    --workpath "$ROOT/build/$out" \
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
    "${add_data[@]}" \
    "$ROOT/connect_mac.py" >"$ROOT/build/pyinstaller-$arch.log" 2>&1 || {
      tail -30 "$ROOT/build/pyinstaller-$arch.log" >&2
      echo "本体（${arch}）が作れませんでした" >&2
      exit 1
    }
  [ -x "$DIST/$out" ] || { echo "本体（${arch}）ができていません" >&2; exit 1; }
  echo "   $DIST/$out"
}

assemble() {
  echo "== .app に包む（AppleScript の起動ラッパー + Info.plist）"
  local bins=()
  for b in "$DIST"/$BIN_NAME-arm64 "$DIST"/$BIN_NAME-x86_64; do
    [ -x "$b" ] && bins+=("$b")
  done
  if [ ${#bins[@]} -eq 0 ]; then
    echo "dist/ に本体（MT5Automatic-arm64 / -x86_64）がありません。先に --binary を" >&2
    exit 1
  fi
  if [ ${#bins[@]} -eq 1 ]; then
    echo "   注意: 本体が 1 機種ぶんしかありません（$(basename "${bins[0]}")）。もう片方の Mac では動きません"
  fi
  rm -rf "$APP"
  osacompile -o "$APP" "$ROOT/tools/mac/launcher.applescript"
  mkdir -p "$APP/Contents/Resources/bin"
  for b in "${bins[@]}"; do
    cp "$b" "$APP/Contents/Resources/bin/$(basename "$b")"
    chmod +x "$APP/Contents/Resources/bin/$(basename "$b")"
    echo "   同梱: $(basename "$b")"
  done
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

  echo "== ZIP にしてサイトの置き場へ"
  mkdir -p "$(dirname "$ZIP")"
  rm -f "$ZIP"
  ditto -c -k --keepParent "$APP" "$ZIP"
  local size
  size=$(stat -f%z "$ZIP" 2>/dev/null || stat -c%s "$ZIP")
  echo "   $ZIP ($size bytes)"
  if [ "$size" -lt 5000000 ]; then
    echo "ZIP が小さすぎます（本体が入っていない？）" >&2
    exit 1
  fi
  echo "できました: $APP"
}

case "$MODE" in
  --binary)
    check_ea
    build_binary
    ;;
  --assemble)
    assemble
    ;;
  all)
    check_ea
    build_binary
    # Apple シリコンの Mac で、Rosetta と universal2 の Python があれば Intel 用も作る
    if [ "$(uname -m)" = "arm64" ] && arch -x86_64 /usr/bin/true 2>/dev/null \
       && [ "$(arch -x86_64 "$PY" -c 'import platform; print(platform.machine())' 2>/dev/null)" = "x86_64" ]; then
      echo "== Intel 用も作る（Rosetta）"
      PYTHON="$PY" arch -x86_64 bash "$0" --binary
    else
      echo "   注意: この Mac では Intel 用を作れません（GitHub の自動ビルドでは両方できます）"
    fi
    assemble
    ;;
  *)
    echo "使い方: bash tools/mac/build-mac.sh [--binary | --assemble]" >&2
    exit 2
    ;;
esac
