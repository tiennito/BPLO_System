create extension if not exists "pgcrypto";

-- The existing business_permits table remains the source of truth. These columns
-- add authoritative source links, immutable snapshots, versioning, and secure QR/PDF metadata.
alter table public.business_permits
  drop constraint if exists business_permits_application_id_key;

alter table public.business_permits
  add column if not exists applicant_id uuid,
  add column if not exists assessment_id uuid,
  add column if not exists payment_id uuid,
  add column if not exists official_receipt_id uuid,
  add column if not exists sp_number text,
  add column if not exists official_receipt_number text,
  add column if not exists payment_amount numeric(14, 2),
  add column if not exists payment_date timestamptz,
  add column if not exists release_date date,
  add column if not exists qr_token text,
  add column if not exists qr_verification_url text,
  add column if not exists generated_by uuid,
  add column if not exists generated_at timestamptz,
  add column if not exists version_number integer not null default 1,
  add column if not exists is_current_version boolean not null default true,
  add column if not exists previous_version_id uuid,
  add column if not exists snapshot_data jsonb not null default '{}'::jsonb,
  add column if not exists authorized_official_name text,
  add column if not exists authorized_official_position text,
  add column if not exists generated_pdf_sha256 text,
  add column if not exists locked_at timestamptz,
  add column if not exists reissue_reason text,
  add column if not exists superseded_at timestamptz;

alter table public.business_permits
  drop constraint if exists business_permits_applicant_id_fkey,
  drop constraint if exists business_permits_assessment_id_fkey,
  drop constraint if exists business_permits_payment_id_fkey,
  drop constraint if exists business_permits_official_receipt_id_fkey,
  drop constraint if exists business_permits_previous_version_id_fkey;

alter table public.business_permits
  add constraint business_permits_applicant_id_fkey
    foreign key (applicant_id) references auth.users(id) on delete restrict,
  add constraint business_permits_assessment_id_fkey
    foreign key (assessment_id) references public.assessments(id) on delete restrict,
  add constraint business_permits_payment_id_fkey
    foreign key (payment_id) references public.payments(id) on delete restrict,
  add constraint business_permits_official_receipt_id_fkey
    foreign key (official_receipt_id) references public.official_receipts(id) on delete restrict,
  add constraint business_permits_previous_version_id_fkey
    foreign key (previous_version_id) references public.business_permits(id) on delete restrict;

alter table public.business_permits
  drop constraint if exists business_permits_status_check;
alter table public.business_permits
  add constraint business_permits_status_check
  check (status in (
    'Draft', 'Generated', 'Ready for Release', 'Released', 'Expired',
    'Revoked', 'Cancelled', 'Reissued', 'Superseded'
  ));

create unique index if not exists business_permits_qr_token_key
  on public.business_permits (qr_token)
  where qr_token is not null;

create unique index if not exists business_permits_application_version_key
  on public.business_permits (application_id, version_number);

create unique index if not exists business_permits_one_current_version_key
  on public.business_permits (application_id)
  where is_current_version;

create index if not exists business_permits_public_verification_idx
  on public.business_permits (qr_token, status, expiration_date)
  where qr_token is not null and is_current_version;

alter table public.applications
  add column if not exists final_approved_by uuid,
  add column if not exists final_approved_at timestamptz;

alter table public.permit_required_offices
  add column if not exists inspection_required boolean not null default false;

create table if not exists public.permit_number_counters (
  permit_year integer primary key,
  last_sequence bigint not null default 0 check (last_sequence >= 0),
  updated_at timestamptz not null default now()
);

create table if not exists public.permit_issuance_settings (
  id uuid primary key default gen_random_uuid(),
  authorized_official_name text not null,
  authorized_official_position text not null,
  permit_number_prefix text not null default 'BP',
  validity_rule text not null default 'calendar_year'
    check (validity_rule in ('calendar_year')),
  public_business_address boolean not null default true,
  effective_from date not null default current_date,
  effective_until date,
  is_active boolean not null default true,
  created_by uuid references auth.users(id) on delete set null,
  updated_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (btrim(authorized_official_name) <> ''),
  check (btrim(authorized_official_position) <> ''),
  check (permit_number_prefix ~ '^[A-Z0-9-]{1,12}$'),
  check (effective_until is null or effective_until >= effective_from)
);

create index if not exists permit_issuance_settings_effective_idx
  on public.permit_issuance_settings (is_active, effective_from desc, effective_until);

alter table public.permit_number_counters enable row level security;
alter table public.permit_issuance_settings enable row level security;

revoke all on public.permit_number_counters from public, anon, authenticated;
revoke all on public.permit_issuance_settings from public, anon, authenticated;
grant select, insert, update on public.permit_number_counters to service_role;
grant select, insert, update on public.permit_issuance_settings to service_role;
grant select, insert, update on public.business_permits to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('business-permits', 'business-permits', false, 10485760, array['application/pdf'])
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- Permit files are intentionally server-only. The backend downloads them with
-- the service role after independently authorizing BPLO staff.
drop policy if exists "Authenticated users can read business permits" on storage.objects;
drop policy if exists "Authenticated users can upload business permits" on storage.objects;

create or replace function public.reserve_official_business_permit(
  p_application_id uuid,
  p_assessment_id uuid,
  p_payment_id uuid,
  p_official_receipt_id uuid,
  p_actor_id uuid,
  p_permit_year integer,
  p_release_date date,
  p_expiration_date date,
  p_qr_token text,
  p_qr_verification_url text,
  p_snapshot_data jsonb,
  p_reissue_reason text default null
)
returns setof public.business_permits
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_application public.applications%rowtype;
  v_existing public.business_permits%rowtype;
  v_settings public.permit_issuance_settings%rowtype;
  v_sequence bigint;
  v_version integer := 1;
  v_permit_number text;
  v_sp_number text;
begin
  if p_permit_year < 2000 or p_permit_year > 9999 then
    raise exception 'Invalid permit issuance year.';
  end if;
  if p_qr_token is null or length(p_qr_token) < 32 then
    raise exception 'A secure QR verification token is required.';
  end if;
  if coalesce(btrim(p_snapshot_data->>'owner_name'), '') = ''
     or coalesce(btrim(p_snapshot_data->>'business_name'), '') = ''
     or coalesce(btrim(p_snapshot_data->>'business_address'), '') = '' then
    raise exception 'The official permit snapshot is incomplete.';
  end if;

  select * into v_application
  from public.applications
  where id = p_application_id
  for update;
  if not found then
    raise exception 'Application not found.';
  end if;

  select * into v_settings
  from public.permit_issuance_settings
  where is_active
    and effective_from <= p_release_date
    and (effective_until is null or effective_until >= p_release_date)
  order by effective_from desc, created_at desc
  limit 1;
  if not found then
    raise exception 'No active permit issuance settings are configured.';
  end if;

  select * into v_existing
  from public.business_permits
  where application_id = p_application_id and is_current_version
  for update;

  if found and coalesce(btrim(p_reissue_reason), '') = '' then
    if v_existing.status in ('Generated', 'Ready for Release') then
      return query select * from public.business_permits where id = v_existing.id;
      return;
    end if;
    raise exception 'An active permit already exists for this application.';
  end if;

  if found then
    v_version := v_existing.version_number + 1;
    update public.business_permits
    set is_current_version = false,
        status = case when status = 'Released' then 'Superseded' else status end,
        superseded_at = now(),
        updated_at = now()
    where id = v_existing.id;
  end if;

  insert into public.permit_number_counters (permit_year, last_sequence, updated_at)
  values (p_permit_year, 1, now())
  on conflict (permit_year) do update
    set last_sequence = public.permit_number_counters.last_sequence + 1,
        updated_at = now()
  returning last_sequence into v_sequence;

  v_permit_number := v_settings.permit_number_prefix || '-' || p_permit_year::text || '-' || lpad(v_sequence::text, 6, '0');
  v_sp_number := v_permit_number;

  return query
  insert into public.business_permits (
    application_id, applicant_id, assessment_id, payment_id, official_receipt_id,
    permit_number, sp_number, control_number, business_name, owner_name,
    business_classification, business_address, permit_type, issue_date, issued_date,
    release_date, expiration_date, valid_until, permit_year, renewal_year,
    renewal_status, status, verification_code, qr_code_value, qr_token,
    qr_verification_url, issued_by, generated_by, generated_at, version_number,
    is_current_version, previous_version_id, snapshot_data,
    official_receipt_number, payment_amount, payment_date,
    authorized_official_name, authorized_official_position, reissue_reason,
    created_at, updated_at
  ) values (
    p_application_id, v_application.applicant_id, p_assessment_id, p_payment_id, p_official_receipt_id,
    v_permit_number, v_sp_number, left(p_application_id::text, 8),
    p_snapshot_data->>'business_name', p_snapshot_data->>'owner_name',
    p_snapshot_data->>'business_classification', p_snapshot_data->>'business_address',
    coalesce(nullif(p_snapshot_data->>'permit_type', ''), 'Business Permit'),
    p_release_date, p_release_date, p_release_date, p_expiration_date, p_expiration_date,
    p_permit_year, p_permit_year + 1, 'not_open', 'Generated', p_qr_token,
    p_qr_verification_url, p_qr_token, p_qr_verification_url, p_actor_id, p_actor_id,
    now(), v_version, true, case when v_existing.id is null then null else v_existing.id end,
    p_snapshot_data || jsonb_build_object('permit_number', v_permit_number, 'sp_number', v_sp_number),
    p_snapshot_data->>'official_receipt_number',
    nullif(p_snapshot_data->>'payment_amount', '')::numeric,
    nullif(p_snapshot_data->>'payment_date_time', '')::timestamptz,
    v_settings.authorized_official_name, v_settings.authorized_official_position,
    nullif(btrim(p_reissue_reason), ''), now(), now()
  )
  returning *;

  update public.applications
  set status = 'Permit Ready for Release',
      progress = 'Permit Generated',
      final_approved_by = p_actor_id,
      final_approved_at = coalesce(final_approved_at, now()),
      finalized_by = p_actor_id,
      finalized_at = coalesce(finalized_at, now()),
      updated_at = now()
  where id = p_application_id;
end;
$$;

create or replace function public.finalize_official_business_permit_release(
  p_permit_id uuid,
  p_actor_id uuid,
  p_release_date date,
  p_expiration_date date,
  p_pdf_storage_path text,
  p_pdf_sha256 text,
  p_snapshot_data jsonb
)
returns setof public.business_permits
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_permit public.business_permits%rowtype;
  v_application public.applications%rowtype;
  v_actor public.profiles%rowtype;
begin
  if coalesce(btrim(p_pdf_storage_path), '') = '' or coalesce(btrim(p_pdf_sha256), '') = '' then
    raise exception 'The final permit PDF is required before release.';
  end if;

  select * into v_permit
  from public.business_permits
  where id = p_permit_id and is_current_version
  for update;
  if not found then
    raise exception 'Current permit record not found.';
  end if;
  if v_permit.status = 'Released' then
    return query select * from public.business_permits where id = v_permit.id;
    return;
  end if;
  if v_permit.status not in ('Generated', 'Ready for Release') then
    raise exception 'Only a generated permit can be released.';
  end if;

  select * into v_application
  from public.applications
  where id = v_permit.application_id
  for update;

  select * into v_actor
  from public.profiles
  where auth_user_id = p_actor_id
  limit 1;

  update public.business_permits
  set status = 'Released',
      issue_date = p_release_date,
      issued_date = p_release_date,
      release_date = p_release_date,
      expiration_date = p_expiration_date,
      valid_until = p_expiration_date,
      permit_file_url = p_pdf_storage_path,
      generated_pdf_sha256 = p_pdf_sha256,
      snapshot_data = p_snapshot_data || jsonb_build_object(
        'permit_number', permit_number,
        'sp_number', sp_number,
        'release_date', p_release_date,
        'expiration_date', p_expiration_date
      ),
      released_by = p_actor_id,
      released_at = now(),
      locked_at = now(),
      updated_at = now()
  where id = v_permit.id;

  update public.applications
  set status = 'Released',
      progress = 'Permit Released',
      updated_at = now()
  where id = v_permit.application_id;

  insert into public.application_status_history (application_id, status, remarks, created_by)
  values (v_permit.application_id, 'Released', 'Official Business Permit released.', p_actor_id);

  insert into public.notifications (
    user_id, application_id, related_permit_id, title, message, type, source_role, action_url
  ) values (
    v_application.applicant_id,
    v_permit.application_id,
    v_permit.id,
    'Business Permit Ready for Pickup',
    'Your Business Permit for ' || v_permit.business_name ||
      ' has been finalized and is ready for pickup at the Business Permits and Licensing Office. Please bring a valid ID and any required claim documents.',
    'permit', 'BPLO', '/applicant/permits?focus=' || v_permit.id::text
  );

  insert into public.audit_logs (
    actor_user_id, actor_email, actor_role, action, entity_type, entity_id, details
  ) values (
    p_actor_id, v_actor.email, coalesce(v_actor.role, 'bplo_admin'),
    'permit_released', 'business_permit', v_permit.id::text,
    jsonb_build_object(
      'applicationId', v_permit.application_id,
      'permitNumber', v_permit.permit_number,
      'releaseDate', p_release_date,
      'expirationDate', p_expiration_date,
      'pdfSha256', p_pdf_sha256
    )
  );

  return query select * from public.business_permits where id = v_permit.id;
end;
$$;

create or replace function public.protect_released_business_permit()
returns trigger
language plpgsql
as $$
begin
  if old.locked_at is not null and (
    new.application_id is distinct from old.application_id or
    new.applicant_id is distinct from old.applicant_id or
    new.permit_number is distinct from old.permit_number or
    new.sp_number is distinct from old.sp_number or
    new.snapshot_data is distinct from old.snapshot_data or
    new.permit_file_url is distinct from old.permit_file_url or
    new.generated_pdf_sha256 is distinct from old.generated_pdf_sha256 or
    new.qr_token is distinct from old.qr_token or
    new.qr_verification_url is distinct from old.qr_verification_url or
    new.assessment_id is distinct from old.assessment_id or
    new.payment_id is distinct from old.payment_id or
    new.official_receipt_id is distinct from old.official_receipt_id or
    new.official_receipt_number is distinct from old.official_receipt_number or
    new.payment_amount is distinct from old.payment_amount or
    new.payment_date is distinct from old.payment_date or
    new.release_date is distinct from old.release_date or
    new.expiration_date is distinct from old.expiration_date or
    new.business_name is distinct from old.business_name or
    new.owner_name is distinct from old.owner_name or
    new.business_address is distinct from old.business_address or
    new.authorized_official_name is distinct from old.authorized_official_name or
    new.authorized_official_position is distinct from old.authorized_official_position or
    new.version_number is distinct from old.version_number
  ) then
    raise exception 'Released permit snapshots and files are immutable; use the authorized reissue workflow.';
  end if;
  return new;
end;
$$;

drop trigger if exists protect_released_business_permit_update on public.business_permits;
create trigger protect_released_business_permit_update
before update on public.business_permits
for each row execute function public.protect_released_business_permit();

create or replace function public.prevent_released_business_permit_delete()
returns trigger
language plpgsql
as $$
begin
  if old.locked_at is not null then
    raise exception 'Released permits cannot be deleted.';
  end if;
  return old;
end;
$$;

drop trigger if exists prevent_released_business_permit_delete on public.business_permits;
create trigger prevent_released_business_permit_delete
before delete on public.business_permits
for each row execute function public.prevent_released_business_permit_delete();

revoke all on function public.reserve_official_business_permit(uuid, uuid, uuid, uuid, uuid, integer, date, date, text, text, jsonb, text) from public, anon, authenticated;
revoke all on function public.finalize_official_business_permit_release(uuid, uuid, date, date, text, text, jsonb) from public, anon, authenticated;
grant execute on function public.reserve_official_business_permit(uuid, uuid, uuid, uuid, uuid, integer, date, date, text, text, jsonb, text) to service_role;
grant execute on function public.finalize_official_business_permit_release(uuid, uuid, date, date, text, text, jsonb) to service_role;

notify pgrst, 'reload schema';
