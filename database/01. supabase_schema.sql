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
