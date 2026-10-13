-- 管理サイトの合言葉を決める。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行（先に 20261014_admin_site.sql か schema.sql を流しておく）。
-- 管理サイトの「管理サイトの合言葉」からも同じことができる。
update public.app_settings
   set admin_password_hash = extensions.crypt('issei-yumeck0623', extensions.gen_salt('bf')),
       updated_at = now()
 where id = 1;
