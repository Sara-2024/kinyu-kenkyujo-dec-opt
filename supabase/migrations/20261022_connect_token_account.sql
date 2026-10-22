-- ════════════════════════════════════════════════════════════
-- 合図を確かめる connect_token_redeem が、会員の口座番号（account）も返す
--
-- パスポートは、合図の URL に口座番号（account=）が付いていれば、それで
-- 「どの口座の手続きか」を決める。ダウンロードしたファイルの名前から拾った合図には
-- 口座番号が付かないので、ロイヤルファーストクラスの 2 つ目の口座でも
-- 「1 つ目を替える」に落ちて 1 年版が置かれた（口座 198676996 で起きた）。
-- 会員 ＝ 口座番号なので、合図を確かめた返事に口座番号を載せれば足りる。
-- 会員本人の合図（使い捨て・5 分〜24 時間）でしか返らないので、口座番号は漏れない。
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
  -- account はパスポートが「どの口座の手続きか」を決めるのに使う（URL に口座番号が無いとき）
  return jsonb_build_object(
    'member_id', v_member.id,
    'can_trade', v_member.can_trade,
    'plan', v_member.plan,
    'account', v_member.account
  );
end;
$$;
