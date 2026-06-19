create extension if not exists pgcrypto;

create table if not exists public.departments (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  description text,
  status text not null default 'Active' check (status in ('Active', 'Inactive')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists departments_created_idx
  on public.departments (created_at desc);

alter table public.departments enable row level security;

create or replace function public.set_departments_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_departments_updated_at on public.departments;

create trigger set_departments_updated_at
before update on public.departments
for each row execute procedure public.set_departments_updated_at();
