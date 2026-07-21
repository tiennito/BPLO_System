alter table public.applicants
  add column if not exists birthdate date,
  add column if not exists sex text,
  add column if not exists civil_status text,
  add column if not exists house_number text,
  add column if not exists profile_photo_url text;

create or replace function public.set_applicants_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_applicants_updated_at on public.applicants;
create trigger set_applicants_updated_at
before update on public.applicants
for each row execute procedure public.set_applicants_updated_at();

drop policy if exists "Applicants can update their own row" on public.applicants;
create policy "Applicants can update their own row"
  on public.applicants
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

grant select, update on public.applicants to authenticated;

comment on table public.applicants is
  'Primary source of truth for applicant-editable identity, contact, and address information.';
