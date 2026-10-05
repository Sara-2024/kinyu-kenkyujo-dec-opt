-- ════════════════════════════════════════════════════════════
-- お使いのパソコン（Windows / Mac）の記録
--
-- Mac ルートを足したので、誰がどちらを使っているかを運営が見られるようにする。
-- 記録するのはサイト（初期設定で選んだとき・始めたとき）。管理者画面と一斉制御に出す。
-- ════════════════════════════════════════════════════════════
alter table public.member_connections add column if not exists platform text;

create or replace function public.member_platform_set(p_token uuid, p_platform text)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
begin
  v_member := public._session_member(p_token);
  if p_platform not in ('windows', 'mac') then
    raise exception 'BAD_PLATFORM';
  end if;
  insert into public.member_connections (member_id, email, platform)
  values (v_member.id, v_member.email, p_platform)
  on conflict (member_id) do update
    set platform = excluded.platform,
        updated_at = now();
  return jsonb_build_object('ok', true, 'platform', p_platform);
end;
$$;

-- 管理者の会員一覧に OS を足す
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
        c.platform,
        c.updated_at as connected_at
      from public.members m
      left join public.member_connections c on c.member_id = m.id
    ) r
  ), '[]'::jsonb);
end;
$$;

-- 一斉制御の一覧にも OS を足す
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
    select jsonb_agg((public._fleet_row_json(r, m.email) || jsonb_build_object('platform', c.platform)) order by r.created_at)
    from public.fleet_accounts r
    join public.members m on m.id = r.member_id
    left join public.member_connections c on c.member_id = r.member_id
  ), '[]'::jsonb);
end;
$$;

grant execute on function public.member_platform_set(uuid, text) to anon, authenticated;
