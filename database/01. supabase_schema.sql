create extension if not exists pgcrypto;

create table if not exists public.applicants (
  id uuid primary key default gen_random_uuid(),
  user_id uuid unique,
  email text not null,
  first_name text not null,
  first_name_raw text not null,
  last_name text not null,
  middle_name text,
  suffix text,
  address_region text,
  address_province text,
  address_city text,
  address_barangay text,
  address_street text,
  postal_code text,
  contact_number text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.applicants enable row level security;

create or replace function public.handle_new_applicant()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.applicants (
    user_id,
    email,
    first_name,
    first_name_raw,
    last_name,
    middle_name,
    suffix,
    address_region,
    address_province,
    address_city,
    address_barangay,
    address_street,
    postal_code,
    contact_number
  )
  values (
    new.id,
    new.email,
    coalesce(new.raw_user_meta_data->>'first_name', ''),
    coalesce(new.raw_user_meta_data->>'first_name', ''),
    coalesce(new.raw_user_meta_data->>'last_name', ''),
    nullif(new.raw_user_meta_data->>'middle_name', ''),
    nullif(new.raw_user_meta_data->>'suffix', ''),
    nullif(new.raw_user_meta_data->>'address_region', ''),
    nullif(new.raw_user_meta_data->>'address_province', ''),
    nullif(new.raw_user_meta_data->>'address_city', ''),
    nullif(new.raw_user_meta_data->>'address_barangay', ''),
    nullif(new.raw_user_meta_data->>'address_street', ''),
    nullif(new.raw_user_meta_data->>'postal_code', ''),
    nullif(new.raw_user_meta_data->>'contact_number', '')
  )
  on conflict (user_id) do update set
    email = excluded.email,
    first_name = excluded.first_name,
    first_name_raw = excluded.first_name_raw,
    last_name = excluded.last_name,
    middle_name = excluded.middle_name,
    suffix = excluded.suffix,
    address_region = excluded.address_region,
    address_province = excluded.address_province,
    address_city = excluded.address_city,
    address_barangay = excluded.address_barangay,
    address_street = excluded.address_street,
    postal_code = excluded.postal_code,
    contact_number = excluded.contact_number,
    updated_at = now();

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_applicant();

create policy "Applicants can read their own row"
  on public.applicants
  for select
  using (auth.uid() = user_id);

create policy "Applicants can insert their own row"
  on public.applicants
  for insert
  with check (auth.uid() = user_id);

create policy "Applicants can update their own row"
  on public.applicants
  for update
  using (auth.uid() = user_id);

create table if not exists public.business_permit_applications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  permit_id text not null unique,
  business_name text not null,
  status text not null default 'Submitted',
  progress text not null default 'Review complete',
  submitted_id text not null,
  application_type text not null default 'New Application',
  application_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists business_permit_applications_user_created_idx
  on public.business_permit_applications (user_id, created_at desc);

alter table public.business_permit_applications enable row level security;

create policy "Applicants can read their own permit applications"
  on public.business_permit_applications
  for select
  using (auth.uid() = user_id);

create policy "Applicants can insert their own permit applications"
  on public.business_permit_applications
  for insert
  with check (auth.uid() = user_id);

create policy "Applicants can update their own permit applications"
  on public.business_permit_applications
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

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

create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid,
  actor_email text,
  actor_role text,
  action text not null,
  entity_type text,
  entity_id text,
  details jsonb not null default '{}'::jsonb,
  ip_address text,
  user_agent text,
  created_at timestamptz not null default now()
);

create index if not exists audit_logs_created_idx
  on public.audit_logs (created_at desc);

create index if not exists audit_logs_actor_created_idx
  on public.audit_logs (actor_user_id, created_at desc);

alter table public.audit_logs enable row level security;

create or replace function public.handle_new_user_audit_log()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.audit_logs (
    actor_user_id,
    actor_email,
    actor_role,
    action,
    entity_type,
    entity_id,
    details
  )
  values (
    new.id,
    new.email,
    coalesce(new.raw_app_meta_data->>'role', 'user'),
    'account_created',
    'user',
    new.id::text,
    jsonb_build_object('email', new.email)
  );

  return new;
end;
$$;

drop trigger if exists on_auth_user_created_audit_log on auth.users;

create trigger on_auth_user_created_audit_log
after insert on auth.users
for each row execute procedure public.handle_new_user_audit_log();
