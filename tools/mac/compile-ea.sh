#!/bin/bash
# EA を、この Mac に入っている MT5 の MetaEditor でコンパイルする。
#
#   bash tools/mac/compile-ea.sh                  # Mac 用:     bridge/mac/YumekkuEA_mac.mq5 → .ex5
#   bash tools/mac/compile-ea.sh YumekkuEA_win    # Windows 用: bridge/YumekkuEA_win.mq5     → .ex5
#   bash tools/mac/compile-ea.sh --all            # 両方
#
# .ex5 は OS に依らない（MT5 の中間コード）ので、Windows 用もここで作れる。
# ソース（.mq5）はどちらも .gitignore で配らない。この Mac にしか無いので消さないこと。
#
# 要るもの: /Applications/MetaTrader 5.app（公式の Mac 版 MT5）。
# その中の Wine で MetaEditor64.exe を黙って動かす。MT5 が起動中でも大丈夫。
# Windows も MetaEditor の画面も要らない。配るのは .ex5 だけ（.mq5 は配らないし、
# リポジトリにも入れない）。
#
# 終わったら build-mac.sh（または push → GitHub の自動ビルド）で .app に入る。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ "${1:-}" = "--all" ]; then
  bash "$0" YumekkuEA_mac && bash "$0" YumekkuEA_win
  exit $?
fi
EA="${1:-YumekkuEA_mac}"
# Windows 用（*_win）は bridge/ 直下、Mac 用は bridge/mac/
case "$EA" in
  *_win) SRC_DIR="$ROOT/bridge" ;;
  *)     SRC_DIR="$ROOT/bridge/mac" ;;
esac
REL="${SRC_DIR#$ROOT/}"
APP="${MT5_APP:-/Applications/MetaTrader 5.app}"
WINE="$APP/Contents/SharedSupport/wine/bin/wine64"
PREFIX="${WINEPREFIX:-$HOME/Library/Application Support/net.metaquotes.wine.metatrader5}"
EDITOR_WIN='C:\Program Files\MetaTrader 5\MetaEditor64.exe'
WORK="$PREFIX/drive_c/trelab_build"

if [ ! -x "$WINE" ]; then
  echo "MT5 の Mac 版が見つかりません: $APP（MT5_APP= で場所を指定できます）" >&2
  exit 1
fi
if [ ! -f "$SRC_DIR/$EA.mq5" ]; then
  echo "ソースがありません: $REL/$EA.mq5" >&2
  exit 1
fi

# EA は <TradingGate.mqh> を山かっこで読むので、Wine の中の MT5 の Include に置く
mkdir -p "$WORK" "$PREFIX/drive_c/Program Files/MetaTrader 5/MQL5/Include"
cp "$ROOT/bridge/TradingGate.mqh" "$PREFIX/drive_c/Program Files/MetaTrader 5/MQL5/Include/TradingGate.mqh"
cp "$SRC_DIR/$EA.mq5" "$WORK/$EA.mq5"
rm -f "$WORK/$EA.ex5" "$WORK/$EA.log"

echo "== コンパイル $EA.mq5（MetaEditor / Wine）"
export WINEPREFIX="$PREFIX" WINEDEBUG=-all
# MetaEditor は成功しても 1 を返すことがあるので、終了コードは見ない。.ex5 とログで判断する
"$WINE" "$EDITOR_WIN" "/compile:C:\\trelab_build\\$EA.mq5" "/log:C:\\trelab_build\\$EA.log" >/dev/null 2>&1 || true

if [ -f "$WORK/$EA.log" ]; then
  iconv -f UTF-16LE -t UTF-8 "$WORK/$EA.log" 2>/dev/null | grep -v ': information:' | sed 's/^/   /' || true
fi
if [ ! -f "$WORK/$EA.ex5" ]; then
  echo "コンパイルできませんでした（上のログを見てください）" >&2
  exit 1
fi
cp "$WORK/$EA.ex5" "$SRC_DIR/$EA.ex5"
"${PYTHON:-python3}" "$ROOT/tools/make-ea-manifest.py" --dir "$SRC_DIR" --quiet
echo "できました: $REL/$EA.ex5（$(stat -f%z "$SRC_DIR/$EA.ex5") bytes）"
echo "次: git add $REL/$EA.ex5 → commit → push で、GitHub が配布物（Windows の exe / Mac の .app）を作り直します"
