-- Supabase ダッシュボード → SQL Editor でこのファイルを実行
-- 何回実行しても大丈夫（既存の leads は残す）
--
-- 初回の入場パスワード: AITrader-dream
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
values (1, extensions.crypt('AITrader-dream', extensions.gen_salt('bf')))
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

-- ════════════════════════════════════════════════════════════
-- 一斉制御（デモ口座の登録簿）
-- 中身は supabase/migrations/20261002_add_fleet.sql と同じ。
-- すでに動いている環境には migration のほうを流す。
-- ════════════════════════════════════════════════════════════
-- ════════════════════════════════════════════════════════════
-- 一斉制御（デモ口座の登録簿）
--
-- 自社のデモ口座（100〜200）を1つの画面から一斉に止めるための台帳。
-- 既存のテーブル・関数は変更していない。ここから下は追加だけ。
--
--   ・口座は「ログイン中の会員」が登録する。会員ID が、その口座の PC で動く
--     MT5 Automatic の部屋（中継の room）になる。一斉停止はその部屋へ流す
--   ・パスワードは預かるだけで、停止には使わない（ブリッジが止めるので要らない）。
--     暗号化して保存し、管理者の操作でしか取り出せない
--   ・「対象にする／対象外にする」は口座ごとに持つ（included）
-- ════════════════════════════════════════════════════════════
create table if not exists public.fleet_accounts (
  id uuid primary key default gen_random_uuid(),
  member_id uuid not null references public.members (id) on delete cascade,
  account bigint not null,
  server text not null,
  password_enc bytea not null,
  included boolean not null default true,
  note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (account, server)
);

create index if not exists fleet_accounts_member_idx on public.fleet_accounts (member_id);

-- 暗号化の鍵。関数の中からしか読めない（下で revoke する）
create table if not exists public.fleet_secret (
  id int primary key default 1 check (id = 1),
  key text not null
);

insert into public.fleet_secret (id, key)
values (1, encode(extensions.gen_random_bytes(32), 'hex'))
on conflict (id) do nothing;

create or replace function public._fleet_key()
returns text
language sql
stable
security definer
set search_path = public, extensions
as $$
  select key from public.fleet_secret where id = 1;
$$;

create or replace function public._fleet_row_json(r public.fleet_accounts, p_email text)
returns jsonb
language sql
immutable
as $$
  select jsonb_build_object(
    'id', r.id,
    'member_id', r.member_id,
    'email', p_email,
    'account', r.account,
    'server', r.server,
    'included', r.included,
    'note', r.note,
    'created_at', r.created_at,
    'updated_at', r.updated_at
  );
$$;

-- 会員が自分の口座を登録する（同じ口座なら上書き）
create or replace function public.fleet_register(
  p_token uuid,
  p_account bigint,
  p_server text,
  p_password text
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
  v_server text := trim(coalesce(p_server, ''));
  v_row public.fleet_accounts;
begin
  v_member := public._session_member(p_token);
  if p_account is null or p_account <= 0 then
    raise exception 'BAD_ACCOUNT';
  end if;
  if v_server = '' or length(v_server) > 80 then
    raise exception 'BAD_SERVER';
  end if;
  if coalesce(p_password, '') = '' or length(p_password) > 200 then
    raise exception 'BAD_PASSWORD';
  end if;

  insert into public.fleet_accounts (member_id, account, server, password_enc)
  values (
    v_member.id,
    p_account,
    v_server,
    extensions.pgp_sym_encrypt(p_password, public._fleet_key())
  )
  on conflict (account, server) do update
    set password_enc = excluded.password_enc,
        member_id = v_member.id,
        updated_at = now()
    -- 他人が登録した口座は、管理者でなければ上書きしない
    where public.fleet_accounts.member_id = v_member.id or v_member.role = 'admin'
  returning * into v_row;

  if v_row.id is null then
    raise exception 'TAKEN';
  end if;
  return public._fleet_row_json(v_row, v_member.email);
end;
$$;

-- 自分が登録した口座
create or replace function public.fleet_my_accounts(p_token uuid)
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
  return coalesce((
    select jsonb_agg(public._fleet_row_json(r, v_member.email) order by r.created_at)
    from public.fleet_accounts r
    where r.member_id = v_member.id
  ), '[]'::jsonb);
end;
$$;

-- 管理者: 全口座（パスワードは返さない）
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
    select jsonb_agg(public._fleet_row_json(r, m.email) order by r.created_at)
    from public.fleet_accounts r
    join public.members m on m.id = r.member_id
  ), '[]'::jsonb);
end;
$$;

-- 管理者: 対象にする／対象外にする
create or replace function public.fleet_set_included(p_token uuid, p_id uuid, p_included boolean)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_row public.fleet_accounts;
begin
  perform public._require_admin(p_token);
  update public.fleet_accounts
     set included = coalesce(p_included, included), updated_at = now()
   where id = p_id
  returning * into v_row;
  if v_row.id is null then
    raise exception 'NOT_FOUND';
  end if;
  return jsonb_build_object('ok', true, 'included', v_row.included);
end;
$$;

-- 管理者: 控えのメモ（PC の場所など）
create or replace function public.fleet_set_note(p_token uuid, p_id uuid, p_note text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  update public.fleet_accounts
     set note = left(coalesce(p_note, ''), 200), updated_at = now()
   where id = p_id;
  if not found then
    raise exception 'NOT_FOUND';
  end if;
  return jsonb_build_object('ok', true);
end;
$$;

-- 本人か管理者が消す
create or replace function public.fleet_delete(p_token uuid, p_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  v_member := public._session_member(p_token);
  delete from public.fleet_accounts
   where id = p_id and (member_id = v_member.id or v_member.role = 'admin');
  if not found then
    raise exception 'NOT_FOUND';
  end if;
  return jsonb_build_object('ok', true);
end;
$$;

-- 管理者: 預かったパスワードを取り出す（MT5 に自分で入るとき用）
create or replace function public.fleet_reveal(p_token uuid, p_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
declare
  v_row public.fleet_accounts;
begin
  perform public._require_admin(p_token);
  select * into v_row from public.fleet_accounts where id = p_id;
  if v_row.id is null then
    raise exception 'NOT_FOUND';
  end if;
  return jsonb_build_object(
    'account', v_row.account,
    'server', v_row.server,
    'password', extensions.pgp_sym_decrypt(v_row.password_enc, public._fleet_key())
  );
end;
$$;

revoke all on table public.fleet_secret from public, anon, authenticated;
revoke all on table public.fleet_accounts from public, anon, authenticated;
revoke all on function public._fleet_key() from public, anon, authenticated;
revoke all on function public._fleet_row_json(public.fleet_accounts, text) from public, anon, authenticated;

grant execute on function public.fleet_register(uuid, bigint, text, text) to anon, authenticated;
grant execute on function public.fleet_my_accounts(uuid) to anon, authenticated;
grant execute on function public.fleet_list(uuid) to anon, authenticated;
grant execute on function public.fleet_set_included(uuid, uuid, boolean) to anon, authenticated;
grant execute on function public.fleet_set_note(uuid, uuid, text) to anon, authenticated;
grant execute on function public.fleet_delete(uuid, uuid) to anon, authenticated;
grant execute on function public.fleet_reveal(uuid, uuid) to anon, authenticated;

-- ════════════════════════════════════════════════════════════
-- 一斉制御: 管理者が「つながっている口座」を登録簿に加える
--
-- 連携済みの PC は中継に部屋（会員ID）として見えているので、お客様に
-- /fleet/join を開いてもらわなくても、管理者が一覧から登録できるようにする。
-- パスワードは預からない（空で入れる。あとで本人が /fleet/join で入れれば上書き）。
-- ════════════════════════════════════════════════════════════
create or replace function public.fleet_register_for(
  p_token uuid,
  p_member_id uuid,
  p_account bigint,
  p_server text,
  p_password text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
  v_server text := trim(coalesce(p_server, ''));
  v_row public.fleet_accounts;
begin
  perform public._require_admin(p_token);
  select * into v_member from public.members where id = p_member_id;
  if v_member.id is null then
    raise exception 'NOT_FOUND';
  end if;
  if p_account is null or p_account <= 0 then
    raise exception 'BAD_ACCOUNT';
  end if;
  if v_server = '' or length(v_server) > 80 then
    raise exception 'BAD_SERVER';
  end if;

  insert into public.fleet_accounts (member_id, account, server, password_enc)
  values (
    v_member.id,
    p_account,
    v_server,
    extensions.pgp_sym_encrypt(coalesce(p_password, ''), public._fleet_key())
  )
  on conflict (account, server) do update
    set member_id = excluded.member_id,
        password_enc = case
          when coalesce(p_password, '') = '' then public.fleet_accounts.password_enc
          else excluded.password_enc
        end,
        updated_at = now()
  returning * into v_row;
  return public._fleet_row_json(v_row, v_member.email);
end;
$$;

grant execute on function public.fleet_register_for(uuid, uuid, bigint, text, text) to anon, authenticated;

-- ════════════════════════════════════════════════════════════
-- 一斉制御: お客様が「運営による一斉停止」を受け付けないと決めた記録
--
-- サイトと連携した口座は、そのまま一斉制御の対象になる（連携＝同意）。
-- 受け付けたくないお客様は管理画面で拒否でき、その記録がここに残る。
-- 拒否した部屋には、一斉制御の指令を流さない（画面と中継の両方で確かめる）。
-- ════════════════════════════════════════════════════════════
create table if not exists public.fleet_optout (
  member_id uuid primary key references public.members (id) on delete cascade,
  created_at timestamptz not null default now()
);

revoke all on table public.fleet_optout from public, anon, authenticated;

-- 本人が、受け付ける／受け付けないを切り替える
create or replace function public.fleet_optout_set(p_token uuid, p_optout boolean)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  v_member := public._session_member(p_token);
  if coalesce(p_optout, false) then
    insert into public.fleet_optout (member_id) values (v_member.id)
    on conflict (member_id) do nothing;
  else
    delete from public.fleet_optout where member_id = v_member.id;
  end if;
  return jsonb_build_object('ok', true, 'optout', coalesce(p_optout, false));
end;
$$;

-- 本人が、いまどちらになっているかを見る
create or replace function public.fleet_my_optout(p_token uuid)
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
  return jsonb_build_object(
    'optout', exists (select 1 from public.fleet_optout where member_id = v_member.id)
  );
end;
$$;

-- 管理者（と中継）が、拒否している会員の一覧を取る
create or replace function public.fleet_optouts(p_token uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  return coalesce((select jsonb_agg(member_id) from public.fleet_optout), '[]'::jsonb);
end;
$$;

grant execute on function public.fleet_optout_set(uuid, boolean) to anon, authenticated;
grant execute on function public.fleet_my_optout(uuid) to anon, authenticated;
grant execute on function public.fleet_optouts(uuid) to anon, authenticated;

-- ════════════════════════════════════════════════════════════
-- 管理者画面: 会員の削除と、BAN した会員のブリッジを中継が切るための問い合わせ
--
-- ・admin_delete_member … 会員を消す（セッション・連携・一斉制御の記録も一緒に消える）。
--   自分自身と、最後の管理者は消せない。
-- ・bridges_blocked … 渡した会員IDのうち「利用できない」もの（停止中・存在しない）を返す。
--   中継がブリッジの接続時と、つないでいるあいだ定期的に呼ぶ。
--   会員IDは推測できない乱数なので、匿名で呼べても分かるのは「止められているか」だけ。
-- ════════════════════════════════════════════════════════════
create or replace function public.admin_delete_member(p_token uuid, p_member_id uuid)
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
  if v_target.id = v_admin.id then
    raise exception 'SELF_DELETE';
  end if;
  if v_target.role = 'admin' then
    select count(*) into v_admins from public.members where role = 'admin' and status = 'active';
    if v_admins <= 1 then
      raise exception 'LAST_ADMIN';
    end if;
  end if;
  delete from public.members where id = p_member_id;
  return jsonb_build_object('ok', true, 'id', p_member_id);
end;
$$;

create or replace function public.bridges_blocked(p_ids uuid[])
returns jsonb
language sql
stable
security definer
set search_path = public, extensions
as $$
  select coalesce(jsonb_agg(id), '[]'::jsonb)
  from unnest(coalesce(p_ids, '{}'::uuid[])) as t(id)
  where not exists (
    select 1 from public.members m where m.id = t.id and m.status = 'active'
  );
$$;

grant execute on function public.admin_delete_member(uuid, uuid) to anon, authenticated;
grant execute on function public.bridges_blocked(uuid[]) to anon, authenticated;
