create table if not exists public.business_classifications (
  id uuid primary key default gen_random_uuid(),
  code text unique,
  name text not null,
  normalized_name text not null,
  parent_category text,
  description text,
  source_metadata jsonb not null default '{}'::jsonb,
  is_active boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint business_classifications_normalized_name_key unique (normalized_name)
);

create index if not exists business_classifications_active_name_idx
  on public.business_classifications (is_active, name);

create index if not exists business_classifications_parent_active_idx
  on public.business_classifications (parent_category, is_active);

create index if not exists business_classifications_normalized_idx
  on public.business_classifications (normalized_name);

alter table public.business_classifications enable row level security;

drop policy if exists "Authenticated users can view active business classifications"
  on public.business_classifications;
create policy "Authenticated users can view active business classifications"
  on public.business_classifications
  for select
  to authenticated
  using (is_active = true);

grant select on public.business_classifications to authenticated;

alter table public.applications
add column if not exists business_classification_id uuid;

alter table public.applications
add column if not exists business_classification_other text;

alter table public.applications
drop constraint if exists applications_business_classification_id_fkey;

alter table public.applications
add constraint applications_business_classification_id_fkey
foreign key (business_classification_id)
references public.business_classifications(id)
on delete restrict;

create index if not exists applications_business_classification_idx
  on public.applications (business_classification_id);

create table if not exists public.business_classification_match_reviews (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  original_classification text not null,
  normalized_classification text not null,
  review_status text not null default 'Needs Review',
  created_at timestamptz not null default now(),
  unique (application_id, normalized_classification)
);

alter table public.business_classification_match_reviews enable row level security;

create index if not exists business_classification_match_reviews_status_idx
  on public.business_classification_match_reviews (review_status, created_at desc);

grant select on public.business_classification_match_reviews to authenticated;

create or replace function public.normalize_business_classification(value text)
returns text
language sql
immutable
as $$
  select trim(regexp_replace(
    regexp_replace(
      regexp_replace(
        upper(replace(replace(replace(coalesce(value, ''), '&', ' AND '), '–', '-'), '—', '-')),
        '\mBAKE\s+SHOP\M',
        'BAKESHOP',
        'g'
      ),
      '[^A-Z0-9]+',
      ' ',
      'g'
    ),
    '\s+',
    ' ',
    'g'
  ));
$$;

update public.applications app
set business_classification_id = cls.id
from public.business_classifications cls
where app.business_classification_id is null
  and app.business_info ? 'business_classification'
  and cls.normalized_name = public.normalize_business_classification(app.business_info->>'business_classification');

insert into public.business_classification_match_reviews (
  application_id,
  original_classification,
  normalized_classification
)
select
  app.id,
  app.business_info->>'business_classification',
  public.normalize_business_classification(app.business_info->>'business_classification')
from public.applications app
where app.business_classification_id is null
  and nullif(trim(app.business_info->>'business_classification'), '') is not null
on conflict (application_id, normalized_classification) do nothing;

notify pgrst, 'reload schema';
