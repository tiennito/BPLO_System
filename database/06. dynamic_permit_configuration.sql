create extension if not exists "pgcrypto";

create table if not exists public.permits (
  id uuid primary key default gen_random_uuid(),
  permit_name text not null,
  permit_code text not null unique,
  category text not null,
  description text,
  status text not null default 'Draft' check (status in ('Draft', 'Published', 'Archived', 'Active', 'Inactive')),
  processing_fee numeric(12, 2),
  applicant_notes text,
  created_by uuid references auth.users(id) on delete set null,
  updated_by uuid references auth.users(id) on delete set null,
  last_saved_at timestamptz default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.permits
  add column if not exists created_by uuid,
  add column if not exists updated_by uuid,
  add column if not exists last_saved_at timestamptz;

alter table public.permits
  alter column last_saved_at set default now();

alter table public.permits
  drop constraint if exists permits_created_by_fkey,
  drop constraint if exists permits_updated_by_fkey;

alter table public.permits
  add constraint permits_created_by_fkey foreign key (created_by) references auth.users(id) on delete set null,
  add constraint permits_updated_by_fkey foreign key (updated_by) references auth.users(id) on delete set null;

alter table public.permits
  drop constraint if exists permits_status_check;

alter table public.permits
  add constraint permits_status_check
  check (status in ('Draft', 'Published', 'Archived', 'Active', 'Inactive'));

create table if not exists public.permit_documents (
  id uuid primary key default gen_random_uuid(),
  permit_id uuid not null references public.permits(id) on delete cascade,
  document_name text not null,
  short_description text,
  requirement_type text not null check (requirement_type in ('Required', 'Optional')),
  accepted_file_types text not null,
  max_file_size text,
  upload_required boolean not null default true,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.permit_required_offices (
  id uuid primary key default gen_random_uuid(),
  permit_id uuid not null references public.permits(id) on delete cascade,
  office_id uuid not null references public.departments(id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (permit_id, office_id)
);

create table if not exists public.applications (
  id uuid primary key default gen_random_uuid(),
  permit_id uuid not null references public.permits(id) on delete restrict,
  applicant_id uuid not null,
  status text not null default 'Requirements',
  permit_snapshot jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.application_documents (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  permit_document_id uuid not null references public.permit_documents(id) on delete restrict,
  document_snapshot jsonb not null default '{}'::jsonb,
  file_url text,
  file_name text,
  upload_status text not null default 'Pending' check (upload_status in ('Pending', 'Uploaded', 'Removed', 'Rejected')),
  remarks text,
  uploaded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (application_id, permit_document_id)
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists permits_set_updated_at on public.permits;
create trigger permits_set_updated_at
before update on public.permits
for each row execute function public.set_updated_at();

drop trigger if exists permit_documents_set_updated_at on public.permit_documents;
create trigger permit_documents_set_updated_at
before update on public.permit_documents
for each row execute function public.set_updated_at();

drop trigger if exists permit_required_offices_set_updated_at on public.permit_required_offices;
create trigger permit_required_offices_set_updated_at
before update on public.permit_required_offices
for each row execute function public.set_updated_at();

drop trigger if exists applications_set_updated_at on public.applications;
create trigger applications_set_updated_at
before update on public.applications
for each row execute function public.set_updated_at();

drop trigger if exists application_documents_set_updated_at on public.application_documents;
create trigger application_documents_set_updated_at
before update on public.application_documents
for each row execute function public.set_updated_at();

alter table public.permits enable row level security;
alter table public.permit_documents enable row level security;
alter table public.permit_required_offices enable row level security;
alter table public.applications enable row level security;
alter table public.application_documents enable row level security;

drop policy if exists "Applicants can view active permits" on public.permits;
create policy "Applicants can view active permits"
on public.permits for select
to authenticated
using (status in ('Published', 'Active'));

drop policy if exists "Applicants can view active permit documents" on public.permit_documents;
create policy "Applicants can view active permit documents"
on public.permit_documents for select
to authenticated
using (
  exists (
    select 1 from public.permits
    where permits.id = permit_documents.permit_id
      and permits.status in ('Published', 'Active')
  )
);

drop policy if exists "Applicants can view active permit offices" on public.permit_required_offices;
create policy "Applicants can view active permit offices"
on public.permit_required_offices for select
to authenticated
using (
  exists (
    select 1 from public.permits
    where permits.id = permit_required_offices.permit_id
      and permits.status in ('Published', 'Active')
  )
);

drop policy if exists "Applicants can view own applications" on public.applications;
create policy "Applicants can view own applications"
on public.applications for select
to authenticated
using (applicant_id = (select auth.uid()));

drop policy if exists "Applicants can create own applications" on public.applications;
create policy "Applicants can create own applications"
on public.applications for insert
to authenticated
with check (applicant_id = (select auth.uid()));

drop policy if exists "Applicants can update own applications" on public.applications;
create policy "Applicants can update own applications"
on public.applications for update
to authenticated
using (applicant_id = (select auth.uid()))
with check (applicant_id = (select auth.uid()));

drop policy if exists "Applicants can view own application documents" on public.application_documents;
create policy "Applicants can view own application documents"
on public.application_documents for select
to authenticated
using (
  exists (
    select 1 from public.applications
    where applications.id = application_documents.application_id
      and applications.applicant_id = (select auth.uid())
  )
);

drop policy if exists "Applicants can create own application documents" on public.application_documents;
create policy "Applicants can create own application documents"
on public.application_documents for insert
to authenticated
with check (
  exists (
    select 1 from public.applications
    where applications.id = application_documents.application_id
      and applications.applicant_id = (select auth.uid())
  )
);

drop policy if exists "Applicants can update own application documents" on public.application_documents;
create policy "Applicants can update own application documents"
on public.application_documents for update
to authenticated
using (
  exists (
    select 1 from public.applications
    where applications.id = application_documents.application_id
      and applications.applicant_id = (select auth.uid())
  )
)
with check (
  exists (
    select 1 from public.applications
    where applications.id = application_documents.application_id
      and applications.applicant_id = (select auth.uid())
  )
);

grant select on public.permits, public.permit_documents, public.permit_required_offices to authenticated;
grant select, insert, update on public.applications, public.application_documents to authenticated;

insert into storage.buckets (id, name, public)
values ('application-documents', 'application-documents', false)
on conflict (id) do nothing;

drop policy if exists "Applicants can upload own application documents" on storage.objects;
create policy "Applicants can upload own application documents"
on storage.objects for insert
to authenticated
with check (
  bucket_id = 'application-documents'
  and owner = (select auth.uid())
);

drop policy if exists "Applicants can view own application documents" on storage.objects;
create policy "Applicants can view own application documents"
on storage.objects for select
to authenticated
using (
  bucket_id = 'application-documents'
  and owner = (select auth.uid())
);

drop policy if exists "Applicants can update own application documents" on storage.objects;
create policy "Applicants can update own application documents"
on storage.objects for update
to authenticated
using (
  bucket_id = 'application-documents'
  and owner = (select auth.uid())
)
with check (
  bucket_id = 'application-documents'
  and owner = (select auth.uid())
);

notify pgrst, 'reload schema';
