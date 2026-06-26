create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null unique references auth.users(id) on delete cascade,
  first_name text not null default '',
  middle_name text not null default '',
  last_name text not null default '',
  suffix text not null default '',
  email text not null unique,
  contact_number text not null default '',
  role text not null check (role in ('super_admin', 'bplo_admin', 'department_office', 'treasury', 'applicant')),
  department_id uuid references public.departments(id) on delete set null,
  department_key text,
  department_name text,
  status text not null default 'active' check (status in ('active', 'inactive', 'pending', 'disabled')),
  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists profiles_role_status_idx
  on public.profiles (role, status);

create index if not exists profiles_department_idx
  on public.profiles (department_id);

create unique index if not exists profiles_email_lower_unique_idx
  on public.profiles (lower(email));

alter table public.profiles enable row level security;

drop policy if exists "Users can read their own profile" on public.profiles;
create policy "Users can read their own profile"
  on public.profiles
  for select
  to authenticated
  using ((select auth.uid()) = auth_user_id);

grant select on public.profiles to authenticated;

create or replace function public.set_profiles_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
before update on public.profiles
for each row execute procedure public.set_profiles_updated_at();

insert into public.profiles (
  auth_user_id,
  first_name,
  middle_name,
  last_name,
  suffix,
  email,
  contact_number,
  role,
  department_id,
  department_key,
  department_name,
  status
)
select
  users.id,
  coalesce(users.raw_user_meta_data->>'first_name', ''),
  coalesce(users.raw_user_meta_data->>'middle_name', ''),
  coalesce(users.raw_user_meta_data->>'last_name', ''),
  coalesce(users.raw_user_meta_data->>'suffix', ''),
  lower(users.email),
  coalesce(users.raw_user_meta_data->>'contact_number', ''),
  case
    when lower(coalesce(users.raw_app_meta_data->>'role', users.raw_user_meta_data->>'role', 'applicant')) in ('super_admin') then 'super_admin'
    when lower(coalesce(users.raw_app_meta_data->>'role', users.raw_user_meta_data->>'role', 'applicant')) in ('admin', 'bplo_admin', 'administrator') then 'bplo_admin'
    when lower(coalesce(users.raw_app_meta_data->>'role', users.raw_user_meta_data->>'role', 'applicant')) in ('department', 'department_user', 'department_office', 'department_office_user') then 'department_office'
    when lower(coalesce(users.raw_app_meta_data->>'role', users.raw_user_meta_data->>'role', 'applicant')) in ('treasury', 'treasury_office', 'treasury_user') then 'treasury'
    else 'applicant'
  end,
  departments.id,
  nullif(users.raw_app_meta_data->>'department_key', ''),
  coalesce(nullif(users.raw_app_meta_data->>'department_name', ''), departments.name),
  case
    when users.banned_until is not null then 'disabled'
    when users.email_confirmed_at is null and users.confirmed_at is null then 'pending'
    else 'active'
  end
from auth.users users
left join public.departments departments
  on lower(departments.name) = lower(coalesce(users.raw_app_meta_data->>'department_name', users.raw_app_meta_data->>'department', ''))
where users.email is not null
on conflict (auth_user_id) do update set
  first_name = excluded.first_name,
  middle_name = excluded.middle_name,
  last_name = excluded.last_name,
  suffix = excluded.suffix,
  email = excluded.email,
  contact_number = excluded.contact_number,
  role = excluded.role,
  department_id = coalesce(public.profiles.department_id, excluded.department_id),
  department_key = coalesce(public.profiles.department_key, excluded.department_key),
  department_name = coalesce(public.profiles.department_name, excluded.department_name),
  status = excluded.status;
