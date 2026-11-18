#!/bin/bash
# Yumekku【サブスク版】の利用許可の鍵を作る（1 回だけ。作り直すと、配った EA がすべて許可を受け付けなくなる）。
#
#   bash tools/make-subscription-secret.sh          # 無ければ作る（あれば何もしない）
#   bash tools/make-subscription-secret.sh --force  # 作り直す（EA を作り直して配り直すときだけ）
#
# 同じ鍵を 2 か所に書く。どちらもリポジトリには入れない（.gitignore）：
#   bridge/subscription/SubscriptionSecret.mqh       … EA に焼き込む（compile-ea.sh sub がこれを読む）
#   supabase/secrets/set_subscription_secret.sql     … Supabase の SQL Editor で 1 回流す（DB が許可に署名する）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MQH="$ROOT/bridge/subscription/SubscriptionSecret.mqh"
SQL="$ROOT/supabase/secrets/set_subscription_secret.sql"
if [ -f "$MQH" ] && [ "${1:-}" != "--force" ]; then
  echo "鍵はもうあります: ${MQH#$ROOT/}（作り直すときは --force）"
  exit 0
fi
SECRET="$(openssl rand -hex 32)"
mkdir -p "$(dirname "$MQH")" "$(dirname "$SQL")"
cat > "$MQH" <<MQH
// Yumekku【サブスク版】の利用許可の鍵。tools/make-subscription-secret.sh が作る。リポジトリに入れない。
// supabase/secrets/set_subscription_secret.sql（DB 側）と同じ値でないと、承認していても EA は動かない。
#define YMK_SUB_SECRET "$SECRET"
MQH
cat > "$SQL" <<SQLEOF
-- Yumekku【サブスク版】の利用許可の鍵（tools/make-subscription-secret.sh が作る。リポジトリに入れない）。
-- supabase/migrations/20261118_subscription.sql を流したあと、Supabase の SQL Editor でこれを 1 回流す。
insert into public.subscription_secret (id, secret)
values (1, '$SECRET')
on conflict (id) do update set secret = excluded.secret;
SQLEOF
chmod 600 "$MQH" "$SQL"
echo "鍵を作りました:"
echo "  ${MQH#$ROOT/}"
echo "  ${SQL#$ROOT/}（Supabase の SQL Editor で流してください）"
