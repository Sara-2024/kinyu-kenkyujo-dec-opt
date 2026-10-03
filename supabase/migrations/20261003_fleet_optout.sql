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
