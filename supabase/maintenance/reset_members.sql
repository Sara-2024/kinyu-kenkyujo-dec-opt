-- 会員（アカウント）をまっさらにする。テスト用の会員を全部消すとき用。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行。
--
-- 消えるもの（会員に紐づくものは一緒に消える）:
--   members（運営用の admin 以外）、sessions（ログイン）、member_connections（MT5連携の記録）、
--   connect_tokens（合図）、fleet_accounts（一斉制御の登録簿）、fleet_optout（一斉停止を受け付けない設定）
-- 残るもの:
--   運営用の会員（operator@dreamland.local、管理サイトの合言葉で入るもの）、プランの合言葉、
--   管理サイトの合言葉、ドリームランドの口座申込（dreamland_applications。消すなら下の 2 つ目を実行）
--
-- 実行後: これまでのパソコンのパスポートは、消した会員の部屋で名乗るので中継に断られる。
-- ロビーからパスポートを取り直して開けば、新しい会員に紐づき直る。

delete from public.members
 where coalesce(email, '') <> 'operator@dreamland.local';

-- 申込（サービスカウンターの口座の登録）も消すときだけ、この行の先頭の「-- 」を外して実行
-- delete from public.dreamland_applications;

select count(*) as 残っている会員 from public.members;
