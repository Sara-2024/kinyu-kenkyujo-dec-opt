-- ════════════════════════════════════════════════════════════
-- Yumekku【サブスク版】: 管理者が口座を手で追加する ／ サブスクの合言葉で入る
--
--   ・admin_add_subscription … 管理サイトの「口座を追加」。口座番号（とお名前）だけで、
--     サブスクの会員と申請を作り、そのまま承認する（申請ページを通らなくてよい）。
--     すでにその口座の会員がいれば、プランをサブスクにして承認する（管理者は追加できない）。
--   ・subscription_login     … 申請ページが「サブスクの合言葉＋口座番号」で入る道。
--     管理者が追加した口座は、サイトのパスワードが申請ページの作り方と合わないので、これで入る。
--     合言葉がサブスクのもので、その口座がサブスクの会員のときだけ通す（総当たりは pg_sleep で遅らせる）。
-- 追加だけ。既存の表・関数は変えない。
-- ════════════════════════════════════════════════════════════
create or replace function public.admin_add_subscription(p_token uuid, p_account bigint, p_name text default '', p_status text default 'active')
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_name text := left(trim(coalesce(p_name, '')), 80);
  v_member public.members;
  v_row public.subscriptions;
begin
  perform public._require_admin(p_token);
  if p_account is null or p_account <= 0 then
    raise exception 'BAD_ACCOUNT';
  end if;
  if p_status is null or p_status not in ('pending', 'active', 'stopped') then
    raise exception 'BAD_STATUS';
  end if;

  select * into v_member from public.members where account = p_account;
  if not found then
    -- サイトのパスワードはでたらめな値にしておく（お客様は subscription_login で入る）
    insert into public.members (account, name, password_hash, role, plan)
    values (p_account, coalesce(nullif(v_name, ''), '（お名前未記入）'),
            crypt(encode(gen_random_bytes(24), 'hex'), gen_salt('bf')), 'user', 'subscription')
    returning * into v_member;
  else
    if v_member.role = 'admin' then
      raise exception 'FORBIDDEN';
    end if;
    update public.members
       set plan = 'subscription',
           name = case when v_name <> '' then v_name else name end
     where id = v_member.id
     returning * into v_member;
  end if;

  insert into public.subscriptions (member_id, status, approved_at, stopped_at, note)
  values (v_member.id, p_status,
          case when p_status = 'active' then now() end,
          case when p_status = 'stopped' then now() end,
          '管理者が追加')
  on conflict (member_id) do update
    set approved_at = case when excluded.status = 'active' and public.subscriptions.status <> 'active' then now() else public.subscriptions.approved_at end,
        stopped_at = case when excluded.status = 'stopped' and public.subscriptions.status <> 'stopped' then now() else public.subscriptions.stopped_at end,
        status = excluded.status,
        updated_at = now()
  returning * into v_row;

  return jsonb_build_object('member_id', v_member.id, 'account', v_member.account) || public._subscription_json(v_row);
end;
$$;

create or replace function public.subscription_login(p_account bigint, p_entry text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  -- 総当たりを遅らせる
  perform pg_sleep(0.3);
  if public._plan_of_entry(p_entry) is distinct from 'subscription' then
    raise exception 'BAD_ENTRY';
  end if;
  select * into v_member from public.members where account = p_account;
  if not found or v_member.plan is distinct from 'subscription' then
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

grant execute on function public.admin_add_subscription(uuid, bigint, text, text) to anon, authenticated;
grant execute on function public.subscription_login(bigint, text) to anon, authenticated;
