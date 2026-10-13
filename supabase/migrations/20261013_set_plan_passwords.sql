-- プランごとの合言葉を決める。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行（先に 20261013_plan_passwords.sql を流しておく）。
-- 管理者画面の「プランの合言葉」からも同じことができる。
--
--   ファーストクラス       … これまでの入場パスワード（AITrader-dream）をそのまま引き継ぐ
--   ロイヤルファーストクラス … 下の 'AITrader-royal' を、配る前に必ず別の文字列に変えること

insert into public.plan_passwords (plan, password_hash)
values
  ('first',   extensions.crypt('AITrader-dream', extensions.gen_salt('bf'))),
  ('crystal', extensions.crypt('AITrader-royal', extensions.gen_salt('bf')))
on conflict (plan) do update
  set password_hash = excluded.password_hash,
      updated_at = now();
