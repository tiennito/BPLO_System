create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  application_id uuid references public.applications(id) on delete cascade,
  title text not null,
  message text not null,
  type text not null default 'system'
    check (type in ('status', 'document', 'inspection', 'payment', 'permit', 'system')),
  source_role text not null default 'System',
  is_read boolean not null default false,
  created_at timestamptz not null default now(),
  read_at timestamptz
);

create index if not exists notifications_user_created_idx
  on public.notifications (user_id, created_at desc);

create index if not exists notifications_user_unread_idx
  on public.notifications (user_id, is_read, created_at desc);

alter table public.notifications enable row level security;

drop policy if exists "Applicants can view own notifications" on public.notifications;
create policy "Applicants can view own notifications"
on public.notifications for select
to authenticated
using (user_id = (select auth.uid()));

drop policy if exists "Applicants can update own notifications" on public.notifications;
create policy "Applicants can update own notifications"
on public.notifications for update
to authenticated
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));

drop policy if exists "Applicants can delete own notifications" on public.notifications;
create policy "Applicants can delete own notifications"
on public.notifications for delete
to authenticated
using (user_id = (select auth.uid()));

grant select, update, delete on public.notifications to authenticated;
notify pgrst, 'reload schema';
