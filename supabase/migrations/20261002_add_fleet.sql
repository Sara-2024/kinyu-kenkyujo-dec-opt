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
