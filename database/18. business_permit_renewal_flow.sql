-- Business permit renewal form workflow extensions.
-- This migration is additive: historical permits, payments, receipts, and approved
-- applications remain immutable reference records.

alter table public.applications
  add column if not exists previous_application_id uuid,
  add column if not exists previous_permit_id uuid,
  add column if not exists renewal_application_number text,
  add column if not exists renewal_baseline jsonb not null default '{}'::jsonb,
  add column if not exists renewal_change_confirmed_at timestamptz;

alter table public.applications
  drop constraint if exists applications_previous_application_id_fkey;
alter table public.applications
  add constraint applications_previous_application_id_fkey
  foreign key (previous_application_id) references public.applications(id) on delete restrict;

alter table public.applications
  drop constraint if exists applications_previous_permit_id_fkey;
alter table public.applications
  add constraint applications_previous_permit_id_fkey
  foreign key (previous_permit_id) references public.business_permits(id) on delete restrict;

update public.applications
set previous_permit_id = coalesce(previous_permit_id, source_permit_id)
where application_type = 'renewal'
  and source_permit_id is not null;

create unique index if not exists applications_renewal_number_idx
  on public.applications (renewal_application_number)
  where renewal_application_number is not null;

create index if not exists applications_previous_reference_idx
  on public.applications (previous_permit_id, previous_application_id)
  where application_type = 'renewal';

create table if not exists public.renewal_change_logs (
  id uuid primary key default gen_random_uuid(),
  renewal_application_id uuid not null references public.applications(id) on delete cascade,
  field_name text not null,
  field_label text not null,
  previous_value text,
  new_value text,
  changed_by uuid not null,
  changed_at timestamptz not null default now(),
  confirmed_at timestamptz,
  unique (renewal_application_id, field_name)
);

create index if not exists renewal_change_logs_application_idx
  on public.renewal_change_logs (renewal_application_id, changed_at desc);

alter table public.application_documents
  add column if not exists original_filename text,
  add column if not exists stored_filename text,
  add column if not exists mime_type text,
  add column if not exists file_size bigint,
  add column if not exists document_year integer,
  add column if not exists issue_date date,
  add column if not exists expiration_date date,
  add column if not exists replaced_document_id uuid,
  add column if not exists removed_at timestamptz,
  add column if not exists reviewed_by uuid,
  add column if not exists reviewed_at timestamptz,
  add column if not exists reviewer_remarks text;

alter table public.application_documents
  drop constraint if exists application_documents_replaced_document_id_fkey;
alter table public.application_documents
  add constraint application_documents_replaced_document_id_fkey
  foreign key (replaced_document_id) references public.application_documents(id) on delete set null;

alter table public.renewal_requirements
  add column if not exists requirement_name text,
  add column if not exists description text,
  add column if not exists application_type text not null default 'renewal',
  add column if not exists business_classification_id uuid,
  add column if not exists responsible_department_id uuid,
  add column if not exists is_required boolean not null default true,
  add column if not exists allowed_file_types text[] not null default array['pdf','png','jpg','jpeg'],
  add column if not exists max_file_size integer not null default 5242880,
  add column if not exists number_of_copies integer not null default 1,
  add column if not exists validity_required boolean not null default false,
  add column if not exists previous_document_may_be_reused boolean not null default false,
  add column if not exists new_upload_required boolean not null default true,
  add column if not exists display_order integer not null default 100,
  add column if not exists deleted_at timestamptz;

alter table public.renewal_requirements
  drop constraint if exists renewal_requirements_application_type_check;
alter table public.renewal_requirements
  add constraint renewal_requirements_application_type_check
  check (application_type = 'renewal');

alter table public.renewal_requirements
  drop constraint if exists renewal_requirements_business_classification_id_fkey;
alter table public.renewal_requirements
  add constraint renewal_requirements_business_classification_id_fkey
  foreign key (business_classification_id) references public.business_classifications(id) on delete set null;

alter table public.renewal_requirements
  drop constraint if exists renewal_requirements_responsible_department_id_fkey;
alter table public.renewal_requirements
  add constraint renewal_requirements_responsible_department_id_fkey
  foreign key (responsible_department_id) references public.departments(id) on delete set null;

create index if not exists renewal_requirements_active_lookup_idx
  on public.renewal_requirements (permit_id, business_classification_id, is_active, display_order)
  where deleted_at is null;

alter table public.renewal_change_logs enable row level security;

drop policy if exists "Applicants can view own renewal change logs" on public.renewal_change_logs;
create policy "Applicants can view own renewal change logs"
on public.renewal_change_logs for select to authenticated
using (
  exists (
    select 1 from public.applications
    where applications.id = renewal_change_logs.renewal_application_id
      and applications.applicant_id = (select auth.uid())
  )
);

grant select on public.renewal_change_logs to authenticated;

notify pgrst, 'reload schema';
