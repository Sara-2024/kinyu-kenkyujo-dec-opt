-- 管理サイトの合言葉を決める。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行（先に 20261014_admin_site.sql か schema.sql を流しておく）。
-- 管理サイトの「管理サイトの合言葉」からも同じことができる（本番はそちらで入れる。2026-10-14 に設定済み）。
--
-- 本番の合言葉はリポジトリに書かない。下の '書き換えてください' を実際の合言葉に置き換えてから流す。
-- そのまま流すと、入れない合言葉になるので注意。
update public.app_settings
   set admin_password_hash = extensions.crypt('書き換えてください', extensions.gen_salt('bf')),
       updated_at = now()
 where id = 1;
