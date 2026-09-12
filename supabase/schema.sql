-- Supabase ダッシュボード → SQL Editor でこのファイルを実行
-- 何回実行しても大丈夫（既存の leads は残す）
--
-- 初回の入場パスワード: TRELAB-ENTRY
-- 最初に登録した人は管理者になります。入場パスワードは管理者画面から変えてください。

create extension if not exists pgcrypto with schema extensions;

-- ────────────────────────────────
-- 設定（入場パスワード）
-- ────────────────────────────────
create table if not exists public.app_settings (
  id int primary key default 1 check (id = 1),
  entry_password_hash text not null,
  updated_at timestamptz not null default now()
);

insert into public.app_settings (id, entry_password_hash)
values (1, extensions.crypt('TRELAB-ENTRY', extensions.gen_salt('bf')))
on conflict (id) do nothing;

-- サイト全体の設定（研究員の名前など）。中身は {"names": {"rin": "…"}} の形
alter table public.app_settings
  add column if not exists site_settings jsonb not null default '{}'::jsonb;

-- ────────────────────────────────
-- 会員
-- ────────────────────────────────
create table if not exists public.members (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  password_hash text not null,
  role text not null default 'user' check (role in ('user', 'admin')),
  status text not null default 'active' check (status in ('active', 'suspended')),
  can_trade boolean not null default true,
  last_login_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists members_created_at_idx on public.members (created_at desc);

-- ────────────────────────────────
-- セッション
-- ────────────────────────────────
create table if not exists public.sessions (
  token uuid primary key default gen_random_uuid(),
  member_id uuid not null references public.members (id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists sessions_member_idx on public.sessions (member_id);
create index if not exists sessions_expires_idx on public.sessions (expires_at);

-- ────────────────────────────────
-- 会員ごとの接続状態（他の人の口座と混ざらない）
-- ────────────────────────────────
create table if not exists public.member_connections (
  member_id uuid primary key references public.members (id) on delete cascade,
  email text,
  account text,
  server text,
  connected_at timestamptz,
  running boolean,
  settings jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- ────────────────────────────────
-- リード（既存）。会員IDを足す
-- ────────────────────────────────
create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  source text not null default 'algo-connect',
  created_at timestamptz not null default now()
);

alter table public.leads add column if not exists member_id uuid references public.members (id) on delete set null;

create index if not exists leads_created_at_idx on public.leads (created_at desc);
create index if not exists leads_email_idx on public.leads (email);

-- 直接アクセスは全部禁止。操作は関数経由だけ。
alter table public.app_settings enable row level security;
alter table public.members enable row level security;
alter table public.sessions enable row level security;
alter table public.member_connections enable row level security;
alter table public.leads enable row level security;

revoke all on public.app_settings from anon, authenticated, public;
revoke all on public.members from anon, authenticated, public;
revoke all on public.sessions from anon, authenticated, public;
revoke all on public.member_connections from anon, authenticated, public;
revoke all on public.leads from anon, authenticated, public;

drop policy if exists "anon can insert leads" on public.leads;

-- ────────────────────────────────
-- 内部ヘルパー
-- ────────────────────────────────
create or replace function public._session_member(p_token uuid)
returns public.members
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  if p_token is null then
    raise exception 'SESSION_EXPIRED';
  end if;
  select m.*
    into v_member
    from public.sessions s
    join public.members m on m.id = s.member_id
   where s.token = p_token
     and s.expires_at > now();
  if not found then
    raise exception 'SESSION_EXPIRED';
  end if;
  if v_member.status <> 'active' then
    raise exception 'SUSPENDED';
  end if;
  return v_member;
end;
$$;

create or replace function public._require_admin(p_token uuid)
returns public.members
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  v_member := public._session_member(p_token);
  if v_member.role <> 'admin' then
    raise exception 'FORBIDDEN';
  end if;
  return v_member;
end;
$$;

create or replace function public._member_json(p_member public.members)
returns jsonb
language sql
immutable
as $$
  select jsonb_build_object(
    'id', p_member.id,
    'email', p_member.email,
    'role', p_member.role,
    'status', p_member.status,
    'can_trade', p_member.can_trade,
    'last_login_at', p_member.last_login_at,
    'created_at', p_member.created_at
  );
$$;

create or replace function public._issue_session(p_member_id uuid)
returns uuid
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_token uuid;
begin
  delete from public.sessions where member_id = p_member_id and expires_at < now();
  insert into public.sessions (member_id, expires_at)
  values (p_member_id, now() + interval '30 days')
  returning token into v_token;
  update public.members set last_login_at = now() where id = p_member_id;
  return v_token;
end;
$$;

-- ────────────────────────────────
-- 認証
-- ────────────────────────────────
create or replace function public.auth_register(p_email text, p_password text, p_entry text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_email text := lower(trim(p_email));
  v_role text := 'user';
  v_member public.members;
begin
  if v_email is null or v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'INVALID_EMAIL';
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
  if exists (select 1 from public.members where email = v_email) then
    raise exception 'EMAIL_TAKEN';
  end if;
  if not exists (select 1 from public.members) then
    v_role := 'admin';
  end if;

  insert into public.members (email, password_hash, role)
  values (v_email, crypt(p_password, gen_salt('bf')), v_role)
  returning * into v_member;

  return jsonb_build_object(
    'token', public._issue_session(v_member.id),
    'member', public._member_json(v_member)
  );
end;
$$;

-- 入場パスワードだけ先に確かめる（受付で「合ってますね」と言うため）。
-- 本登録のときにもう一度確かめるので、ここは案内用。
create or replace function public.auth_check_entry(p_entry text)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
begin
  -- 総当たりを遅らせる
  perform pg_sleep(0.3);
  return jsonb_build_object(
    'ok',
    p_entry is not null and exists (
      select 1 from public.app_settings
       where id = 1
         and entry_password_hash = crypt(p_entry, entry_password_hash)
    )
  );
end;
$$;

create or replace function public.auth_login(p_email text, p_password text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_email text := lower(trim(p_email));
  v_member public.members;
begin
  select * into v_member from public.members where email = v_email;
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

create or replace function public.auth_logout(p_token uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  delete from public.sessions where token = p_token;
  return jsonb_build_object('ok', true);
end;
$$;

create or replace function public.auth_me(p_token uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  v_member := public._session_member(p_token);
  return jsonb_build_object('member', public._member_json(v_member));
end;
$$;

-- ────────────────────────────────
-- 管理者
-- ────────────────────────────────
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
        m.role,
        m.status,
        m.can_trade,
        m.last_login_at,
        m.created_at,
        c.account,
        c.server,
        c.running,
        c.updated_at as connected_at
      from public.members m
      left join public.member_connections c on c.member_id = m.id
    ) r
  ), '[]'::jsonb);
end;
$$;

create or replace function public.admin_update_member(
  p_token uuid,
  p_member_id uuid,
  p_role text default null,
  p_status text default null,
  p_can_trade boolean default null
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_admin public.members;
  v_target public.members;
  v_admins int;
begin
  v_admin := public._require_admin(p_token);
  select * into v_target from public.members where id = p_member_id;
  if not found then
    raise exception 'NOT_FOUND';
  end if;

  if p_role is not null and p_role not in ('user', 'admin') then
    raise exception 'INVALID_ROLE';
  end if;
  if p_status is not null and p_status not in ('active', 'suspended') then
    raise exception 'INVALID_STATUS';
  end if;

  if v_target.id = v_admin.id and p_role = 'user' then
    select count(*) into v_admins from public.members where role = 'admin' and status = 'active';
    if v_admins <= 1 then
      raise exception 'LAST_ADMIN';
    end if;
  end if;
  if v_target.id = v_admin.id and p_status = 'suspended' then
    raise exception 'LAST_ADMIN';
  end if;

  update public.members
     set role = coalesce(p_role, role),
         status = coalesce(p_status, status),
         can_trade = coalesce(p_can_trade, can_trade)
   where id = p_member_id
   returning * into v_target;

  if p_status = 'suspended' then
    delete from public.sessions where member_id = p_member_id;
  end if;

  return public._member_json(v_target);
end;
$$;

create or replace function public.admin_set_password(
  p_token uuid,
  p_member_id uuid,
  p_password text
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  if p_password is null or char_length(p_password) < 8 then
    raise exception 'WEAK_PASSWORD';
  end if;
  if not exists (select 1 from public.members where id = p_member_id) then
    raise exception 'NOT_FOUND';
  end if;
  update public.members
     set password_hash = crypt(p_password, gen_salt('bf'))
   where id = p_member_id;
  delete from public.sessions where member_id = p_member_id;
  return jsonb_build_object('ok', true);
end;
$$;

create or replace function public.admin_set_entry_password(p_token uuid, p_entry text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  if p_entry is null or char_length(trim(p_entry)) < 8 then
    raise exception 'WEAK_PASSWORD';
  end if;
  update public.app_settings
     set entry_password_hash = crypt(trim(p_entry), gen_salt('bf')),
         updated_at = now()
   where id = 1;
  return jsonb_build_object('ok', true);
end;
$$;

-- サイト全体の設定。誰でも読めるが、書けるのは管理者だけ
create or replace function public.site_settings_get()
returns jsonb
language sql
security definer
set search_path = public
as $$
  select coalesce(site_settings, '{}'::jsonb) from public.app_settings where id = 1;
$$;

create or replace function public.admin_set_site_settings(p_token uuid, p_settings jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  perform public._require_admin(p_token);
  if p_settings is null or jsonb_typeof(p_settings) <> 'object' then
    raise exception 'BAD_SETTINGS';
  end if;
  update public.app_settings
     set site_settings = p_settings,
         updated_at = now()
   where id = 1;
  return p_settings;
end;
$$;

-- ────────────────────────────────
-- 会員自身の接続データ
-- ────────────────────────────────
create or replace function public.member_get_connection(p_token uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
  v_row public.member_connections;
begin
  v_member := public._session_member(p_token);
  select * into v_row from public.member_connections where member_id = v_member.id;
  if not found then
    return jsonb_build_object('connection', null);
  end if;
  return jsonb_build_object(
    'connection', jsonb_build_object(
      'email', v_row.email,
      'account', v_row.account,
      'server', v_row.server,
      'connectedAt', v_row.connected_at,
      'running', v_row.running,
      'settings', v_row.settings
    )
  );
end;
$$;

create or replace function public.member_put_connection(p_token uuid, p_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  v_member := public._session_member(p_token);
  insert into public.member_connections (
    member_id, email, account, server, connected_at, running, settings, updated_at
  ) values (
    v_member.id,
    coalesce(p_payload->>'email', v_member.email),
    p_payload->>'account',
    p_payload->>'server',
    nullif(p_payload->>'connectedAt', '')::timestamptz,
    coalesce((p_payload->>'running')::boolean, false),
    coalesce(p_payload->'settings', '{}'::jsonb),
    now()
  )
  on conflict (member_id) do update set
    email = excluded.email,
    account = excluded.account,
    server = excluded.server,
    connected_at = excluded.connected_at,
    running = excluded.running,
    settings = excluded.settings,
    updated_at = now();
  return jsonb_build_object('ok', true);
end;
$$;

create or replace function public.member_clear_connection(p_token uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  v_member := public._session_member(p_token);
  delete from public.member_connections where member_id = v_member.id;
  return jsonb_build_object('ok', true);
end;
$$;

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
  values (coalesce(nullif(trim(p_email), ''), v_member.email), coalesce(p_source, 'algo-connect'), v_member.id);
  return jsonb_build_object('ok', true);
end;
$$;

-- ────────────────────────────────
-- 実行権限（テーブルは渡さない）
-- ────────────────────────────────
revoke all on function public._session_member(uuid) from public, anon, authenticated;
revoke all on function public._require_admin(uuid) from public, anon, authenticated;
revoke all on function public._member_json(public.members) from public, anon, authenticated;
revoke all on function public._issue_session(uuid) from public, anon, authenticated;

grant execute on function public.auth_register(text, text, text) to anon, authenticated;
grant execute on function public.auth_check_entry(text) to anon, authenticated;
grant execute on function public.auth_login(text, text) to anon, authenticated;
grant execute on function public.auth_logout(uuid) to anon, authenticated;
grant execute on function public.auth_me(uuid) to anon, authenticated;
grant execute on function public.admin_list_members(uuid) to anon, authenticated;
grant execute on function public.admin_update_member(uuid, uuid, text, text, boolean) to anon, authenticated;
grant execute on function public.admin_set_password(uuid, uuid, text) to anon, authenticated;
grant execute on function public.admin_set_entry_password(uuid, text) to anon, authenticated;
grant execute on function public.site_settings_get() to anon, authenticated;
grant execute on function public.admin_set_site_settings(uuid, jsonb) to anon, authenticated;
grant execute on function public.member_get_connection(uuid) to anon, authenticated;
grant execute on function public.member_put_connection(uuid, jsonb) to anon, authenticated;
grant execute on function public.member_clear_connection(uuid) to anon, authenticated;
grant execute on function public.member_save_lead(uuid, text, text) to anon, authenticated;

-- ════════════════════════════════════════════════════════════
-- MT5連携のワンタイム合図（AI Trader Connect）
--
-- サイトの「MT5と連携する」を押したときだけ発行する、短命の合図。
-- これを aitrader://connect?token=... でお客様のPCのアプリへ渡す。
--
--   ・会員IDそのものは URL に載せない
--   ・推測できない長さの乱数
--   ・数分で切れる
--   ・一度使ったら無効
--   ・アプリ単体では作れない（ログイン中のセッションが要る）
--
-- 既存のテーブルや関数は変更していない。ここから下は追加だけ。
-- ════════════════════════════════════════════════════════════
create table if not exists public.connect_tokens (
  token text primary key,
  member_id uuid not null references public.members (id) on delete cascade,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists connect_tokens_member_idx on public.connect_tokens (member_id);
create index if not exists connect_tokens_expires_idx on public.connect_tokens (expires_at);

alter table public.connect_tokens enable row level security;

-- 合図を発行する。ログイン中の会員だけが、自分のぶんを作れる。
create or replace function public.connect_token_issue(p_token uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
  v_token text;
begin
  v_member := public._session_member(p_token);

  -- 古いものを片づける（切れたもの・使ったもの・この会員の未使用ぶん）
  delete from public.connect_tokens
   where expires_at < now()
      or used_at is not null
      or member_id = v_member.id;

  v_token := encode(extensions.gen_random_bytes(32), 'hex');
  insert into public.connect_tokens (token, member_id, expires_at)
  values (v_token, v_member.id, now() + interval '5 minutes');

  return jsonb_build_object('token', v_token, 'expires_in', 300);
end;
$$;

-- 合図を使う。サイトのサーバー関数（/api/connect）からだけ呼ぶ。
-- 正しければ会員IDを返し、その場で使用済みにする（二度は使えない）。
create or replace function public.connect_token_redeem(p_connect_token text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_row public.connect_tokens;
  v_member public.members;
begin
  if p_connect_token is null or length(p_connect_token) < 32 then
    raise exception 'INVALID_TOKEN';
  end if;

  -- 使用済みにできたものだけを受け取る（同時に2回来ても1回しか通らない）
  update public.connect_tokens
     set used_at = now()
   where token = p_connect_token
     and used_at is null
     and expires_at > now()
  returning * into v_row;

  if not found then
    raise exception 'INVALID_TOKEN';
  end if;

  select * into v_member from public.members where id = v_row.member_id;
  if not found or v_member.status <> 'active' then
    raise exception 'INVALID_TOKEN';
  end if;

  return jsonb_build_object('member_id', v_member.id, 'can_trade', v_member.can_trade);
end;
$$;

grant execute on function public.connect_token_issue(uuid) to anon, authenticated;
grant execute on function public.connect_token_redeem(text) to anon, authenticated;
