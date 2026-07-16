create extension if not exists "pgcrypto";

-- Calendar-year validity fields. The legacy issue_date/expiration_date columns are
-- retained for compatibility with the existing permit and reporting screens.
alter table public.business_permits
  add column if not exists permit_year integer,
  add column if not exists issued_date date,
  add column if not exists valid_until date,
  add column if not exists renewal_year integer,
  add column if not exists renewal_status text not null default 'not_open',
  add column if not exists renewed_at timestamptz;

update public.business_permits
set issued_date = coalesce(issued_date, released_at::date, issue_date),
    permit_year = coalesce(permit_year, extract(year from coalesce(issued_date, released_at::date, issue_date))::integer),
    valid_until = coalesce(
      valid_until,
      make_date(extract(year from coalesce(issued_date, released_at::date, issue_date))::integer, 12, 31)
    ),
    renewal_year = coalesce(
      renewal_year,
      extract(year from coalesce(issued_date, released_at::date, issue_date))::integer + 1
    )
where coalesce(issued_date, released_at::date, issue_date) is not null;

alter table public.business_permits
  drop constraint if exists business_permits_renewal_status_check;
alter table public.business_permits
  add constraint business_permits_renewal_status_check
  check (renewal_status in (
    'not_open', 'upcoming', 'open', 'draft', 'submitted', 'under_review',
    'for_payment', 'paid', 'renewed', 'late', 'closed'
  ));

create index if not exists business_permits_renewal_monitoring_idx
  on public.business_permits (renewal_year, renewal_status, valid_until);

alter table public.applications
  add column if not exists application_type text not null default 'new',
  add column if not exists permit_year integer,
  add column if not exists source_permit_id uuid,
  add column if not exists renewal_due_date date,
  add column if not exists original_renewal_due_date date,
  add column if not exists effective_renewal_due_date date,
  add column if not exists deadline_extension_id uuid,
  add column if not exists filed_at timestamptz,
  add column if not exists payment_completed_at timestamptz,
  add column if not exists is_late boolean not null default false;

alter table public.applications
  drop constraint if exists applications_source_permit_id_fkey;
alter table public.applications
  add constraint applications_source_permit_id_fkey
  foreign key (source_permit_id) references public.business_permits(id) on delete restrict;

update public.applications
set application_type = case
  when lower(coalesce(application_type, '')) in ('renewal', 're-newal', 'renew') then 'renewal'
  else 'new'
end;

alter table public.applications
  drop constraint if exists applications_application_type_check;
alter table public.applications
  add constraint applications_application_type_check
  check (application_type in ('new', 'renewal'));

create unique index if not exists applications_unique_source_renewal_year_idx
  on public.applications (source_permit_id, permit_year)
  where application_type = 'renewal' and source_permit_id is not null;

create index if not exists applications_renewal_monitoring_idx
  on public.applications (permit_year, is_late, status, filed_at desc)
  where application_type = 'renewal';

alter table public.application_documents
  add column if not exists source_document_id uuid,
  add column if not exists renewal_reuse_policy text,
  add column if not exists reused_at timestamptz;

alter table public.application_documents
  drop constraint if exists application_documents_source_document_id_fkey;
alter table public.application_documents
  add constraint application_documents_source_document_id_fkey
  foreign key (source_document_id) references public.application_documents(id) on delete set null;

alter table public.application_documents
  drop constraint if exists application_documents_renewal_reuse_policy_check;
alter table public.application_documents
  add constraint application_documents_renewal_reuse_policy_check
  check (renewal_reuse_policy is null or renewal_reuse_policy in (
    'remains_valid', 'reupload_every_year', 'reupload_when_expired',
    'updated_copy_required', 'not_required_for_renewal'
  ));

create table if not exists public.renewal_settings (
  id uuid primary key default gen_random_uuid(),
  renewal_start_month integer not null default 1 check (renewal_start_month between 1 and 12),
  renewal_start_day integer not null default 1 check (renewal_start_day between 1 and 31),
  renewal_due_month integer not null default 1 check (renewal_due_month between 1 and 12),
  renewal_due_day integer not null default 20 check (renewal_due_day between 1 and 31),
  surcharge_rate numeric(6,5) not null default 0.25 check (surcharge_rate between 0 and 1),
  monthly_interest_rate numeric(6,5) not null default 0.02 check (monthly_interest_rate between 0 and 1),
  maximum_interest_months integer not null default 36 check (maximum_interest_months between 0 and 120),
  interest_month_rule text not null default 'anniversary_cycle'
    check (interest_month_rule in (
      'anniversary_cycle', 'calendar_month', 'completed_month',
      'manual_treasury_confirmation'
    )),
  penalties_enabled boolean not null default true,
  updated_by uuid,
  updated_at timestamptz not null default now()
);

insert into public.renewal_settings (id)
select gen_random_uuid()
where not exists (select 1 from public.renewal_settings);

create table if not exists public.renewal_settings_history (
  id uuid primary key default gen_random_uuid(),
  settings_id uuid not null references public.renewal_settings(id) on delete restrict,
  previous_values jsonb not null,
  new_values jsonb not null,
  reason text not null,
  changed_by uuid not null,
  changed_at timestamptz not null default now()
);

create index if not exists renewal_settings_history_changed_idx
  on public.renewal_settings_history (changed_at desc);

create table if not exists public.renewal_deadline_extensions (
  id uuid primary key default gen_random_uuid(),
  renewal_year integer not null,
  original_due_date date not null,
  extended_due_date date not null,
  reason text not null,
  authorization_reference text not null,
  surcharge_suspended boolean not null default false,
  interest_suspended boolean not null default false,
  is_active boolean not null default true,
  authorized_by uuid not null,
  created_at timestamptz not null default now(),
  check (extended_due_date >= original_due_date)
);

create unique index if not exists one_active_renewal_extension_per_year
  on public.renewal_deadline_extensions (renewal_year)
  where is_active;

alter table public.applications
  drop constraint if exists applications_deadline_extension_id_fkey;
alter table public.applications
  add constraint applications_deadline_extension_id_fkey
  foreign key (deadline_extension_id) references public.renewal_deadline_extensions(id) on delete set null;

create table if not exists public.renewal_requirements (
  id uuid primary key default gen_random_uuid(),
  permit_id uuid not null references public.permits(id) on delete cascade,
  permit_document_id uuid not null references public.permit_documents(id) on delete cascade,
  reuse_policy text not null default 'reupload_every_year'
    check (reuse_policy in (
      'remains_valid', 'reupload_every_year', 'reupload_when_expired',
      'updated_copy_required', 'not_required_for_renewal'
    )),
  required_department_id uuid references public.departments(id) on delete set null,
  is_active boolean not null default true,
  updated_by uuid,
  updated_at timestamptz not null default now(),
  unique (permit_id, permit_document_id)
);

create index if not exists renewal_requirements_permit_idx
  on public.renewal_requirements (permit_id, is_active);

alter table public.notifications
  add column if not exists related_permit_id uuid,
  add column if not exists action_url text;

alter table public.notifications
  drop constraint if exists notifications_related_permit_id_fkey;
alter table public.notifications
  add constraint notifications_related_permit_id_fkey
  foreign key (related_permit_id) references public.business_permits(id) on delete set null;

alter table public.notifications
  drop constraint if exists notifications_type_check;
alter table public.notifications
  add constraint notifications_type_check
  check (type in ('status', 'document', 'inspection', 'payment', 'permit', 'system', 'profile', 'renewal'));

create table if not exists public.renewal_notification_logs (
  id uuid primary key default gen_random_uuid(),
  permit_id uuid not null references public.business_permits(id) on delete cascade,
  applicant_id uuid not null,
  renewal_year integer not null,
  reminder_type text not null check (reminder_type in (
    'advance_december_1', 'second_december_15', 'expiration_december_31',
    'renewal_open_january_1', 'deadline_january_10', 'three_days_remaining',
    'last_day', 'late_notice'
  )),
  notification_id uuid references public.notifications(id) on delete set null,
  sent_at timestamptz not null default now()
);

create unique index if not exists renewal_notification_logs_unique_idx
  on public.renewal_notification_logs (permit_id, renewal_year, reminder_type);

create index if not exists renewal_notification_logs_applicant_idx
  on public.renewal_notification_logs (applicant_id, sent_at desc);

create table if not exists public.renewal_fee_assessments (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete restrict,
  permit_year integer not null,
  base_renewal_fee numeric(14,2) not null default 0,
  other_fees numeric(14,2) not null default 0,
  penalty_base numeric(14,2) not null default 0,
  surcharge_rate numeric(6,5) not null default 0,
  surcharge_amount numeric(14,2) not null default 0,
  interest_rate numeric(6,5) not null default 0,
  interest_month_rule text not null default 'anniversary_cycle',
  months_delayed integer not null default 0,
  maximum_interest_months integer not null default 0,
  interest_amount numeric(14,2) not null default 0,
  total_amount numeric(14,2) not null default 0,
  calculation_date date not null,
  settings_snapshot jsonb not null default '{}'::jsonb,
  status text not null default 'draft'
    check (status in ('draft', 'calculated', 'finalized', 'paid', 'voided')),
  calculated_by uuid,
  finalized_by uuid,
  finalized_at timestamptz,
  voided_by uuid,
  voided_at timestamptz,
  void_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists one_active_renewal_assessment
  on public.renewal_fee_assessments (application_id)
  where status <> 'voided';

create index if not exists renewal_fee_assessments_status_idx
  on public.renewal_fee_assessments (permit_year, status, calculation_date desc);

create table if not exists public.renewal_assessment_adjustments (
  id uuid primary key default gen_random_uuid(),
  assessment_id uuid not null references public.renewal_fee_assessments(id) on delete restrict,
  field_name text not null,
  previous_amount numeric(14,2) not null,
  new_amount numeric(14,2) not null,
  reason text not null,
  adjusted_by uuid not null,
  adjusted_at timestamptz not null default now()
);

create or replace function public.lock_finalized_renewal_assessment()
returns trigger
language plpgsql
as $$
begin
  if old.status = 'paid' then
    raise exception 'Paid renewal assessments cannot be changed';
  end if;

  if old.status = 'finalized' and (
    new.application_id is distinct from old.application_id or
    new.permit_year is distinct from old.permit_year or
    new.base_renewal_fee is distinct from old.base_renewal_fee or
    new.other_fees is distinct from old.other_fees or
    new.penalty_base is distinct from old.penalty_base or
    new.surcharge_rate is distinct from old.surcharge_rate or
    new.surcharge_amount is distinct from old.surcharge_amount or
    new.interest_rate is distinct from old.interest_rate or
    new.interest_month_rule is distinct from old.interest_month_rule or
    new.months_delayed is distinct from old.months_delayed or
    new.maximum_interest_months is distinct from old.maximum_interest_months or
    new.interest_amount is distinct from old.interest_amount or
    new.total_amount is distinct from old.total_amount or
    new.calculation_date is distinct from old.calculation_date or
    new.settings_snapshot is distinct from old.settings_snapshot
  ) then
    raise exception 'Finalized renewal assessment values are locked';
  end if;

  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists renewal_assessment_lock on public.renewal_fee_assessments;
create trigger renewal_assessment_lock
before update on public.renewal_fee_assessments
for each row execute function public.lock_finalized_renewal_assessment();

create or replace view public.renewal_monitoring
with (security_invoker = true)
as
select
  bp.id as permit_id,
  bp.application_id as source_application_id,
  source_app.applicant_id,
  bp.business_name,
  bp.owner_name,
  bp.permit_number,
  bp.permit_type,
  bp.permit_year as existing_permit_year,
  bp.issued_date,
  bp.valid_until,
  bp.renewal_year,
  bp.renewal_status,
  renewal_app.id as renewal_application_id,
  renewal_app.renewal_due_date,
  renewal_app.original_renewal_due_date,
  renewal_app.effective_renewal_due_date,
  renewal_app.filed_at,
  renewal_app.is_late,
  renewal_app.status as application_status,
  renewal_app.progress as department_status,
  renewal_app.assessment_status,
  renewal_app.payment_status,
  rfa.status as renewal_assessment_status,
  rfa.total_amount as finalized_total,
  rfa.total_amount as renewal_total_amount,
  coalesce(renewal_app.updated_at, bp.updated_at) as updated_at
from public.business_permits bp
join public.applications source_app on source_app.id = bp.application_id
left join public.applications renewal_app
  on renewal_app.source_permit_id = bp.id
 and renewal_app.permit_year = bp.renewal_year
 and renewal_app.application_type = 'renewal'
left join public.renewal_fee_assessments rfa
  on rfa.application_id = renewal_app.id
 and rfa.status <> 'voided';

alter table public.renewal_settings enable row level security;
alter table public.renewal_settings_history enable row level security;
alter table public.renewal_deadline_extensions enable row level security;
alter table public.renewal_requirements enable row level security;
alter table public.renewal_notification_logs enable row level security;
alter table public.renewal_fee_assessments enable row level security;
alter table public.renewal_assessment_adjustments enable row level security;

drop policy if exists "Authenticated users can view renewal settings" on public.renewal_settings;
create policy "Authenticated users can view renewal settings"
on public.renewal_settings for select to authenticated using (true);

drop policy if exists "Authenticated users can view renewal deadlines" on public.renewal_deadline_extensions;
create policy "Authenticated users can view renewal deadlines"
on public.renewal_deadline_extensions for select to authenticated using (is_active);

drop policy if exists "Authenticated users can view renewal requirements" on public.renewal_requirements;
create policy "Authenticated users can view renewal requirements"
on public.renewal_requirements for select to authenticated using (is_active);

drop policy if exists "Applicants can view own renewal assessments" on public.renewal_fee_assessments;
create policy "Applicants can view own renewal assessments"
on public.renewal_fee_assessments for select to authenticated
using (
  exists (
    select 1 from public.applications
    where applications.id = renewal_fee_assessments.application_id
      and applications.applicant_id = (select auth.uid())
  )
);

grant select on public.renewal_settings, public.renewal_deadline_extensions,
  public.renewal_requirements, public.renewal_fee_assessments to authenticated;

revoke all on public.renewal_settings_history, public.renewal_notification_logs,
  public.renewal_assessment_adjustments, public.renewal_monitoring from anon, authenticated;
revoke all on public.renewal_monitoring from anon, authenticated;
grant select on public.renewal_monitoring to service_role;

notify pgrst, 'reload schema';
