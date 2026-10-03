-- ════════════════════════════════════════════════════════════
-- 管理者画面: 会員の削除と、BAN した会員のブリッジを中継が切るための問い合わせ
--
-- ・admin_delete_member … 会員を消す（セッション・連携・一斉制御の記録も一緒に消える）。
--   自分自身と、最後の管理者は消せない。
-- ・bridges_blocked … 渡した会員IDのうち「利用できない」もの（停止中・存在しない）を返す。
--   中継がブリッジの接続時と、つないでいるあいだ定期的に呼ぶ。
--   会員IDは推測できない乱数なので、匿名で呼べても分かるのは「止められているか」だけ。
-- ════════════════════════════════════════════════════════════
create or replace function public.admin_delete_member(p_token uuid, p_member_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_admin public.members;
  v_target public.members;
  v_admins int;
begin
  v_admin := public._require_admin(p_token);
  select * into v_target from public.members where id = p_member_id;
  if not found then
    raise exception 'NOT_FOUND';
  end if;
  if v_target.id = v_admin.id then
    raise exception 'SELF_DELETE';
  end if;
  if v_target.role = 'admin' then
    select count(*) into v_admins from public.members where role = 'admin' and status = 'active';
    if v_admins <= 1 then
      raise exception 'LAST_ADMIN';
    end if;
  end if;
  delete from public.members where id = p_member_id;
  return jsonb_build_object('ok', true, 'id', p_member_id);
end;
$$;

create or replace function public.bridges_blocked(p_ids uuid[])
returns jsonb
language sql
stable
security definer
set search_path = public, extensions
as $$
  select coalesce(jsonb_agg(id), '[]'::jsonb)
  from unnest(coalesce(p_ids, '{}'::uuid[])) as t(id)
  where not exists (
    select 1 from public.members m where m.id = t.id and m.status = 'active'
  );
$$;

grant execute on function public.admin_delete_member(uuid, uuid) to anon, authenticated;
grant execute on function public.bridges_blocked(uuid[]) to anon, authenticated;
