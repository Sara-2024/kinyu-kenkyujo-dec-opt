-- プレミアムプラン（premium）を足す。基本はファーストクラスと同じで、ドリームランドへの渡航の案内が無い。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行。

alter table public.members drop constraint if exists members_plan_check;
alter table public.members add constraint members_plan_check check (plan in ('first', 'crystal', 'premium'));
alter table public.plan_passwords drop constraint if exists plan_passwords_plan_check;
alter table public.plan_passwords add constraint plan_passwords_plan_check check (plan in ('first', 'crystal', 'premium'));
alter table public.dreamland_applications drop constraint if exists dreamland_applications_plan_check;
alter table public.dreamland_applications add constraint dreamland_applications_plan_check check (plan in ('first', 'crystal', 'premium'));

-- プランを確かめる関数を作り直す（schema.sql と同じ中身）
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
  if p_plan is null or p_plan not in ('first', 'crystal', 'premium') then
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

create or replace function public.admin_set_plan_password(p_token uuid, p_plan text, p_password text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  if p_plan is null or p_plan not in ('first', 'crystal', 'premium') then
    raise exception 'BAD_PLAN';
  end if;
  if p_password is null or char_length(trim(p_password)) < 8 then
    raise exception 'WEAK_PASSWORD';
  end if;
  insert into public.plan_passwords (plan, password_hash)
  values (p_plan, crypt(trim(p_password), gen_salt('bf')))
  on conflict (plan) do update
    set password_hash = excluded.password_hash,
        updated_at = now();
  return jsonb_build_object('ok', true);
end;
$$;

-- プレミアムプランの合言葉は、管理サイトの「プランの合言葉」から決める（未設定のあいだは誰も入れない）。
