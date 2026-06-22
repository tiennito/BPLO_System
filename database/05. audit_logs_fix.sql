create extension if not exists pgcrypto;

create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid,
  actor_email text,
  actor_role text,
  action text not null,
  entity_type text,
  entity_id text,
  details jsonb not null default '{}'::jsonb,
  ip_address text,
  user_agent text,
  created_at timestamptz not null default now()
);

create index if not exists audit_logs_created_idx
  on public.audit_logs (created_at desc);

create index if not exists audit_logs_actor_created_idx
  on public.audit_logs (actor_user_id, created_at desc);

alter table public.audit_logs enable row level security;

create or replace function public.handle_new_user_audit_log()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.audit_logs (
    actor_user_id,
    actor_email,
    actor_role,
    action,
    entity_type,
    entity_id,
    details
  )
  values (
    new.id,
    new.email,
    coalesce(new.raw_app_meta_data->>'role', 'user'),
    'account_created',
    'user',
    new.id::text,
    jsonb_build_object('email', new.email)
  );

  return new;
end;
$$;

drop trigger if exists on_auth_user_created_audit_log on auth.users;

create trigger on_auth_user_created_audit_log
after insert on auth.users
for each row execute procedure public.handle_new_user_audit_log();

notify pgrst, 'reload schema';
