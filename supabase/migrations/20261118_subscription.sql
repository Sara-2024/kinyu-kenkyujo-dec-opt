-- ════════════════════════════════════════════════════════════
-- Yumekku【サブスク版】: 運営が承認しているあいだだけ、システム（EA）が使える
--
--   ・お客様はロビーとは別の特別ゲート（dreamland/yumekku-sub/）で、サブスクの合言葉・
--     口座番号・お名前を入れて「申請」する。会員はプラン subscription で作られる（会員 ＝ 口座番号）。
--   ・運営は管理サイトの「Yumekku【サブスク版】の申請」で 承認 / 停止 を切り替える（subscriptions）。
--   ・承認中だけ、この DB が「利用許可（24〜25 時間で切れる。口座番号に結びついた署名つき）」を出す
--     （subscription_licenses）。中継がそれを 1 分ごとにパスポートへ渡し、パスポートが指令ファイルに書き、
--     EA は許可が無い・切れている・署名が合わないときは新規エントリーをしない。
--     停止すると、パスポートがつながっていれば 1 分ほどで、つながっていなくても最長 25 時間で止まる。
--   ・署名の鍵（subscription_secret）は EA にも同じものを焼き込む。鍵はリポジトリに入れない
--     （tools/make-subscription-secret.sh が、EA 用と DB 用の 2 つのファイルを手元に作る）。
--     鍵が入っていないあいだは、承認していても許可を出さない（＝止まる側に倒す）。
-- 追加だけ。既存の表・関数の中身はプランの一覧に subscription を足すだけ。
-- ════════════════════════════════════════════════════════════

-- プランに subscription を足す
alter table public.members drop constraint if exists members_plan_check;
alter table public.members add constraint members_plan_check check (plan in ('first', 'crystal', 'premium', 'subscription'));
alter table public.plan_passwords drop constraint if exists plan_passwords_plan_check;
alter table public.plan_passwords add constraint plan_passwords_plan_check check (plan in ('first', 'crystal', 'premium', 'subscription'));

create or replace function public.admin_set_plan_password(p_token uuid, p_plan text, p_password text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  if p_plan is null or p_plan not in ('first', 'crystal', 'premium', 'subscription') then
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

create or replace function public.admin_set_member_plan(p_token uuid, p_member_id uuid, p_plan text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_target public.members;
begin
  perform public._require_admin(p_token);
  if p_plan is null or p_plan not in ('first', 'crystal', 'premium', 'subscription') then
    raise exception 'BAD_PLAN';
  end if;
  update public.members
     set plan = p_plan
   where id = p_member_id
   returning * into v_target;
  if not found then
    raise exception 'NOT_FOUND';
  end if;
  return public._member_json(v_target);
end;
$$;

-- 申請と承認の状態。pending＝審査中 / active＝承認中（使える） / stopped＝停止（解約など）
create table if not exists public.subscriptions (
  member_id uuid primary key references public.members (id) on delete cascade,
  status text not null default 'pending' check (status in ('pending', 'active', 'stopped')),
  applied_at timestamptz not null default now(),
  approved_at timestamptz,
  stopped_at timestamptz,
  note text not null default '',
  submissions int not null default 1,
  updated_at timestamptz not null default now()
);
alter table public.subscriptions enable row level security;

-- 利用許可の署名の鍵。関数の中からしか読めない（下で revoke する）。行は手元の SQL で入れる
create table if not exists public.subscription_secret (
  id int primary key default 1 check (id = 1),
  secret text not null check (char_length(secret) >= 32)
);
alter table public.subscription_secret enable row level security;

create or replace function public._subscription_secret()
returns text
language sql
stable
security definer
set search_path = public, extensions
as $$
  select secret from public.subscription_secret where id = 1;
$$;

-- 署名：sha256("YMKSUB|<口座番号>|<期限>|<鍵>") の先頭 12 桁（16 進）を数にしたもの。
-- EA（bridge/subscription/YumekkuEA【サブスク版】.mq5 の SubSignature）と同じ計算。
-- 指令ファイルは「名前=数値」しか書けないので、数（48 ビット。double で丸まらない）で渡す
create or replace function public._subscription_sig(p_account bigint, p_until bigint)
returns bigint
language sql
stable
security definer
set search_path = public, extensions
as $$
  select ('x' || lpad(substr(encode(extensions.digest(
           convert_to('YMKSUB|' || p_account::text || '|' || p_until::text || '|' || s.secret, 'UTF8'),
           'sha256'), 'hex'), 1, 12), 16, '0'))::bit(64)::bigint
    from public.subscription_secret s
   where s.id = 1;
$$;

create or replace function public._subscription_json(r public.subscriptions)
returns jsonb
language sql
immutable
as $$
  select jsonb_build_object(
    'status', r.status,
    'applied_at', r.applied_at,
    'approved_at', r.approved_at,
    'stopped_at', r.stopped_at
  );
$$;

-- お客様：申請する（サブスクの合言葉で登録した会員だけ）。
-- 停止中に申請し直したら「審査中」に戻す（使えるようにはならない。承認は運営だけ）
create or replace function public.subscription_apply(p_token uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
  v_row public.subscriptions;
begin
  v_member := public._session_member(p_token);
  if v_member.plan is distinct from 'subscription' then
    raise exception 'NOT_SUBSCRIPTION';
  end if;
  insert into public.subscriptions (member_id)
  values (v_member.id)
  on conflict (member_id) do update
    set submissions = public.subscriptions.submissions + 1,
        status = case when public.subscriptions.status = 'stopped' then 'pending' else public.subscriptions.status end,
        applied_at = case when public.subscriptions.status = 'stopped' then now() else public.subscriptions.applied_at end,
        updated_at = now()
  returning * into v_row;
  return public._subscription_json(v_row);
end;
$$;

-- お客様：いまの状態（申請していなければ none）
create or replace function public.subscription_status(p_token uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
  v_row public.subscriptions;
begin
  v_member := public._session_member(p_token);
  select * into v_row from public.subscriptions where member_id = v_member.id;
  if not found then
    return jsonb_build_object('status', 'none');
  end if;
  return public._subscription_json(v_row);
end;
$$;

-- 管理者：申請の一覧
create or replace function public.admin_list_subscriptions(p_token uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
begin
  perform public._require_admin(p_token);
  return coalesce((
    select jsonb_agg(jsonb_build_object(
             'member_id', s.member_id,
             'account', m.account,
             'name', m.name,
             'member_status', m.status,
             'status', s.status,
             'applied_at', s.applied_at,
             'approved_at', s.approved_at,
             'stopped_at', s.stopped_at,
             'note', s.note,
             'submissions', s.submissions
           ) order by (s.status = 'pending') desc, s.applied_at desc)
      from public.subscriptions s
      join public.members m on m.id = s.member_id
  ), '[]'::jsonb);
end;
$$;

-- 管理者：承認（active）・停止（stopped）・審査中に戻す（pending）
create or replace function public.admin_set_subscription(p_token uuid, p_member_id uuid, p_status text, p_note text default null)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_row public.subscriptions;
begin
  perform public._require_admin(p_token);
  if p_status is null or p_status not in ('pending', 'active', 'stopped') then
    raise exception 'BAD_STATUS';
  end if;
  update public.subscriptions
     set approved_at = case when p_status = 'active' and status <> 'active' then now() else approved_at end,
         stopped_at = case when p_status = 'stopped' and status <> 'stopped' then now() else stopped_at end,
         status = p_status,
         note = coalesce(left(p_note, 200), note),
         updated_at = now()
   where member_id = p_member_id
   returning * into v_row;
  if not found then
    raise exception 'NOT_FOUND';
  end if;
  return public._subscription_json(v_row);
end;
$$;

-- 中継：つないでいる部屋（会員ID）のうち、サブスクの会員の利用許可。
-- 承認中（かつ会員が利用停止でない・鍵がある）なら、期限（UNIX 秒・UTC。24〜25 時間後）と署名。
-- それ以外は期限 0（＝EA は新規を止める）。サブスクでない会員は返さない（中継は何もしない）。
-- 許可は口座番号に結びついているので、ほかの口座の EA では使えない（匿名で呼べてよい）
create or replace function public.subscription_licenses(p_ids uuid[])
returns jsonb
language plpgsql
stable
security definer
set search_path = public, extensions
as $$
declare
  v_until bigint := (floor(extract(epoch from now()) / 3600)::bigint + 25) * 3600;
  v_has_secret boolean := public._subscription_secret() is not null;
begin
  return coalesce((
    select jsonb_agg(jsonb_build_object(
             'id', s.member_id,
             'status', s.status,
             'until', case when ok then v_until else 0 end,
             'sig', case when ok then public._subscription_sig(m.account, v_until) else 0 end
           ))
      from public.subscriptions s
      join public.members m on m.id = s.member_id
      cross join lateral (select (s.status = 'active' and m.status = 'active' and m.account is not null and v_has_secret) as ok) k
     where s.member_id = any(coalesce(p_ids, '{}'::uuid[]))
  ), '[]'::jsonb);
end;
$$;

revoke all on function public._subscription_secret() from public, anon, authenticated;
revoke all on function public._subscription_sig(bigint, bigint) from public, anon, authenticated;
revoke all on function public._subscription_json(public.subscriptions) from public, anon, authenticated;
grant execute on function public.subscription_apply(uuid) to anon, authenticated;
grant execute on function public.subscription_status(uuid) to anon, authenticated;
grant execute on function public.admin_list_subscriptions(uuid) to anon, authenticated;
grant execute on function public.admin_set_subscription(uuid, uuid, text, text) to anon, authenticated;
grant execute on function public.subscription_licenses(uuid[]) to anon, authenticated;
grant execute on function public.admin_set_plan_password(uuid, text, text) to anon, authenticated;
grant execute on function public.admin_set_member_plan(uuid, uuid, text) to anon, authenticated;
