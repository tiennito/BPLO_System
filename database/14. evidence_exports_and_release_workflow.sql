create table if not exists public.department_evidence (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  department_id uuid references public.departments(id) on delete set null,
  department_key text not null,
  uploaded_by uuid not null,
  file_name text not null,
  file_url text not null,
  remarks text,
  deleted_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists department_evidence_application_idx
  on public.department_evidence (application_id, created_at desc)
  where deleted_at is null;

create index if not exists department_evidence_department_idx
  on public.department_evidence (department_key, created_at desc)
  where deleted_at is null;

alter table public.department_evidence enable row level security;

grant select, insert, update on public.department_evidence to authenticated;

insert into storage.buckets (id, name, public)
values ('department-evidence', 'department-evidence', false)
on conflict (id) do nothing;

alter table public.business_permits
add column if not exists released_by uuid;
