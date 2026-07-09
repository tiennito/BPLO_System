-- Structured OCR review results.
-- Keeps raw OCR text, detected document type, per-field confidence, and applicant corrections.

create table if not exists public.ocr_results (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  document_id uuid references public.application_documents(id) on delete cascade,
  permit_document_id uuid,
  legacy_ocr_result_id uuid references public.application_ocr_results(id) on delete set null,
  document_type text not null default 'Unknown Document',
  extracted_text text,
  extracted_fields_json jsonb not null default '{}'::jsonb,
  confidence_score numeric(5,2) not null default 0,
  correction_status text not null default 'pending'
    check (correction_status in ('pending', 'accepted', 'corrected', 'rejected')),
  created_by uuid,
  corrected_by uuid,
  corrected_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.ocr_results enable row level security;

create index if not exists ocr_results_application_created_idx
  on public.ocr_results (application_id, created_at desc);

create index if not exists ocr_results_document_idx
  on public.ocr_results (document_id);

drop policy if exists "Applicants can view own structured OCR results" on public.ocr_results;
create policy "Applicants can view own structured OCR results"
on public.ocr_results
for select
to authenticated
using (
  exists (
    select 1
    from public.applications
    where applications.id = ocr_results.application_id
      and applications.applicant_id = (select auth.uid())
  )
);

drop policy if exists "Applicants can update own structured OCR corrections" on public.ocr_results;
create policy "Applicants can update own structured OCR corrections"
on public.ocr_results
for update
to authenticated
using (
  exists (
    select 1
    from public.applications
    where applications.id = ocr_results.application_id
      and applications.applicant_id = (select auth.uid())
  )
)
with check (
  exists (
    select 1
    from public.applications
    where applications.id = ocr_results.application_id
      and applications.applicant_id = (select auth.uid())
  )
);

alter table public.application_ocr_results
  add column if not exists error_message text;
