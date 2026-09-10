#!/usr/bin/env bash
# ぜんぶの試験を1回で走らせる。MT5 も AI の鍵も要らない（偽の相手を立てて確かめる）。
#
#   npm test          … これを呼ぶ
#   npm test -- -q    … 通ったものは出さず、失敗だけ出す
#
# 新しい試験を足したら、この一覧にも足すこと。ここに無い試験は誰も走らせない。
set -u
cd "$(dirname "$0")/.."

QUIET=0
[ "${1:-}" = "-q" ] && QUIET=1

# 「表示名」「走らせるコマンド」の順に並べる
TESTS=(
  "根拠の検証と方向別の理由コード（/api/risk）|node --experimental-strip-types api/_lib/risk.test.mjs"
  "研究員の受け答えと会員確認（/api/chat）|node --experimental-strip-types api/_lib/chat.test.mjs"
  "水準・突破・リテストの計算|python3 bridge/tests/risk_features_test.py"
  "停止と再開・通信断・古い応答|python3 bridge/tests/risk_gate_test.py"
  "ブリッジの配線|python3 bridge/tests/wiring_test.py"
  "金の銘柄選び|python3 bridge/tests/symbol_test.py"
  "指令ファイルが消えたときの書き戻し|python3 bridge/tests/settings_restore_test.py"
  "中継の部屋分け（通し試験）|node server/tests/relay_test.mjs"
  "判定の突き合わせ道具（通し試験）|node --experimental-strip-types tools/tests/compare_risk_models_test.mjs"
)

failed=0
for row in "${TESTS[@]}"; do
  name="${row%%|*}"
  cmd="${row#*|}"
  out="$(eval "$cmd" 2>&1)"
  code=$?
  tail_line="$(printf '%s\n' "$out" | grep -E '[0-9]+ ok / [0-9]+ NG' | tail -1)"
  if [ $code -eq 0 ]; then
    [ $QUIET -eq 1 ] || printf '  ok   %-40s %s\n' "$name" "$tail_line"
  else
    failed=$((failed + 1))
    printf '  NG   %-40s %s\n' "$name" "$tail_line"
    printf '%s\n' "$out" | tail -20 | sed 's/^/       /'
  fi
done

echo
if [ $failed -eq 0 ]; then
  echo "ぜんぶ通りました（${#TESTS[@]} 件）"
else
  echo "${failed} 件が落ちています"
fi
exit $failed
