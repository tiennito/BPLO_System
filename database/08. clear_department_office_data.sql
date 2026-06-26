begin;

delete from public.department_verifications;
delete from public.department_remarks;
delete from public.department_inspections;
delete from public.department_reports;
delete from public.department_requirement_checklists;
delete from public.department_settings;
delete from public.department_application_assignments;

delete from public.business_permit_applications
where user_id = '00000000-0000-0000-0000-000000000000'
  and permit_id similar to 'BPLO-(ENG|HEA|ZON|FIR)-%';

commit;
