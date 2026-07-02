create table if not exists public.application_ocr_results (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  application_document_id uuid references public.application_documents(id) on delete cascade,
  permit_document_id uuid,
  file_name text,
  file_url text,
  document_type text,
  raw_text text,
  extracted_fields jsonb not null default '{}'::jsonb,
  confidence_score numeric(5,2),
  parser_version text,
  ocr_status text not null default 'Pending'
    check (ocr_status in ('Pending', 'Processing', 'Completed', 'Failed')),
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.application_ocr_results enable row level security;

alter table public.application_ocr_results
add column if not exists parser_version text;

drop policy if exists "Applicants can view own OCR results" on public.application_ocr_results;

create policy "Applicants can view own OCR results"
on public.application_ocr_results
for select
to authenticated
using (
  exists (
    select 1 from public.applications
    where applications.id = application_ocr_results.application_id
      and applications.applicant_id = auth.uid()
  )
);

alter table public.application_documents
add column if not exists ocr_status text default 'Pending';

alter table public.application_documents
add column if not exists ocr_extracted_fields jsonb default '{}'::jsonb;

alter table public.application_documents
add column if not exists ocr_raw_text text;
