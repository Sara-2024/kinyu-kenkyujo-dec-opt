-- ════════════════════════════════════════════════════════════
-- 2026-10-17: プランで口座の数を縛る
--   ・合図を確かめる connect_token_redeem が会員のプラン（plan）も返す。
--     パスポートはこれを見て、ロイヤルファーストクラス（crystal）のときだけ
--     同じ PC に 2 つ目の口座（2 本目のブリッジ）を足す。それ以外は 1 本目を切り替える。
--   ・管理者が会員のプランを直せる admin_set_member_plan（プランの合言葉の仕組みより前に
--     登録した会員は plan が空なので、ロイヤルの方はここで直す）。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行。
-- ════════════════════════════════════════════════════════════
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

  -- plan はパスポートが「2 つ目の口座を足してよいか（crystal か）」を決めるのに使う
  return jsonb_build_object('member_id', v_member.id, 'can_trade', v_member.can_trade, 'plan', v_member.plan);
end;
$$;

-- 管理者: 会員のプランを直す（first / crystal / premium）
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
  if p_plan is null or p_plan not in ('first', 'crystal', 'premium') then
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

grant execute on function public.connect_token_redeem(text) to anon, authenticated;
grant execute on function public.admin_set_member_plan(uuid, uuid, text) to anon, authenticated;
