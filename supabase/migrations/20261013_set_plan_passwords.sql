-- プランごとの合言葉を決める。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行（先に 20261013_plan_passwords.sql を流しておく）。
-- 管理者画面の「プランの合言葉」からも同じことができる。
--
--   ここに書くのは「まだ決まっていないとき」の仮の値。本番の合言葉は管理サイトの
--   「プランの合言葉」で入れる（2026-10-14 に設定済み。合言葉はリポジトリに書かない）。
--   すでに入っている行は上書きしない（do nothing）。もう一度流しても本番の合言葉は変わらない

insert into public.plan_passwords (plan, password_hash)
values
  ('first',   extensions.crypt('AITrader-dream', extensions.gen_salt('bf'))),
  ('crystal', extensions.crypt('AITrader-royal', extensions.gen_salt('bf')))
on conflict (plan) do nothing;
