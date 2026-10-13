-- 入場パスワードを AITrader-dream にする。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行。
-- schema.sql を流し直しても、既存の行は上書きされない（on conflict do nothing）。

update public.app_settings
   set entry_password_hash = extensions.crypt('AITrader-dream', extensions.gen_salt('bf')),
       updated_at = now()
 where id = 1;
