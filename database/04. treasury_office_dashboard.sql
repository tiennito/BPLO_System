create extension if not exists pgcrypto;

create table if not exists public.treasury_records (
  id uuid primary key default gen_random_uuid(),
  application_no text not null,
  or_no text,
  applicant text not null,
  business_name text not null,
  amount numeric(14, 2) not null default 0,
  step text not null default 'Assessment',
  status text not null default 'Pending'
    check (status in ('Paid', 'Pending', 'Ready', 'Generated', 'Not Generated', 'Accepted')),
  current_step text not null default 'Assessment',
  record_type text not null default 'payment',
  transaction_date date not null default current_date,
  remarks text,
  created_by uuid,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists treasury_records_created_idx
  on public.treasury_records (created_at desc)
  where deleted_at is null;

create index if not exists treasury_records_status_idx
  on public.treasury_records (status, current_step)
  where deleted_at is null;

alter table public.treasury_records enable row level security;

create or replace function public.set_treasury_records_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_treasury_records_updated_at on public.treasury_records;

create trigger set_treasury_records_updated_at
before update on public.treasury_records
for each row execute procedure public.set_treasury_records_updated_at();
