-- ════════════════════════════════════════════════════════════
-- 会員登録を「MT5 の口座番号 ＋ お名前 ＋ パスワード」にする（メールをやめる）
--
--   ・会員 ＝ MT5 の口座番号。口座が2つある人は会員を2つ作る（それぞれに自分のサイトがある）
--   ・ログインも口座番号とパスワード
--   ・メールの列は残す（空でよい）。メールで登録した会員はまだ居ないので、移す処理は無い
--   ・ロビー（dreamland/）の申込と会員は、口座番号で結びつく（dreamland_list が会員名を返す）
-- ════════════════════════════════════════════════════════════
alter table public.members add column if not exists account bigint;
alter table public.members add column if not exists name text not null default '';
alter table public.members alter column email drop not null;
create unique index if not exists members_account_idx on public.members (account);

create or replace function public._member_json(p_member public.members)
returns jsonb
language sql
immutable
as $$
  select jsonb_build_object(
    'id', p_member.id,
    'email', p_member.email,
    'name', p_member.name,
    'account', p_member.account,
    'role', p_member.role,
    'status', p_member.status,
    'can_trade', p_member.can_trade,
    'last_login_at', p_member.last_login_at,
    'created_at', p_member.created_at
  );
$$;

-- 旧: メールで登録・ログイン。残しておくとメールでも登録できてしまうので消す
drop function if exists public.auth_register(text, text, text);
drop function if exists public.auth_login(text, text);

create or replace function public.auth_register(p_account bigint, p_name text, p_password text, p_entry text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_name text := left(trim(coalesce(p_name, '')), 80);
  v_role text := 'user';
  v_member public.members;
begin
  if p_account is null or p_account <= 0 then
    raise exception 'BAD_ACCOUNT';
  end if;
  if v_name = '' then
    raise exception 'BAD_NAME';
  end if;
  if p_password is null or char_length(p_password) < 8 then
    raise exception 'WEAK_PASSWORD';
  end if;
  if p_entry is null or not exists (
    select 1 from public.app_settings
     where id = 1
       and entry_password_hash = crypt(p_entry, entry_password_hash)
  ) then
    raise exception 'BAD_ENTRY';
  end if;
  if exists (select 1 from public.members where account = p_account) then
    raise exception 'ACCOUNT_TAKEN';
  end if;
  if not exists (select 1 from public.members) then
    v_role := 'admin';
  end if;

  insert into public.members (account, name, password_hash, role)
  values (p_account, v_name, crypt(p_password, gen_salt('bf')), v_role)
  returning * into v_member;

  return jsonb_build_object(
    'token', public._issue_session(v_member.id),
    'member', public._member_json(v_member)
  );
end;
$$;

create or replace function public.auth_login(p_account bigint, p_password text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  select * into v_member from public.members where account = p_account;
  if not found or v_member.password_hash <> crypt(p_password, v_member.password_hash) then
    raise exception 'BAD_CREDENTIALS';
  end if;
  if v_member.status <> 'active' then
    raise exception 'SUSPENDED';
  end if;
  return jsonb_build_object(
    'token', public._issue_session(v_member.id),
    'member', public._member_json(v_member)
  );
end;
$$;

grant execute on function public.auth_register(bigint, text, text, text) to anon, authenticated;
grant execute on function public.auth_login(bigint, text) to anon, authenticated;

-- 管理者の一覧: お名前と登録した口座番号。連携でつながっている口座は connected_account
create or replace function public.admin_list_members(p_token uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  return coalesce((
    select jsonb_agg(row_to_json(r)::jsonb order by r.created_at desc)
    from (
      select
        m.id,
        m.email,
        m.name,
        m.account,
        m.role,
        m.status,
        m.can_trade,
        m.last_login_at,
        m.created_at,
        c.account as connected_account,
        c.server,
        c.running,
        c.platform,
        c.updated_at as connected_at
      from public.members m
      left join public.member_connections c on c.member_id = m.id
    ) r
  ), '[]'::jsonb);
end;
$$;

-- 一斉制御の一覧: メールの代わりにお名前を出す
create or replace function public.fleet_list(p_token uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  return coalesce((
    select jsonb_agg((public._fleet_row_json(r, coalesce(nullif(m.name, ''), m.email)) || jsonb_build_object('platform', c.platform)) order by r.created_at)
    from public.fleet_accounts r
    join public.members m on m.id = r.member_id
    left join public.member_connections c on c.member_id = r.member_id
  ), '[]'::jsonb);
end;
$$;

-- 見込み客の記録: メールが無ければお名前と口座番号で残す（leads.email は空にできない）
create or replace function public.member_save_lead(p_token uuid, p_email text, p_source text default 'algo-connect')
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  v_member := public._session_member(p_token);
  insert into public.leads (email, source, member_id)
  values (
    coalesce(nullif(trim(p_email), ''), v_member.email, v_member.name || ' / ' || coalesce(v_member.account::text, '')),
    coalesce(p_source, 'algo-connect'),
    v_member.id
  );
  return jsonb_build_object('ok', true);
end;
$$;

-- ロビーの申込に、口座番号が同じ会員を添える
create or replace function public.dreamland_list(p_token uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  return coalesce((
    select jsonb_agg(
      (public._dreamland_row_json(r) || jsonb_build_object('member_id', m.id, 'member_name', m.name))
      order by r.updated_at desc
    )
    from public.dreamland_applications r
    left join public.members m on m.account = r.account
  ), '[]'::jsonb);
end;
$$;
