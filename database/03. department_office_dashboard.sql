create extension if not exists pgcrypto;

create table if not exists public.business_permit_applications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  permit_id text not null unique,
  business_name text not null,
  status text not null default 'Submitted',
  progress text not null default 'Department review',
  submitted_id text not null,
  application_type text not null default 'New Application',
  application_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists business_permit_applications_user_created_idx
  on public.business_permit_applications (user_id, created_at desc);

alter table public.business_permit_applications enable row level security;

drop policy if exists "Applicants can read their own permit applications"
  on public.business_permit_applications;

create policy "Applicants can read their own permit applications"
  on public.business_permit_applications
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "Applicants can insert their own permit applications"
  on public.business_permit_applications;

create policy "Applicants can insert their own permit applications"
  on public.business_permit_applications
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "Applicants can update their own permit applications"
  on public.business_permit_applications;

create policy "Applicants can update their own permit applications"
  on public.business_permit_applications
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create table if not exists public.department_application_assignments (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.business_permit_applications(id) on delete cascade,
  department_key text not null,
  evaluation_status text not null default 'Pending'
    check (evaluation_status in ('Pending', 'Approved', 'Rejected')),
  remarks text,
  verification_status text not null default 'Unverified',
  inspection_date date,
  inspection_time time,
  inspection_remarks text,
  assigned_by uuid,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (application_id, department_key)
);

create index if not exists department_assignments_department_status_idx
  on public.department_application_assignments (department_key, evaluation_status, created_at desc)
  where deleted_at is null;

create table if not exists public.department_requirement_checklists (
  id uuid primary key default gen_random_uuid(),
  department_key text not null,
  title text not null,
  description text,
  is_required boolean not null default true,
  status text not null default 'Draft' check (status in ('Draft', 'Active')),
  created_by uuid,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists department_requirements_department_idx
  on public.department_requirement_checklists (department_key, created_at desc)
  where deleted_at is null;

create table if not exists public.department_inspections (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.business_permit_applications(id) on delete cascade,
  department_key text not null,
  scheduled_date date not null,
  scheduled_time time not null,
  remarks text,
  status text not null default 'Draft' check (status in ('Draft', 'Scheduled', 'Completed', 'Cancelled')),
  created_by uuid,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists department_inspections_department_idx
  on public.department_inspections (department_key, scheduled_date desc)
  where deleted_at is null;

create table if not exists public.department_remarks (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.business_permit_applications(id) on delete cascade,
  department_key text not null,
  remark text not null,
  status text not null default 'Draft' check (status in ('Draft', 'Submitted')),
  created_by uuid,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists department_remarks_department_idx
  on public.department_remarks (department_key, created_at desc)
  where deleted_at is null;

create table if not exists public.department_verifications (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.business_permit_applications(id) on delete cascade,
  department_key text not null,
  requirement_id uuid references public.department_requirement_checklists(id) on delete set null,
  verification_status text not null default 'Pending'
    check (verification_status in ('Pending', 'Verified', 'Rejected')),
  remarks text,
  created_by uuid,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists department_verifications_department_idx
  on public.department_verifications (department_key, created_at desc)
  where deleted_at is null;

create table if not exists public.department_reports (
  id uuid primary key default gen_random_uuid(),
  department_key text not null,
  applicant_name text not null,
  business_name text not null,
  report_type text not null,
  report_date date not null default current_date,
  status text not null default 'Pending'
    check (status in ('Completed', 'Approved', 'Pending', 'For Revision', 'Draft')),
  remarks text,
  created_by uuid,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists department_reports_department_idx
  on public.department_reports (department_key, report_date desc, created_at desc)
  where deleted_at is null;

create table if not exists public.department_settings (
  id uuid primary key default gen_random_uuid(),
  department_key text not null unique,
  profile_settings jsonb not null default '{}'::jsonb,
  office_information jsonb not null default '{}'::jsonb,
  notification_settings jsonb not null default '{}'::jsonb,
  inspection_settings jsonb not null default '{}'::jsonb,
  report_settings jsonb not null default '{}'::jsonb,
  security_settings jsonb not null default '{}'::jsonb,
  created_by uuid,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists department_settings_department_idx
  on public.department_settings (department_key)
  where deleted_at is null;

alter table public.department_application_assignments enable row level security;
alter table public.department_requirement_checklists enable row level security;
alter table public.department_inspections enable row level security;
alter table public.department_remarks enable row level security;
alter table public.department_verifications enable row level security;
alter table public.department_reports enable row level security;
alter table public.department_settings enable row level security;

create or replace function public.set_department_office_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_department_assignments_updated_at on public.department_application_assignments;
create trigger set_department_assignments_updated_at
before update on public.department_application_assignments
for each row execute procedure public.set_department_office_updated_at();

drop trigger if exists set_department_requirements_updated_at on public.department_requirement_checklists;
create trigger set_department_requirements_updated_at
before update on public.department_requirement_checklists
for each row execute procedure public.set_department_office_updated_at();

drop trigger if exists set_department_inspections_updated_at on public.department_inspections;
create trigger set_department_inspections_updated_at
before update on public.department_inspections
for each row execute procedure public.set_department_office_updated_at();

drop trigger if exists set_department_remarks_updated_at on public.department_remarks;
create trigger set_department_remarks_updated_at
before update on public.department_remarks
for each row execute procedure public.set_department_office_updated_at();

drop trigger if exists set_department_verifications_updated_at on public.department_verifications;
create trigger set_department_verifications_updated_at
before update on public.department_verifications
for each row execute procedure public.set_department_office_updated_at();

drop trigger if exists set_department_reports_updated_at on public.department_reports;
create trigger set_department_reports_updated_at
before update on public.department_reports
for each row execute procedure public.set_department_office_updated_at();

drop trigger if exists set_department_settings_updated_at on public.department_settings;
create trigger set_department_settings_updated_at
before update on public.department_settings
for each row execute procedure public.set_department_office_updated_at();
