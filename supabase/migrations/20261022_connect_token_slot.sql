-- ════════════════════════════════════════════════════════════
-- 合図を確かめる connect_token_redeem が、何番目の口座か（slot）も返す
--
-- ロイヤルファーストクラスは口座を 2 つつなぐ。1 つ目は YumekkuEA-1年版、
-- 2 つ目は YumekkuEA1年版｜安定低月利ver。ロビーは口座の登録順で 2 つ目と出す。
-- パスポートはこれまで、この PC の state.json の 1 本目と違う口座だけを 2 つ目と
-- 見ていた。サイトでは 2 本目の口座 198676996 でも、その PC がそれを 1 本目と
-- 覚えていると 1 年版が置かれた。
--
-- 同じお名前・同じプラン（crystal）の会員を登録順に数えて、2 人目なら slot=2。
-- お名前が空のときは 1（数えられない）。ロビーが URL / 中継の合図に付ける
-- slot=2 のほうが先に来る場合は、パスポートはそちらを落とさない。
-- 追加だけ。既存の列・表は触らない。
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
  v_slot int := 1;
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

  -- ロイヤルの同じお名前で、この会員より先に登録した口座が居れば 2 つ目
  if v_member.plan = 'crystal' and nullif(trim(coalesce(v_member.name, '')), '') is not null then
    select 1 + count(*)::int into v_slot
      from public.members o
     where o.plan = 'crystal'
       and o.status = 'active'
       and o.id <> v_member.id
       and o.name = v_member.name
       and o.created_at < v_member.created_at;
    if v_slot is null then
      v_slot := 1;
    end if;
    if v_slot > 2 then
      v_slot := 2;
    end if;
  end if;

  -- plan はパスポートが「2 つ目の口座を足してよいか（crystal か）」を決めるのに使う
  -- account はパスポートが「どの口座の手続きか」を決めるのに使う（URL に口座番号が無いとき）
  -- slot は「何番目の口座か」。2 なら安定低月利ver を置く
  return jsonb_build_object(
    'member_id', v_member.id,
    'can_trade', v_member.can_trade,
    'plan', v_member.plan,
    'account', v_member.account,
    'slot', v_slot
  );
end;
$$;
