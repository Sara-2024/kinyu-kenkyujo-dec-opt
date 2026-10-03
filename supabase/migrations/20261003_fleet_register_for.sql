-- ════════════════════════════════════════════════════════════
-- 一斉制御: 管理者が「つながっている口座」を登録簿に加える
--
-- 連携済みの PC は中継に部屋（会員ID）として見えているので、お客様に
-- /fleet/join を開いてもらわなくても、管理者が一覧から登録できるようにする。
-- パスワードは預からない（空で入れる。あとで本人が /fleet/join で入れれば上書き）。
-- ════════════════════════════════════════════════════════════
create or replace function public.fleet_register_for(
  p_token uuid,
  p_member_id uuid,
  p_account bigint,
  p_server text,
  p_password text default ''
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_member public.members;
  v_server text := trim(coalesce(p_server, ''));
  v_row public.fleet_accounts;
begin
  perform public._require_admin(p_token);
  select * into v_member from public.members where id = p_member_id;
  if v_member.id is null then
    raise exception 'NOT_FOUND';
  end if;
  if p_account is null or p_account <= 0 then
    raise exception 'BAD_ACCOUNT';
  end if;
  if v_server = '' or length(v_server) > 80 then
    raise exception 'BAD_SERVER';
  end if;

  insert into public.fleet_accounts (member_id, account, server, password_enc)
  values (
    v_member.id,
    p_account,
    v_server,
    extensions.pgp_sym_encrypt(coalesce(p_password, ''), public._fleet_key())
  )
  on conflict (account, server) do update
    set member_id = excluded.member_id,
        password_enc = case
          when coalesce(p_password, '') = '' then public.fleet_accounts.password_enc
          else excluded.password_enc
        end,
        updated_at = now()
  returning * into v_row;
  return public._fleet_row_json(v_row, v_member.email);
end;
$$;

grant execute on function public.fleet_register_for(uuid, uuid, bigint, text, text) to anon, authenticated;
