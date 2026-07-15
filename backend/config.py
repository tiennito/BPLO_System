from pathlib import Path
import os

try:
    import pytesseract
except ImportError:
    pytesseract = None

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
ENV_FILE = BASE_DIR / ".env"

if pytesseract is not None and os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def load_env():
    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()

HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", "8000"))
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(STATIC_DIR / "uploads"))
ALLOWED_FILE_TYPES = {"pdf", "png", "jpg", "jpeg", "gif", "webp"}

PAGE_ROUTES = {
    "/": "/templates/login.html",
    "/login": "/templates/login.html",
    "/login.html": "/templates/login.html",
    "/register": "/templates/register.html",
    "/signup": "/templates/register.html",
    "/register.html": "/templates/register.html",
    "/applicant": "/templates/applicant/dashboard.html",
    "/applicant/": "/templates/applicant/dashboard.html",
    "/applicant/dashboard": "/templates/applicant/dashboard.html",
    "/applicant/dashboard/": "/templates/applicant/dashboard.html",
    "/applicant/dashboard.html": "/templates/applicant/dashboard.html",
    "/applicant/permits": "/templates/applicant/permits.html",
    "/applicant/permits/": "/templates/applicant/permits.html",
    "/applicant/permits.html": "/templates/applicant/permits.html",
    "/applicant/documents": "/templates/applicant/documents.html",
    "/applicant/documents/": "/templates/applicant/documents.html",
    "/applicant/documents.html": "/templates/applicant/documents.html",
    "/applicant/profile": "/templates/applicant/profile.html",
    "/applicant/profile/": "/templates/applicant/profile.html",
    "/applicant/profile.html": "/templates/applicant/profile.html",
    "/applicant/business-permit": "/templates/applicant/business_permit.html",
    "/applicant/business-permit/": "/templates/applicant/business_permit.html",
    "/applicant/business-permit.html": "/templates/applicant/business_permit.html",
    "/applicant/application-type": "/templates/applicant/application_type.html",
    "/applicant/application-type/": "/templates/applicant/application_type.html",
    "/applicant/application-type.html": "/templates/applicant/application_type.html",
    "/applicant/new-application": "/templates/applicant/new_application.html",
    "/applicant/new-application/": "/templates/applicant/new_application.html",
    "/applicant/new-application.html": "/templates/applicant/new_application.html",
    "/applicant/business-information": "/templates/applicant/business_information.html",
    "/applicant/business-information/": "/templates/applicant/business_information.html",
    "/applicant/business-information.html": "/templates/applicant/business_information.html",
    "/admin": "/templates/admin/dashboard.html",
    "/admin/": "/templates/admin/dashboard.html",
    "/admin/dashboard": "/templates/admin/dashboard.html",
    "/admin/dashboard/": "/templates/admin/dashboard.html",
    "/admin/dashboard.html": "/templates/admin/dashboard.html",
    "/admin/staff-administrator": "/templates/staff_administrator/staff_administrator.html",
    "/admin/staff-administrator/": "/templates/staff_administrator/staff_administrator.html",
    "/admin/staff-administrator.html": "/templates/staff_administrator/staff_administrator.html",
    "/admin/staff-administrator/applications": "/templates/staff_administrator/applications.html",
    "/admin/staff-administrator/applications/": "/templates/staff_administrator/applications.html",
    "/admin/staff-administrator/applications.html": "/templates/staff_administrator/applications.html",
    "/admin/staff-administrator/renewal-application": "/templates/staff_administrator/renewal_application.html",
    "/admin/staff-administrator/renewal-application/": "/templates/staff_administrator/renewal_application.html",
    "/admin/staff-administrator/renewal-application.html": "/templates/staff_administrator/renewal_application.html",
    "/admin/staff-administrator/notifications": "/templates/staff_administrator/notifications.html",
    "/admin/staff-administrator/notifications/": "/templates/staff_administrator/notifications.html",
    "/admin/staff-administrator/notifications.html": "/templates/staff_administrator/notifications.html",
    "/admin/staff-administrator/reports": "/templates/staff_administrator/reports.html",
    "/admin/staff-administrator/reports/": "/templates/staff_administrator/reports.html",
    "/admin/staff-administrator/reports.html": "/templates/staff_administrator/reports.html",
    "/admin/staff-administrator/business-classifications": "/templates/staff_administrator/business_classifications.html",
    "/admin/staff-administrator/business-classifications/": "/templates/staff_administrator/business_classifications.html",
    "/admin/staff-administrator/business-classifications.html": "/templates/staff_administrator/business_classifications.html",
    "/admin/create-user": "/templates/admin/create_user.html",
    "/admin/create-user/": "/templates/admin/create_user.html",
    "/admin/create-user.html": "/templates/admin/create_user.html",
    "/admin/create-permit": "/templates/admin/create_permit.html",
    "/admin/create-permit/": "/templates/admin/create_permit.html",
    "/admin/create-permit.html": "/templates/admin/create_permit.html",
    "/admin/users": "/templates/admin/users.html",
    "/admin/users/": "/templates/admin/users.html",
    "/admin/user-list": "/templates/admin/users.html",
    "/admin/user-list/": "/templates/admin/users.html",
    "/admin/users.html": "/templates/admin/users.html",
    "/admin/departments": "/templates/admin/departments.html",
    "/admin/departments/": "/templates/admin/departments.html",
    "/admin/departments.html": "/templates/admin/departments.html",
    "/admin/audit-logs": "/templates/admin/audit_logs.html",
    "/admin/audit-logs/": "/templates/admin/audit_logs.html",
    "/admin/audit-logs.html": "/templates/admin/audit_logs.html",
    "/department": "/templates/department_office/dashboard.html",
    "/department/": "/templates/department_office/dashboard.html",
    "/department/dashboard": "/templates/department_office/dashboard.html",
    "/department/dashboard/": "/templates/department_office/dashboard.html",
    "/department/applications": "/templates/department_office/applications.html",
    "/department/applications/": "/templates/department_office/applications.html",
    "/department/application-details": "/templates/department_office/application_details.html",
    "/department/application-details/": "/templates/department_office/application_details.html",
    "/department/permit-requirements": "/templates/department_office/permit_requirements.html",
    "/department/permit-requirements/": "/templates/department_office/permit_requirements.html",
    "/department/site-inspections": "/templates/department_office/site_inspections.html",
    "/department/site-inspections/": "/templates/department_office/site_inspections.html",
    "/department/reports": "/templates/department_office/reports.html",
    "/department/reports/": "/templates/department_office/reports.html",
    "/department/settings": "/templates/department_office/settings.html",
    "/department/settings/": "/templates/department_office/settings.html",
    "/treasury": "/templates/treasury_office/dashboard.html",
    "/treasury/": "/templates/treasury_office/dashboard.html",
    "/treasury/dashboard": "/templates/treasury_office/dashboard.html",
    "/treasury/dashboard/": "/templates/treasury_office/dashboard.html",
    "/treasury/processing": "/templates/treasury_office/processing.html",
    "/treasury/processing/": "/templates/treasury_office/processing.html",
    "/treasury/payment-records": "/templates/treasury_office/payment_records.html",
    "/treasury/payment-records/": "/templates/treasury_office/payment_records.html",
    "/treasury/official-receipts": "/templates/treasury_office/official_receipts.html",
    "/treasury/official-receipts/": "/templates/treasury_office/official_receipts.html",
    "/treasury/reports": "/templates/treasury_office/reports.html",
    "/treasury/reports/": "/templates/treasury_office/reports.html",
    "/treasury/settings": "/templates/treasury_office/settings.html",
    "/treasury/settings/": "/templates/treasury_office/settings.html",
}
