#!/bin/bash
# EA を、この Mac に入っている MT5 の MetaEditor でコンパイルする。
#
#   bash tools/mac/compile-ea.sh mac    # Mac 用:     bridge/mac/<名前>.mq5 → .ex5
#   bash tools/mac/compile-ea.sh win    # Windows 用: bridge/<名前>.mq5     → .ex5
#   bash tools/mac/compile-ea.sh growth # 追加口座用（安定低月利ver）: bridge/growth/YumekkuEA1年版｜安定低月利ver.mq5 → .ex5
#   bash tools/mac/compile-ea.sh sub    # Yumekku【サブスク版】: bridge/subscription/Yumekku【サブスク版】ver1.1.mq5 → .ex5
#                                       #   （利用許可の鍵 SubscriptionSecret.mqh が要る。tools/make-subscription-secret.sh）
#   bash tools/mac/compile-ea.sh all    # 全部（引数なしも同じ）
#
# 名前：win は bridge/mt5_terminal.py の EA_NAMES[0]（YumekkuEA-1年版-ver1.1）。mac は中身が v1.20 のまま YumekkuEA-1年版。
# growth は bridge/mt5_terminal.py の GROWTH_EA_NAME（ロイヤルファーストクラスの 2 つ目の口座に置く EA）。
# .ex5 は OS に依らない（MT5 の中間コード）ので、Windows 用もここで作れる。
# ソース（.mq5）はどちらも .gitignore で配らない。この Mac にしか無いので消さないこと。
#
# 要るもの: /Applications/MetaTrader 5.app（公式の Mac 版 MT5）。
# その中の Wine で MetaEditor64.exe を黙って動かす。MT5 が起動中でも大丈夫。
# Windows も MetaEditor の画面も要らない。配るのは .ex5 だけ。
#
# 終わったら .ex5 を commit → push で、GitHub が配布物（Windows の exe / Mac の .app）を作り直す。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET="${1:-all}"
case "$TARGET" in
  all)    bash "$0" mac && bash "$0" win && bash "$0" growth && bash "$0" sub; exit $? ;;
  win)    SRC_DIR="$ROOT/bridge";        EA="${EA_NAME:-YumekkuEA-1年版-ver1.1}" ;;
  mac)    SRC_DIR="$ROOT/bridge/mac";    EA="${EA_NAME:-YumekkuEA-1年版}" ;;
  growth) SRC_DIR="$ROOT/bridge/growth"; EA="${EA_NAME:-YumekkuEA1年版｜安定低月利ver}" ;;
  sub)    SRC_DIR="$ROOT/bridge/subscription"; EA="${EA_NAME:-Yumekku【サブスク版】ver1.1}" ;;
  *)      echo "使い方: bash tools/mac/compile-ea.sh [mac|win|growth|sub|all]" >&2; exit 2 ;;
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
# サブスク版は利用許可の鍵を "SubscriptionSecret.mqh"（ソースと同じ場所）から読む
if [ "$TARGET" = "sub" ]; then
  if [ ! -f "$SRC_DIR/SubscriptionSecret.mqh" ]; then
    echo "利用許可の鍵がありません。先に bash tools/make-subscription-secret.sh を実行してください" >&2
    exit 1
  fi
  cp "$SRC_DIR/SubscriptionSecret.mqh" "$WORK/SubscriptionSecret.mqh"
fi
rm -f "$WORK/$EA.ex5" "$WORK/$EA.log"

echo "== コンパイル $REL/$EA.mq5（MetaEditor / Wine）"
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
