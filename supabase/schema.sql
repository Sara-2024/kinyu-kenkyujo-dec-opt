-- Supabase ダッシュボード → SQL Editor で実行
-- 接続フローで入力されたメール（リード）を保存する

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  source text not null default 'algo-connect',
  created_at timestamptz not null default now()
);

create index if not exists leads_created_at_idx on public.leads (created_at desc);
create index if not exists leads_email_idx on public.leads (email);

alter table public.leads enable row level security;

-- 匿名（ブラウザ）からの登録のみ許可。参照・更新・削除はダッシュボード側
create policy "anon can insert leads"
  on public.leads
  for insert
  to anon
  with check (true);
