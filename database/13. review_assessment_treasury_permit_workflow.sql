create extension if not exists "pgcrypto";

alter table public.applications
add column if not exists payment_status text not null default 'Unpaid';

alter table public.applications
add column if not exists assessment_status text not null default 'Draft';

alter table public.applications
add column if not exists initial_reviewed_by uuid;

alter table public.applications
add column if not exists initial_reviewed_at timestamptz;

alter table public.applications
add column if not exists finalized_by uuid;

alter table public.applications
add column if not exists finalized_at timestamptz;

create table if not exists public.application_document_reviews (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  document_id uuid not null references public.application_documents(id) on delete cascade,
  reviewer_id uuid,
  department_key text,
  status text not null default 'Pending'
    check (status in ('Pending', 'Under Review', 'Verified', 'Rejected', 'For Revision', 'Resubmitted')),
  remarks text,
  reviewed_at timestamptz,
  is_deleted boolean not null default false,
  deleted_at timestamptz,
  deleted_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists application_document_reviews_application_idx
  on public.application_document_reviews (application_id, created_at desc)
  where is_deleted = false;

create index if not exists application_document_reviews_document_idx
  on public.application_document_reviews (document_id, created_at desc)
  where is_deleted = false;

create table if not exists public.application_department_reviews (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  department_id uuid references public.departments(id) on delete set null,
  department_key text not null,
  assigned_user_id uuid,
  status text not null default 'Pending'
    check (status in ('Not Started', 'Pending', 'Under Review', 'For Revision', 'Approved', 'Rejected', 'Completed')),
  remarks text,
  assigned_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  approved_at timestamptz,
  rejected_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (application_id, department_key)
);

create index if not exists application_department_reviews_status_idx
  on public.application_department_reviews (department_key, status, assigned_at desc);

create table if not exists public.fee_types (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  code text not null unique,
  department_id uuid references public.departments(id) on delete set null,
  department_key text not null,
  category text not null,
  formula_type text not null default 'fixed',
  default_rate numeric(14, 4) not null default 0,
  minimum_amount numeric(14, 2),
  maximum_amount numeric(14, 2),
  is_required boolean not null default false,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists fee_types_department_idx
  on public.fee_types (department_key, is_active, name);

create table if not exists public.fee_rate_configurations (
  id uuid primary key default gen_random_uuid(),
  fee_type_id uuid not null references public.fee_types(id) on delete cascade,
  business_classification_id uuid references public.business_classifications(id) on delete set null,
  permit_type_id uuid references public.permits(id) on delete set null,
  min_value numeric(14, 2),
  max_value numeric(14, 2),
  fixed_amount numeric(14, 2),
  rate numeric(14, 4),
  percentage numeric(8, 4),
  effective_from date not null default current_date,
  effective_until date,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists fee_rate_configurations_lookup_idx
  on public.fee_rate_configurations (fee_type_id, permit_type_id, business_classification_id, is_active);

create table if not exists public.assessments (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  assessment_number text not null unique,
  status text not null default 'Draft'
    check (status in ('Draft', 'In Progress', 'Pending Department Fees', 'Ready for Completion', 'Completed', 'For Payment', 'Paid', 'Cancelled')),
  subtotal numeric(14, 2) not null default 0,
  discount_total numeric(14, 2) not null default 0,
  penalty_total numeric(14, 2) not null default 0,
  grand_total numeric(14, 2) not null default 0,
  completed_by uuid,
  completed_at timestamptz,
  locked_at timestamptz,
  soa_file_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (application_id)
);

create index if not exists assessments_application_status_idx
  on public.assessments (application_id, status);

create table if not exists public.assessment_items (
  id uuid primary key default gen_random_uuid(),
  assessment_id uuid not null references public.assessments(id) on delete cascade,
  application_id uuid not null references public.applications(id) on delete cascade,
  department_key text not null,
  fee_type_id uuid references public.fee_types(id) on delete set null,
  fee_name text not null,
  category text not null,
  computation_basis text,
  formula_type text not null default 'fixed',
  quantity numeric(14, 4) not null default 1,
  unit text,
  rate numeric(14, 4) not null default 0,
  percentage numeric(8, 4),
  base_amount numeric(14, 2) not null default 0,
  amount numeric(14, 2) not null default 0,
  penalty numeric(14, 2) not null default 0,
  discount numeric(14, 2) not null default 0,
  final_amount numeric(14, 2) not null default 0,
  remarks text,
  status text not null default 'Draft'
    check (status in ('Draft', 'Submitted', 'Locked', 'Cancelled')),
  created_by uuid,
  updated_by uuid,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists assessment_items_assessment_idx
  on public.assessment_items (assessment_id, department_key, is_active);

create table if not exists public.treasury_payment_queue (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  assessment_id uuid not null references public.assessments(id) on delete cascade,
  queue_number text not null unique,
  status text not null default 'Waiting for Payment'
    check (status in ('Waiting for Payment', 'Processing', 'Partially Paid', 'Paid', 'Payment Failed', 'Cancelled', 'Refunded')),
  amount_due numeric(14, 2) not null default 0,
  queued_at timestamptz not null default now(),
  assigned_cashier_id uuid,
  processing_started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (assessment_id)
);

create index if not exists treasury_payment_queue_status_idx
  on public.treasury_payment_queue (status, queued_at desc);

create table if not exists public.payments (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  assessment_id uuid not null references public.assessments(id) on delete cascade,
  queue_id uuid not null references public.treasury_payment_queue(id) on delete cascade,
  payment_reference text not null unique,
  amount_due numeric(14, 2) not null default 0,
  amount_paid numeric(14, 2) not null default 0,
  change_amount numeric(14, 2) not null default 0,
  payment_method text not null default 'Cash',
  payment_status text not null default 'Recorded'
    check (payment_status in ('Recorded', 'Confirmed', 'Voided', 'Cancelled', 'Refunded')),
  official_receipt_number text unique,
  paid_at timestamptz,
  cashier_id uuid,
  remarks text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists payments_application_idx
  on public.payments (application_id, created_at desc);

create table if not exists public.official_receipts (
  id uuid primary key default gen_random_uuid(),
  payment_id uuid not null references public.payments(id) on delete cascade,
  application_id uuid not null references public.applications(id) on delete cascade,
  receipt_number text not null unique,
  receipt_file_url text,
  issued_at timestamptz not null default now(),
  issued_by uuid,
  status text not null default 'Issued'
    check (status in ('Issued', 'Reprinted', 'Voided', 'Replaced')),
  void_reason text,
  voided_at timestamptz,
  voided_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists official_receipts_application_idx
  on public.official_receipts (application_id, issued_at desc);

create table if not exists public.business_permits (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade unique,
  permit_number text not null unique,
  control_number text not null,
  business_name text not null,
  owner_name text not null,
  business_classification text,
  business_address text,
  permit_type text,
  issue_date date not null default current_date,
  expiration_date date not null,
  status text not null default 'Ready for Release'
    check (status in ('Draft', 'Generated', 'Ready for Release', 'Released', 'Expired', 'Revoked', 'Cancelled')),
  permit_file_url text,
  verification_code text not null unique,
  qr_code_value text,
  issued_by uuid,
  released_at timestamptz,
  revoked_at timestamptz,
  revoked_by uuid,
  revocation_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists business_permits_application_idx
  on public.business_permits (application_id, status);

alter table public.application_document_reviews enable row level security;
alter table public.application_department_reviews enable row level security;
alter table public.fee_types enable row level security;
alter table public.fee_rate_configurations enable row level security;
alter table public.assessments enable row level security;
alter table public.assessment_items enable row level security;
alter table public.treasury_payment_queue enable row level security;
alter table public.payments enable row level security;
alter table public.official_receipts enable row level security;
alter table public.business_permits enable row level security;

grant select, insert, update on
  public.application_document_reviews,
  public.application_department_reviews,
  public.fee_types,
  public.fee_rate_configurations,
  public.assessments,
  public.assessment_items,
  public.treasury_payment_queue,
  public.payments,
  public.official_receipts,
  public.business_permits
to authenticated;

insert into public.fee_types (name, code, department_key, category, formula_type, default_rate, is_required)
values
  ('Local Business Tax', 'LBT', 'bplo', 'Local Business Taxes', 'percentage', 0, false),
  ('Municipal License Tax', 'MUNICIPAL_LICENSE_TAX', 'bplo', 'Local Business Taxes', 'percentage', 0, false),
  ('Mayor''s Permit Fee', 'MAYORS_PERMIT_FEE', 'bplo', 'Regulatory Fees and Charges', 'higher_of_asset_or_worker', 0, true),
  ('Sticker Fee', 'STICKER_FEE', 'bplo', 'Regulatory Fees and Charges', 'fixed', 0, false),
  ('Environmental Fee', 'ENVIRONMENTAL_FEE', 'bplo', 'Regulatory Fees and Charges', 'fixed', 0, false),
  ('Tax on Delivery Vans or Trucks', 'DELIVERY_VEHICLE_TAX', 'bplo', 'Taxes on Specific Business Operations', 'quantity_rate', 0, false),
  ('Tax on Signboard or Billboard', 'SIGNBOARD_TAX', 'zoning', 'Taxes on Specific Business Operations', 'area_rate', 0, false),
  ('Sanitary Fee', 'SANITARY_FEE', 'health', 'Regulatory Fees and Charges', 'fixed', 0, true),
  ('Laboratory Fee', 'LABORATORY_FEE', 'health', 'Regulatory Fees and Charges', 'fixed_plus_variable', 0, false),
  ('Zoning Fee', 'ZONING_FEE', 'zoning', 'Regulatory Fees and Charges', 'area_rate', 0, true),
  ('Annual Inspection Fee', 'ANNUAL_INSPECTION_FEE', 'engineering', 'Regulatory Fees and Charges', 'fixed_or_percentage', 0, true),
  ('Weight and Measure Fee', 'WEIGHT_MEASURE_FEE', 'engineering', 'Regulatory Fees and Charges', 'quantity_rate', 0, false),
  ('Storage and Sale of Combustible or Flammable Substances Fee', 'COMBUSTIBLE_STORAGE_FEE', 'fire', 'Regulatory Fees and Charges', 'area_rate', 0, false),
  ('Tax on Storage of Combustible or Flammable Substances', 'COMBUSTIBLE_STORAGE_TAX', 'fire', 'Taxes on Specific Business Operations', 'area_rate', 0, false),
  ('Fire Safety Inspection Fee', 'FIRE_SAFETY_INSPECTION_FEE', 'fire', 'Fire Safety', 'percentage', 10, true),
  ('Barangay Clearance Fee', 'BARANGAY_CLEARANCE_FEE', 'bplo', 'Clearances and Certifications', 'fixed', 0, false),
  ('Community Tax', 'COMMUNITY_TAX', 'treasury', 'Local Business Taxes', 'gross_receipts_per_thousand', 0, false)
on conflict (code) do update set
  name = excluded.name,
  department_key = excluded.department_key,
  category = excluded.category,
  formula_type = excluded.formula_type,
  default_rate = excluded.default_rate,
  is_required = excluded.is_required,
  updated_at = now();

notify pgrst, 'reload schema';
