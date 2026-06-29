alter table public.applications
add column if not exists business_info jsonb not null default '{}'::jsonb;

alter table public.applications
add column if not exists submitted_at timestamptz;

alter table public.applications
add column if not exists reviewed_at timestamptz;

alter table public.applications
add column if not exists progress text not null default 'Draft';

alter table public.applications
alter column status set default 'Draft';

create table if not exists public.application_status_history (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  status text not null,
  remarks text,
  created_by uuid,
  created_at timestamptz not null default now()
);

alter table public.application_status_history enable row level security;

drop policy if exists "Applicants can view own application history" on public.application_status_history;
create policy "Applicants can view own application history"
on public.application_status_history for select
to authenticated
using (
  exists (
    select 1 from public.applications
    where applications.id = application_status_history.application_id
      and applications.applicant_id = (select auth.uid())
  )
);

delete from public.department_application_assignments
where not exists (
  select 1 from public.applications
  where applications.id = department_application_assignments.application_id
);

delete from public.department_inspections
where not exists (
  select 1 from public.applications
  where applications.id = department_inspections.application_id
);

delete from public.department_remarks
where not exists (
  select 1 from public.applications
  where applications.id = department_remarks.application_id
);

delete from public.department_verifications
where not exists (
  select 1 from public.applications
  where applications.id = department_verifications.application_id
);

alter table public.department_application_assignments
drop constraint if exists department_application_assignments_application_id_fkey;

alter table public.department_application_assignments
add constraint department_application_assignments_application_id_fkey
foreign key (application_id) references public.applications(id) on delete cascade;

alter table public.department_inspections
drop constraint if exists department_inspections_application_id_fkey;

alter table public.department_inspections
add constraint department_inspections_application_id_fkey
foreign key (application_id) references public.applications(id) on delete cascade;

alter table public.department_remarks
drop constraint if exists department_remarks_application_id_fkey;

alter table public.department_remarks
add constraint department_remarks_application_id_fkey
foreign key (application_id) references public.applications(id) on delete cascade;

alter table public.department_verifications
drop constraint if exists department_verifications_application_id_fkey;

alter table public.department_verifications
add constraint department_verifications_application_id_fkey
foreign key (application_id) references public.applications(id) on delete cascade;

grant select on public.application_status_history to authenticated;
notify pgrst, 'reload schema';
