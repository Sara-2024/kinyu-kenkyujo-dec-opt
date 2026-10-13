-- ════════════════════════════════════════════════════════════
-- ドリームランド渡航手続き: お客様の MT5 口座の申込
--
-- ロビー（dreamland/index.html）のサービスカウンターで、お客様が
-- MT5 の口座番号・サーバー・パスワードを記入して送ったものを預かる。
-- 送り先はサイトの /api/dreamland（api/_lib/dreamland.ts）。
-- ロビーは Supabase を直接叩かない（鍵を配らない）。
--
--   ・パスワードは一斉制御の登録簿（fleet_accounts）と同じ鍵で暗号化して保存し、
--     管理者の操作（dreamland_reveal）でしか取り出せない
--   ・同じ口座（口座番号＋サーバー）をもう一度送ったら上書きし、回数を数える
--     （「会員登録を何度もやる人は会員権を取り消す」の判断材料。消しはしない）
--   ・プランは first（ファーストクラス）/ crystal（プレミアムファースト・クリスタル）
--   ・申込には受付番号（DL- + 6桁）を振って、お客様の画面に出す
-- ════════════════════════════════════════════════════════════
create table if not exists public.dreamland_applications (
  id uuid primary key default gen_random_uuid(),
  application_no text not null unique,
  account bigint not null,
  server text not null,
  password_enc bytea not null,
  plan text not null check (plan in ('first', 'crystal')),
  name text not null default '',
  email text not null default '',
  platform text check (platform in ('windows', 'mac')),
  consent_at timestamptz not null default now(),
  submissions int not null default 1,
  note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (account, server)
);

revoke all on table public.dreamland_applications from public, anon, authenticated;
alter table public.dreamland_applications enable row level security;

create or replace function public._dreamland_row_json(r public.dreamland_applications)
returns jsonb
language sql
immutable
as $$
  select jsonb_build_object(
    'id', r.id,
    'application_no', r.application_no,
    'account', r.account,
    'server', r.server,
    'plan', r.plan,
    'name', r.name,
    'email', r.email,
    'platform', r.platform,
    'consent_at', r.consent_at,
    'submissions', r.submissions,
    'note', r.note,
    'created_at', r.created_at,
    'updated_at', r.updated_at
  );
$$;

-- お客様の申込を預かる（サイトの /api/dreamland から呼ぶ。同じ口座なら上書き）
create or replace function public.dreamland_apply(
  p_account bigint,
  p_server text,
  p_password text,
  p_plan text,
  p_name text default '',
  p_email text default '',
  p_platform text default null,
  p_consent boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_server text := trim(coalesce(p_server, ''));
  v_name text := left(trim(coalesce(p_name, '')), 80);
  v_email text := left(lower(trim(coalesce(p_email, ''))), 200);
  v_platform text := nullif(trim(coalesce(p_platform, '')), '');
  v_no text;
  v_row public.dreamland_applications;
begin
  if not coalesce(p_consent, false) then
    raise exception 'NO_CONSENT';
  end if;
  if p_account is null or p_account <= 0 then
    raise exception 'BAD_ACCOUNT';
  end if;
  if v_server = '' or length(v_server) > 80 then
    raise exception 'BAD_SERVER';
  end if;
  if coalesce(p_password, '') = '' or length(p_password) > 200 then
    raise exception 'BAD_PASSWORD';
  end if;
  if p_plan is null or p_plan not in ('first', 'crystal') then
    raise exception 'BAD_PLAN';
  end if;
  if v_platform is not null and v_platform not in ('windows', 'mac') then
    v_platform := null;
  end if;

  -- 受付番号。被ったら振り直す
  loop
    v_no := 'DL-' || lpad((floor(random() * 1000000))::int::text, 6, '0');
    exit when not exists (select 1 from public.dreamland_applications where application_no = v_no);
  end loop;

  insert into public.dreamland_applications (application_no, account, server, password_enc, plan, name, email, platform)
  values (
    v_no,
    p_account,
    v_server,
    extensions.pgp_sym_encrypt(p_password, public._fleet_key()),
    p_plan,
    v_name,
    v_email,
    v_platform
  )
  on conflict (account, server) do update
    set password_enc = excluded.password_enc,
        plan = excluded.plan,
        name = case when excluded.name = '' then public.dreamland_applications.name else excluded.name end,
        email = case when excluded.email = '' then public.dreamland_applications.email else excluded.email end,
        platform = coalesce(excluded.platform, public.dreamland_applications.platform),
        consent_at = now(),
        submissions = public.dreamland_applications.submissions + 1,
        updated_at = now()
  returning * into v_row;

  return public._dreamland_row_json(v_row);
end;
$$;

-- 管理者: 申込の一覧（パスワードは返さない）
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
    select jsonb_agg(public._dreamland_row_json(r) order by r.updated_at desc)
    from public.dreamland_applications r
  ), '[]'::jsonb);
end;
$$;

-- 管理者: 預かったパスワードを取り出す（EA を納品するときに MT5 へ入る用）
create or replace function public.dreamland_reveal(p_token uuid, p_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
declare
  v_row public.dreamland_applications;
begin
  perform public._require_admin(p_token);
  select * into v_row from public.dreamland_applications where id = p_id;
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

-- 管理者: 覚え書き（納品した日など）
create or replace function public.dreamland_set_note(p_token uuid, p_id uuid, p_note text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  update public.dreamland_applications
     set note = left(coalesce(p_note, ''), 500), updated_at = now()
   where id = p_id;
  if not found then
    raise exception 'NOT_FOUND';
  end if;
  return jsonb_build_object('ok', true);
end;
$$;

-- 管理者: 申込を消す
create or replace function public.dreamland_delete(p_token uuid, p_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  delete from public.dreamland_applications where id = p_id;
  if not found then
    raise exception 'NOT_FOUND';
  end if;
  return jsonb_build_object('ok', true);
end;
$$;

revoke all on function public._dreamland_row_json(public.dreamland_applications) from public, anon, authenticated;

grant execute on function public.dreamland_apply(bigint, text, text, text, text, text, text, boolean) to anon, authenticated;
grant execute on function public.dreamland_list(uuid) to anon, authenticated;
grant execute on function public.dreamland_reveal(uuid, uuid) to anon, authenticated;
grant execute on function public.dreamland_set_note(uuid, uuid, text) to anon, authenticated;
grant execute on function public.dreamland_delete(uuid, uuid) to anon, authenticated;
