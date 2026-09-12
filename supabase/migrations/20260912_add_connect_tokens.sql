-- 2026-09-12  MT5連携のワンタイム合図を足す（AI Trader Connect）
--
-- 既存の環境へ、これだけを流す。
--   Supabase ダッシュボード → SQL Editor に貼り付けて実行
--   （schema.sql を丸ごと流し直す必要はない）
--
-- 既存のテーブル・関数・権限には一切触らない。追加だけ。
-- 二度流しても壊れない（if not exists / create or replace）。
--
-- 元に戻すとき:
--   drop function if exists public.connect_token_redeem(text);
--   drop function if exists public.connect_token_issue(uuid);
--   drop table if exists public.connect_tokens;

-- ════════════════════════════════════════════════════════════
-- MT5連携のワンタイム合図（AI Trader Connect）
--
-- サイトの「MT5と連携する」を押したときだけ発行する、短命の合図。
-- これを aitrader://connect?token=... でお客様のPCのアプリへ渡す。
--
--   ・会員IDそのものは URL に載せない
--   ・推測できない長さの乱数
--   ・数分で切れる
--   ・一度使ったら無効
--   ・アプリ単体では作れない（ログイン中のセッションが要る）
--
-- 既存のテーブルや関数は変更していない。ここから下は追加だけ。
-- ════════════════════════════════════════════════════════════
create table if not exists public.connect_tokens (
  token text primary key,
  member_id uuid not null references public.members (id) on delete cascade,
  expires_at timestamptz not null,
  used_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists connect_tokens_member_idx on public.connect_tokens (member_id);
create index if not exists connect_tokens_expires_idx on public.connect_tokens (expires_at);

alter table public.connect_tokens enable row level security;

-- 合図を発行する。ログイン中の会員だけが、自分のぶんを作れる。
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
  values (v_token, v_member.id, now() + interval '5 minutes');

  return jsonb_build_object('token', v_token, 'expires_in', 300);
end;
$$;

-- 合図を使う。サイトのサーバー関数（/api/connect）からだけ呼ぶ。
-- 正しければ会員IDを返し、その場で使用済みにする（二度は使えない）。
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

  return jsonb_build_object('member_id', v_member.id, 'can_trade', v_member.can_trade);
end;
$$;

grant execute on function public.connect_token_issue(uuid) to anon, authenticated;
grant execute on function public.connect_token_redeem(text) to anon, authenticated;
