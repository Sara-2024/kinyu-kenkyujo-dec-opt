-- ════════════════════════════════════════════════════════════
-- プランごとの合言葉（ロビーの「接続ツールの設置」で打ち込むもの）
--
--   ・合言葉はプランごとに1つ。first（ファーストクラス）/ crystal（ロイヤルファーストクラス）
--   ・ロビーで合言葉を打つと、そのプランの案内に振り分けられる（違うプランへは行けない）
--   ・会員登録（auth_register）の「入場パスワード」も、この合言葉で受ける。
--     合ったプランが members.plan に入る（古い入場パスワード app_settings も当面は通す。plan は空）
--   ・ロイヤルファーストクラスは MT5 の口座を2つつなぐ。会員 ＝ 口座番号なので会員が2つできる
--     （どちらも同じ合言葉で登録する）
--   ・合言葉そのものは保存しない（crypt のハッシュだけ）
-- ════════════════════════════════════════════════════════════
alter table public.members add column if not exists plan text check (plan in ('first', 'crystal'));

create table if not exists public.plan_passwords (
  plan text primary key check (plan in ('first', 'crystal')),
  password_hash text not null,
  updated_at timestamptz not null default now()
);

revoke all on table public.plan_passwords from public, anon, authenticated;

-- これまでの入場パスワードは、そのままファーストクラスの合言葉として引き継ぐ
insert into public.plan_passwords (plan, password_hash)
select 'first', entry_password_hash from public.app_settings where id = 1
on conflict (plan) do nothing;

-- 会員の JSON にプランを足す
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
    'plan', p_member.plan,
    'role', p_member.role,
    'status', p_member.status,
    'can_trade', p_member.can_trade,
    'last_login_at', p_member.last_login_at,
    'created_at', p_member.created_at
  );
$$;

-- 合言葉に合うプラン。合わなければ null
create or replace function public._plan_of_entry(p_entry text)
returns text
language sql
stable
security definer
set search_path = public, extensions
as $$
  select plan from public.plan_passwords
   where p_entry is not null
     and password_hash = crypt(p_entry, password_hash)
   limit 1;
$$;

-- ロビーが「この合言葉はどのプランか」を聞く（登録の前に案内を振り分けるため）
create or replace function public.plan_check(p_entry text)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
begin
  -- 総当たりを遅らせる
  perform pg_sleep(0.3);
  return jsonb_build_object('plan', public._plan_of_entry(p_entry));
end;
$$;

-- 会員登録：入場パスワードの代わりにプランの合言葉で受け、プランを会員に記録する
create or replace function public.auth_register(p_account bigint, p_name text, p_password text, p_entry text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_name text := left(trim(coalesce(p_name, '')), 80);
  v_role text := 'user';
  v_plan text;
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
  v_plan := public._plan_of_entry(p_entry);
  if v_plan is null and (p_entry is null or not exists (
    select 1 from public.app_settings
     where id = 1
       and entry_password_hash = crypt(p_entry, entry_password_hash)
  )) then
    raise exception 'BAD_ENTRY';
  end if;
  if exists (select 1 from public.members where account = p_account) then
    raise exception 'ACCOUNT_TAKEN';
  end if;
  if not exists (select 1 from public.members) then
    v_role := 'admin';
  end if;

  insert into public.members (account, name, password_hash, role, plan)
  values (p_account, v_name, crypt(p_password, gen_salt('bf')), v_role, v_plan)
  returning * into v_member;

  return jsonb_build_object(
    'token', public._issue_session(v_member.id),
    'member', public._member_json(v_member)
  );
end;
$$;

-- 管理者がプランの合言葉を決める（8文字以上）
create or replace function public.admin_set_plan_password(p_token uuid, p_plan text, p_password text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  if p_plan is null or p_plan not in ('first', 'crystal') then
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

-- 管理者の一覧にプランを足す
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
        m.plan,
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

revoke all on function public._plan_of_entry(text) from public, anon, authenticated;
grant execute on function public.plan_check(text) to anon, authenticated;
grant execute on function public.auth_register(bigint, text, text, text) to anon, authenticated;
grant execute on function public.admin_set_plan_password(uuid, text, text) to anon, authenticated;
