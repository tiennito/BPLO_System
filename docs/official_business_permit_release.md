# Official Business Permit Release

This feature generates the Municipality of Victoria official Business Permit from approved system records. The PDF reference file is used only as a visual layout guide; released permits are generated from the application, assessment, payment, receipt, and configured issuance settings in Supabase.

## Database Setup

Run `database/20. official_business_permit_release.sql` after the previous migrations. It adds:

- atomic yearly permit numbering through `permit_number_counters`
- `permit_issuance_settings` for the authorized signatory and calendar-year validity rule
- immutable versioned fields on `business_permits`
- private Supabase Storage bucket `business-permits`
- service-role-only RPCs for permit reservation and final release

Seed one active issuance setting before generating permits:

```sql
insert into public.permit_issuance_settings (
  authorized_official_name,
  authorized_official_position,
  permit_number_prefix,
  validity_rule,
  effective_from,
  is_active
) values (
  'Full Name of Authorized Official',
  'Municipal Mayor',
  'BP',
  'calendar_year',
  current_date,
  true
);
```

## Staff Flow

1. BPLO approves initial review and routes required offices.
2. Required departments approve their reviews; any office marked `inspection_required` must have a completed inspection.
3. BPLO completes and locks the assessment.
4. Treasury confirms payment and issues an official receipt.
5. BPLO uses **Generate Final Permit** from the application review page.
6. Staff review the A4 permit preview, print/download as needed, then confirm release.

The release step renders the final PDF, uploads it to the private `business-permits` bucket, stores the SHA-256 hash, locks the released snapshot, updates the application to `Released`, and notifies the applicant for pickup.

## Public Verification

The QR code points to:

```text
/verify/permit/{secure-token}
```

The public page shows only verification-safe fields: permit number, business name, owner name, status, release date, expiration date, and version. The PDF itself remains private and is served only through authenticated staff endpoints.

Set `PUBLIC_BASE_URL` in `.env` so QR codes use the deployed origin. If it is omitted, the backend falls back to the current request host.
