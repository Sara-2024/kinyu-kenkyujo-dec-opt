-- ════════════════════════════════════════════════════════════
-- 管理サイト（運営用の別サイト）の合言葉
--
--   ・運営は、口座番号ではなく「管理サイトの合言葉」1つで入る（admin_login）
--   ・入ると、運営用の会員（email = operator@dreamland.local、role = admin）のセッションになる。
--     居なければそのとき作る。会員一覧の操作・プランの合言葉・口座申込の取り出しは、この会員で行う
--   ・合言葉そのものは保存しない（crypt のハッシュだけ。app_settings.admin_password_hash）
--   ・初期値は 20261014_set_admin_password.sql で入れる。管理サイトの画面からも変えられる
-- ════════════════════════════════════════════════════════════
alter table public.app_settings add column if not exists admin_password_hash text;

create or replace function public.admin_login(p_password text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_hash text;
  v_member public.members;
begin
  -- 総当たりを遅らせる
  perform pg_sleep(0.3);
  select admin_password_hash into v_hash from public.app_settings where id = 1;
  if v_hash is null or p_password is null or v_hash <> crypt(p_password, v_hash) then
    raise exception 'BAD_CREDENTIALS';
  end if;

  select * into v_member from public.members where email = 'operator@dreamland.local';
  if not found then
    insert into public.members (email, name, password_hash, role)
    values ('operator@dreamland.local', '運営', crypt(encode(extensions.gen_random_bytes(24), 'hex'), gen_salt('bf')), 'admin')
    returning * into v_member;
  elsif v_member.role <> 'admin' or v_member.status <> 'active' then
    update public.members set role = 'admin', status = 'active' where id = v_member.id returning * into v_member;
  end if;

  return jsonb_build_object(
    'token', public._issue_session(v_member.id),
    'member', public._member_json(v_member)
  );
end;
$$;

-- 管理者が管理サイトの合言葉を決める（8文字以上）
create or replace function public.admin_set_admin_password(p_token uuid, p_password text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  if p_password is null or char_length(trim(p_password)) < 8 then
    raise exception 'WEAK_PASSWORD';
  end if;
  update public.app_settings
     set admin_password_hash = crypt(trim(p_password), gen_salt('bf')),
         updated_at = now()
   where id = 1;
  return jsonb_build_object('ok', true);
end;
$$;

grant execute on function public.admin_login(text) to anon, authenticated;
grant execute on function public.admin_set_admin_password(uuid, text) to anon, authenticated;
