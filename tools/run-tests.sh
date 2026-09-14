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
  "AIに渡す数値とプロンプトの説明が揃っているか|python3 bridge/tests/prompt_features_test.py"
  "停止と再開・通信断・古い応答|python3 bridge/tests/risk_gate_test.py"
  "ブリッジの配線|python3 bridge/tests/wiring_test.py"
  "金の銘柄選び|python3 bridge/tests/symbol_test.py"
  "指令ファイルが消えたときの書き戻し|python3 bridge/tests/settings_restore_test.py"
  "接続ツールが受け取る部屋の検査|python3 bridge/tests/connector_room_test.py"
  "口座履歴の取りこぼし（ドテン・長期保有・時計のズレ）|python3 bridge/tests/history_test.py"
  "配る EA にサイト連携が入っているか|python3 bridge/tests/ea_gate_test.py"
  "MT5の検出・EAの状態判定・連携状態|python3 bridge/tests/phase1_test.py"
  "初回の設定が通信しないこと（通し試験）|python3 bridge/tests/phase1_offline_test.py"
  "初回の設定画面（専門用語・文字の大きさ）|python3 bridge/tests/installer_ui_test.py"
  "サイトからの連携（合図の検証・状態の移り変わり）|python3 bridge/tests/phase2_test.py"
  "新規連携の受付を止めているあいだの安全確認|python3 bridge/tests/connect_paused_test.py"
  "合図を確かめる所（/api/connect）|node --experimental-strip-types api/_lib/connect.test.mjs"
  "中継の部屋分け・会員の確認（通し試験）|node server/tests/relay_test.mjs"
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
