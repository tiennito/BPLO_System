-- Applicant UX support indexes.
-- These indexes speed up draft lookup, dashboard progress loading, and notification sorting.

create index if not exists applications_applicant_status_updated_idx
  on public.applications (applicant_id, status, updated_at desc);

create index if not exists application_department_reviews_application_idx
  on public.application_department_reviews (application_id, department_key);

create index if not exists department_application_assignments_application_idx
  on public.department_application_assignments (application_id, department_key)
  where deleted_at is null;

create index if not exists notifications_user_created_idx
  on public.notifications (user_id, created_at desc);
