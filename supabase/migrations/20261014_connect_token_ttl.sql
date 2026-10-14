-- 合図（connect_tokens）の期限を 5 分 → 24 時間にする。
-- ロビーは Windows 用パスポートを「DreamlandPassport-<合図>.exe」という名前で配り、
-- お客様が「開くだけ」で連携できるようにした。ダウンロードしてから開くまでに
-- 時間が空くことがふつうにあるので、期限を延ばす（合図は 32 バイトの乱数・使い捨てのまま）。
-- Supabase ダッシュボード → SQL Editor に貼り付けて実行。
create or replace function public.connect_token_issue(p_token uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
  v_token text;
begin
  v_member := public._session_member(p_token);

  -- 古いものを片づける（切れたもの・使ったもの・この会員の未使用ぶん）
  delete from public.connect_tokens
   where expires_at < now()
      or used_at is not null
      or member_id = v_member.id;

  v_token := encode(extensions.gen_random_bytes(32), 'hex');
  insert into public.connect_tokens (token, member_id, expires_at)
  values (v_token, v_member.id, now() + interval '24 hours');

  return jsonb_build_object('token', v_token, 'expires_in', 86400);
end;
$$;
