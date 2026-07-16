# Annual Business Permit Renewal Feature

## Deployment Order

1. Apply `database/17. annual_business_permit_renewals.sql`.
2. Restart the Python web server so the new backend mixins and routes are loaded.
3. Schedule `python scripts/run_renewal_daily.py` once per day.

## Main Data Flow

- Released permits now carry `permit_year`, `issued_date`, `valid_until`, `renewal_year`, and `renewal_status`.
- New and renewal permits use calendar-year validity: issue date through December 31 of the issue year.
- Applicants start renewals from `/applicant/permits`; the backend creates one renewal application per source permit and renewal year.
- Renewals reuse allowed business information and documents according to `renewal_requirements`.
- Submission records `filed_at`, original/effective due dates, deadline extension, and `is_late` using Manila time.
- BPLO calculates renewal fees; Treasury finalizes the assessment and confirms payment.
- Final release creates the renewed permit and marks the source permit as `renewed`.

## Backend Routes

- `GET /admin/api/renewals`
- `GET /admin/api/renewals/summary`
- `POST /admin/api/renewals/run-daily`
- `GET/PATCH /admin/api/renewal/settings`
- `POST /admin/api/renewal/deadline-extensions`
- `POST /admin/api/renewal/requirements`
- `POST /admin/api/renewals/{applicationId}/assessment/calculate`
- `POST /treasury/api/renewals/{applicationId}/assessment/finalize`
- `GET /treasury/api/renewals/{applicationId}/assessment`
- `POST /admin/api/renewal-assessments/{assessmentId}/void`
- `POST /applicant/api/permits/{permitId}/renew`

## Key Files

- Schema and RLS: `database/17. annual_business_permit_renewals.sql`
- Renewal rules and API handlers: `backend/renewal_service.py`
- Permit validity/release updates: `backend/permit_service.py`
- Payment completion updates: `backend/treasury_routes.py`
- Applicant permit renewal UI: `static/features/applicant_self_service.js`
- Staff monitoring UI: `static/templates/staff_administrator/renewal_application.html`, `static/features/staff_renewals.js`
- Scheduler: `scripts/run_renewal_daily.py`
- Tests: `tests/test_annual_renewals.py`
