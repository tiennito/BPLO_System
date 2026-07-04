from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import os
import re
import tempfile
import uuid

import cv2
import fitz
import numpy as np
import pytesseract
from PIL import Image, ImageOps


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ENV_FILE = BASE_DIR / ".env"

if os.name == "nt":
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


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_role(value):
    role = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "admin": "bplo_admin",
        "administrator": "bplo_admin",
        "department": "department_office",
        "department_user": "department_office",
        "department_office_user": "department_office",
        "treasury_office": "treasury",
        "treasury_user": "treasury",
        "client": "applicant",
    }
    return aliases.get(role, role)


def profile_status(value):
    status = (value or "active").strip().lower()
    return status if status in {"active", "inactive", "pending", "disabled"} else "active"


def dashboard_path_for_role(role):
    paths = {
        "super_admin": "/admin/dashboard",
        "bplo_admin": "/admin/staff-administrator",
        "department_office": "/department/dashboard",
        "treasury": "/treasury/dashboard",
        "applicant": "/applicant/dashboard",
    }
    return paths.get(normalize_role(role))


def slugify_key(value):
    normalized = []
    previous_was_separator = False
    for character in (value or "").strip().lower():
        if character.isalnum():
            normalized.append(character)
            previous_was_separator = False
        elif not previous_was_separator:
            normalized.append("_")
            previous_was_separator = True
    return "".join(normalized).strip("_")


def department_key_from_name(name):
    key = slugify_key(name)
    for suffix in ("_office", "_department"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    seeded_aliases = {
        "health_sanitary": "health",
        "zoning_mpdc": "zoning",
        "fire": "fire",
        "engineering": "engineering",
    }
    return seeded_aliases.get(key, key)


def normalize_business_classification_value(value):
    value = (value or "").strip()
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"\s+", " ", value).strip().upper()
    value = re.sub(r"\s*/\s*", " / ", value)
    value = re.sub(r"\s*-\s*", " - ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_business_classification_key(value):
    value = normalize_business_classification_value(value).replace("&", " AND ")
    value = re.sub(r"\bBAKE\s+SHOP\b", "BAKESHOP", value)
    value = re.sub(r"\bPHONE\s+CARDS\b", "PHONECARDS", value)
    value = re.sub(r"\bSMALL\s+LOT\b", "SMALLLOT", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", "8000"))
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


class AppHandler(SimpleHTTPRequestHandler):
    FIELD_LABELS = {
        "business_name": [
            r"business\s*name",
            r"name\s*of\s*business",
        ],
        "trade_name": [
            r"trade\s*name",
            r"tradename",
        ],
        "tin": [
            r"tin",
            r"tax\s*identification\s*number",
            r"taxpayer\s*identification\s*number",
        ],
        "business_address": [
            r"business\s*address",
            r"business\s*location",
            r"business\s*office\s*address",
        ],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        request_path = urlsplit(self.path).path

        if request_path == "/department/api/me":
            self.get_department_profile()
            return

        if request_path == "/department/api/applications":
            self.list_department_applications()
            return

        workspace_match = re.fullmatch(r"/department/api/applications/([^/]+)/workspace", request_path)
        if workspace_match:
            self.get_department_application_workspace(workspace_match.group(1))
            return

        if request_path.startswith("/department/api/applications/"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 4:
                self.get_department_application(parts[-1])
                return

        if request_path == "/department/api/requirements":
            self.list_department_requirements()
            return

        if request_path == "/department/api/inspections":
            self.list_department_inspections()
            return

        if request_path == "/department/api/reports":
            self.list_department_reports()
            return

        if request_path == "/department/api/settings":
            self.get_department_settings()
            return

        if request_path == "/treasury/api/me":
            self.get_treasury_profile()
            return

        if request_path == "/treasury/api/records":
            self.list_treasury_records()
            return

        if request_path == "/treasury/api/payment-queue":
            self.list_treasury_payment_queue()
            return

        if request_path == "/api/me/profile":
            self.get_current_user_profile()
            return

        if request_path == "/api/business-classifications":
            self.list_business_classifications()
            return

        if request_path == "/admin/api/users":
            self.list_admin_users()
            return

        if request_path == "/admin/api/departments":
            self.list_admin_departments()
            return

        if request_path == "/admin/api/audit-logs":
            self.list_admin_audit_logs()
            return

        if request_path == "/admin/api/applications":
            self.list_admin_applications()
            return

        if request_path.startswith("/admin/api/applications/"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 4:
                self.get_admin_application_review(parts[-1])
                return
            if len(parts) == 5 and parts[-1] == "assessment":
                self.get_admin_application_assessment(parts[-2])
                return

        if request_path.startswith("/admin/application-documents/") and request_path.endswith("/preview"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 4:
                self.preview_admin_application_document(parts[2])
                return

        if request_path == "/admin/api/business-classifications":
            self.list_admin_business_classifications()
            return

        if request_path == "/admin/api/permits":
            self.list_admin_permits()
            return

        if request_path.startswith("/admin/api/permits/"):
            permit_id = request_path.rsplit("/", 1)[-1]
            self.get_admin_permit(permit_id)
            return

        if request_path == "/applicant/api/permits":
            self.list_applicant_permits()
            return

        if request_path == "/applicant/api/notifications":
            self.list_applicant_notifications()
            return

        if request_path.startswith("/applicant/api/application/") and request_path.endswith("/ocr-fields"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.get_applicant_application_ocr_fields(parts[3])
                return

        if request_path.startswith("/applicant/api/permits/"):
            permit_id = request_path.rsplit("/", 1)[-1]
            self.get_applicant_permit(permit_id)
            return

        if request_path == "/config.js":
            supabase_url = os.getenv("SUPABASE_URL", "")
            supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
            supabase_publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
            admin_email = os.getenv("ADMIN_EMAIL", "")
            payload = (
                "window.APP_CONFIG = "
                f"{{supabaseUrl: {supabase_url!r}, supabaseAnonKey: {supabase_anon_key!r}, "
                f"supabasePublishableKey: {supabase_publishable_key!r}, adminEmail: {admin_email!r}}};"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        if re.fullmatch(r"/admin/staff-administrator/applications/[^/]+/?", request_path):
            self.path = "/templates/staff_administrator/application_review.html"
        else:
            self.path = PAGE_ROUTES.get(request_path, request_path)
        super().do_GET()

    def do_POST(self):
        request_path = urlsplit(self.path).path

        if request_path == "/department/api/requirements":
            self.create_department_requirement()
            return

        if request_path == "/department/api/inspections":
            self.create_department_inspection()
            return

        if request_path == "/department/api/inspection-notifications":
            self.send_department_inspection_notification()
            return

        assessment_match = re.fullmatch(r"/department/api/applications/([^/]+)/assessment", request_path)
        if assessment_match:
            self.upsert_department_assessment(assessment_match.group(1))
            return

        if request_path == "/department/api/remarks":
            self.create_department_remark()
            return

        if request_path == "/department/api/verifications":
            self.create_department_verification()
            return

        if request_path == "/department/api/reports":
            self.create_department_report()
            return

        if request_path == "/department/api/settings":
            self.upsert_department_settings()
            return

        if request_path == "/treasury/api/records":
            self.create_treasury_record()
            return

        if request_path.startswith("/treasury/api/payment-queue/") and request_path.endswith("/confirm"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.confirm_treasury_payment(parts[-2])
                return

        if request_path.startswith("/treasury/api/records/") and request_path.endswith("/print-notify"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.notify_treasury_print_complete(parts[-2])
                return

        if request_path.startswith("/treasury/api/records/") and request_path.endswith("/sync-completion"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.sync_treasury_record_completion(parts[-2])
                return

        if request_path == "/admin/api/users":
            self.create_admin_user()
            return

        if request_path == "/admin/api/departments":
            self.create_admin_department()
            return

        if request_path == "/admin/api/permits":
            self.create_admin_permit()
            return

        if request_path.startswith("/admin/api/applications/"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5 and parts[-1] == "approve-initial-review":
                self.approve_admin_initial_review(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "reject":
                self.reject_admin_application(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "request-revision":
                self.request_admin_application_revision(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "complete-assessment":
                self.complete_admin_assessment(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "finalize":
                self.finalize_admin_application(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "release-permit":
                self.release_admin_business_permit(parts[-2])
                return

        if request_path == "/admin/api/document-reviews":
            self.create_admin_document_review()
            return

        if request_path == "/admin/api/assessment-items":
            self.create_admin_assessment_item()
            return

        if request_path == "/admin/api/business-classifications":
            self.create_admin_business_classification()
            return

        if request_path == "/applicant/api/applications":
            self.start_applicant_application()
            return

        if request_path == "/applicant/api/application-documents":
            self.update_applicant_application_document()
            return

        if request_path == "/applicant/api/ocr-extract":
            self.extract_applicant_document_ocr()
            return

        if request_path == "/applicant/api/submit-application":
            self.submit_applicant_application()
            return

        if request_path == "/api/audit-logs":
            self.create_audit_log()
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def do_PATCH(self):
        request_path = urlsplit(self.path).path

        if request_path.startswith("/department/api/applications/") and request_path.endswith("/evaluation"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.update_department_application_evaluation(parts[3])
                return

        if request_path.startswith("/department/api/requirements/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_department_requirement(record_id)
            return

        if request_path.startswith("/department/api/inspections/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_department_inspection(record_id)
            return

        if request_path.startswith("/department/api/verifications/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_department_verification(record_id)
            return

        if request_path.startswith("/department/api/reports/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_department_report(record_id)
            return

        if request_path == "/department/api/settings":
            self.upsert_department_settings()
            return

        if request_path.startswith("/treasury/api/records/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_treasury_record(record_id)
            return

        if request_path == "/applicant/api/notifications/mark-all-read":
            self.mark_all_applicant_notifications_read()
            return

        if request_path.startswith("/applicant/api/notifications/") and request_path.endswith("/read"):
            notification_id = request_path.strip("/").split("/")[-2]
            self.mark_applicant_notification_read(notification_id)
            return

        if request_path.startswith("/admin/api/departments/"):
            department_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_department(department_id)
            return

        if request_path.startswith("/admin/api/permits/"):
            permit_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_permit(permit_id)
            return

        if request_path.startswith("/admin/api/business-classifications/"):
            classification_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_business_classification(classification_id)
            return

        if request_path.startswith("/admin/api/document-reviews/"):
            review_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_document_review(review_id)
            return

        if request_path.startswith("/admin/api/assessment-items/"):
            item_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_assessment_item(item_id)
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def do_DELETE(self):
        request_path = urlsplit(self.path).path

        if request_path.startswith("/department/api/requirements/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_department_record("department_requirement_checklists", record_id, "requirement_deleted")
            return

        if request_path.startswith("/department/api/inspections/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_department_record("department_inspections", record_id, "inspection_deleted")
            return

        if request_path.startswith("/department/api/remarks/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_department_record("department_remarks", record_id, "remark_deleted")
            return

        if request_path.startswith("/department/api/reports/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_department_record("department_reports", record_id, "report_deleted")
            return

        if request_path == "/department/api/settings":
            self.delete_department_settings()
            return

        if request_path.startswith("/treasury/api/records/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_treasury_record(record_id)
            return

        if request_path.startswith("/applicant/api/notifications/"):
            notification_id = request_path.rsplit("/", 1)[-1]
            self.delete_applicant_notification(notification_id)
            return

        if request_path.startswith("/admin/api/departments/"):
            department_id = request_path.rsplit("/", 1)[-1]
            self.delete_admin_department(department_id)
            return

        if request_path.startswith("/admin/api/permits/"):
            permit_id = request_path.rsplit("/", 1)[-1]
            self.delete_admin_permit(permit_id)
            return

        if request_path.startswith("/admin/api/assessment-items/"):
            item_id = request_path.rsplit("/", 1)[-1]
            self.delete_admin_assessment_item(item_id)
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}

        raw_body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw_body)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def download_storage_file(self, supabase_url, service_key, bucket, file_path):
        encoded_path = quote(file_path, safe="/")
        request = Request(
            f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{encoded_path}",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
        )

        with urlopen(request, timeout=30) as response:
            return response.read()

    def content_type_for_filename(self, filename):
        extension = Path(filename or "").suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
        }.get(extension, "application/octet-stream")

    def preview_admin_application_document(self, document_id):
        config = self.ensure_admin_request("document preview")
        if not config:
            return

        supabase_url, service_key = config
        document_id = (document_id or "").strip()
        if not document_id:
            self.send_json({"error": "Document id is required."}, status=400)
            return

        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "application_documents",
                {
                    "select": "id,file_url,file_name,upload_status",
                    "id": f"eq.{document_id}",
                    "limit": 1,
                },
            ) or []
            if not rows:
                self.send_json({"error": "Document not found."}, status=404)
                return

            document = rows[0]
            file_path = document.get("file_url") or ""
            file_name = document.get("file_name") or Path(file_path).name or "document"
            if not file_path:
                self.send_json({"error": "No uploaded file is attached to this document."}, status=404)
                return

            file_bytes = self.download_storage_file(supabase_url, service_key, "application-documents", file_path)
            content_type = self.content_type_for_filename(file_name)
            disposition_name = file_name.replace('"', "")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(file_bytes)))
            self.send_header("Content-Disposition", f'inline; filename="{disposition_name}"')
            self.end_headers()
            self.wfile.write(file_bytes)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to preview document.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to preview document."}, status=500)

    def prepare_ocr_image_variants(self, image):
        image = ImageOps.exif_transpose(image).convert("RGB")
        rgb = np.array(image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        height, width = gray.shape[:2]
        scale = max(1.0, min(4.0, 1800 / max(width, height)))
        if scale > 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        denoised = cv2.fastNlMeansDenoising(gray, None, 18, 7, 21)
        clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(denoised)
        blur = cv2.GaussianBlur(clahe, (3, 3), 0)
        _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )

        variants = [
            Image.fromarray(gray),
            Image.fromarray(clahe),
            Image.fromarray(otsu),
            Image.fromarray(adaptive),
            Image.fromarray(cv2.bitwise_not(otsu)),
        ]

        enlarged_variants = []
        for variant in variants:
            enlarged_variants.append(variant)
            enlarged_variants.append(variant.resize((variant.width * 2, variant.height * 2), Image.Resampling.LANCZOS))

        return enlarged_variants

    def ocr_image_to_text(self, image):
        configs = [
            "--oem 3 --psm 6",
            "--oem 3 --psm 11",
            "--oem 3 --psm 7",
        ]
        texts = []
        seen = set()

        for variant in self.prepare_ocr_image_variants(image):
            for config in configs:
                try:
                    text = pytesseract.image_to_string(variant, config=config)
                except Exception:
                    continue
                text = self.clean_ocr_text(text)
                key = self.flatten_ocr_text(text).lower()
                if text and key not in seen:
                    seen.add(key)
                    texts.append(text)

        return "\n".join(texts)

    def extract_text_from_file(self, file_name, file_bytes):
        file_name_lower = (file_name or "").lower()

        if file_name_lower.endswith(".pdf"):
            document = fitz.open(stream=file_bytes, filetype="pdf")
            extracted_pages = []

            for page in document:
                pix = page.get_pixmap(dpi=260)
                image_bytes = pix.tobytes("png")
                image = Image.open(BytesIO(image_bytes))
                text = self.ocr_image_to_text(image)
                extracted_pages.append(text)

            return "\n".join(extracted_pages)

        image = Image.open(BytesIO(file_bytes))
        return self.ocr_image_to_text(image)

    BAD_BUSINESS_NAME_WORDS = [
        "registration",
        "issued",
        "issue",
        "republic",
        "philippines",
        "secretary",
        "certificate",
        "department",
        "trade and industry",
        "department of trade",
        "pursuant",
        "valid",
        "business name registration",
        "this is to certify",
        "le ma",
        "cristina",
        "roque",
    ]

    def clean_ocr_text(self, text):
        text = (text or "").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n+", "\n", text)
        return text.strip()

    def flatten_ocr_text(self, text):
        return re.sub(r"\s+", " ", text or "").strip()

    def get_all_label_patterns(self):
        labels = []
        for patterns in self.FIELD_LABELS.values():
            labels.extend(patterns)
        return labels

    def build_all_labels_regex(self):
        return "|".join(f"(?:{pattern})" for pattern in self.get_all_label_patterns())

    def normalize_ocr_text(self, raw_text):
        text = self.clean_ocr_text(raw_text)
        for label_pattern in self.get_all_label_patterns():
            text = re.sub(
                rf"(?i)\b({label_pattern})\b\s*[:\-]?",
                r"\n\1: ",
                text,
            )
        text = re.sub(r"\n+", "\n", text)
        return text.strip()

    def find_first_match(self, patterns, text):
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip(" :,-")
        return ""

    def clean_extracted_value(self, value):
        if not value:
            return None

        value = str(value).strip()
        value = re.sub(r"\s+", " ", value)
        value = value.replace("|", "")
        value = value.replace("\u201c", "")
        value = value.replace("\u201d", "")
        value = value.strip(" :;-")
        return value.strip() or None

    def clean_extracted_ocr_value(self, value):
        return self.clean_extracted_value(re.sub(r"[:|_]+", " ", str(value or ""))) or ""

    def extract_value_by_label(self, text, label_patterns):
        all_labels_regex = self.build_all_labels_regex()
        current_label_regex = "|".join(f"(?:{pattern})" for pattern in label_patterns)
        pattern = rf"""
            (?:^|\n)\s*
            (?:{current_label_regex})
            \s*[:\-]?\s*
            (.*?)
            (?=
                \n\s*(?:{all_labels_regex})\s*[:\-]?
                |
                $
            )
        """
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL | re.VERBOSE)
        if not match:
            return None
        return self.clean_extracted_value(match.group(1))

    def contains_known_label(self, value):
        if not value:
            return False
        all_labels_regex = self.build_all_labels_regex()
        return re.search(rf"\b(?:{all_labels_regex})\b", str(value), re.IGNORECASE) is not None

    def is_valid_business_name(self, value):
        if not value:
            return False
        value = str(value).strip()
        if len(value) > 100:
            return False
        if self.contains_known_label(value):
            return False

        bad_words = [
            "certificate",
            "registration",
            "republic",
            "philippines",
            "department",
            "secretary",
            "issued",
            "valid",
        ]
        lower = value.lower()
        return not any(word in lower for word in bad_words)

    def clean_tin(self, value):
        if not value:
            return None

        match = re.search(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3}(?:[-\s]?\d{3})?\b", str(value))
        if not match:
            return None

        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) == 9:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:9]}"
        if len(digits) == 12:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:9]}-{digits[9:12]}"
        return None

    def is_valid_address(self, value):
        if not value:
            return False

        value = str(value).strip()
        if len(value) < 5 or len(value) > 250:
            return False
        if self.contains_known_label(value):
            return False
        return True

    def validate_business_info_fields(self, fields):
        validated = {}

        business_name = self.clean_extracted_value(fields.get("business_name"))
        trade_name = self.clean_extracted_value(fields.get("trade_name"))
        tin = self.clean_tin(fields.get("tin"))
        business_address = self.clean_extracted_value(fields.get("business_address"))

        if self.is_valid_business_name(business_name):
            validated["business_name"] = business_name.upper()

        if trade_name and len(trade_name) <= 100 and not self.contains_known_label(trade_name):
            validated["trade_name"] = trade_name.upper()

        if tin:
            validated["tin"] = tin

        if self.is_valid_address(business_address):
            validated["business_address"] = business_address.upper()

        return validated

    def score_field(self, field_name, value):
        if not value:
            return 0.0
        if self.contains_known_label(value):
            return 0.2
        if field_name == "tin":
            return 0.95 if self.clean_tin(value) else 0.3
        if field_name == "business_name":
            return 0.9 if self.is_valid_business_name(value) else 0.3
        if field_name == "business_address":
            return 0.85 if self.is_valid_address(value) else 0.3
        return 0.8

    def build_confidence(self, fields):
        return {
            field_name: self.score_field(field_name, value)
            for field_name, value in fields.items()
        }

    def parse_business_info_document(self, raw_text):
        text = self.normalize_ocr_text(raw_text)
        fields = {
            "business_name": self.extract_value_by_label(text, self.FIELD_LABELS["business_name"]),
            "trade_name": self.extract_value_by_label(text, self.FIELD_LABELS["trade_name"]),
            "tin": self.extract_value_by_label(text, self.FIELD_LABELS["tin"]),
            "business_address": self.extract_value_by_label(text, self.FIELD_LABELS["business_address"]),
        }
        fields = self.validate_business_info_fields(fields)
        if not fields:
            return {}

        confidence = self.build_confidence(fields)
        fields["field_confidence"] = confidence
        fields["confidence"] = confidence
        fields["confidence_score"] = round(sum(confidence.values()) / len(confidence), 2)
        fields["parser_version"] = "business_info_v1"
        return fields

    def field_confidence_value(self, value, confidence):
        return {
            "value": value,
            "confidence": confidence,
        }

    def extract_labeled_ocr_value(self, labels, lines, flattened_text, stop_labels=None):
        stop_labels = stop_labels or [
            "Name of Owner",
            "Name of Business",
            "Business Name",
            "Business Address",
            "TIN",
            "Date Issued",
            "TOTAL SALES",
            "Total Sales",
        ]
        stop_pattern = "|".join(re.escape(label) for label in stop_labels)

        for label_pattern, confidence in labels:
            same_line_pattern = re.compile(rf"{label_pattern}\s*[:\-|]?\s*(.+)", re.IGNORECASE)
            for index, line in enumerate(lines):
                match = same_line_pattern.search(line)
                if match:
                    value = self.clean_extracted_ocr_value(match.group(1))
                    if value:
                        return value, confidence
                    if index + 1 < len(lines):
                        next_value = self.clean_extracted_ocr_value(lines[index + 1])
                        if next_value:
                            return next_value, max(confidence - 8, 70)

            block_match = re.search(
                rf"{label_pattern}\s*[:\-|]?\s*(.+?)(?:\s+(?:{stop_pattern})\b|$)",
                flattened_text,
                re.IGNORECASE,
            )
            if block_match:
                value = self.clean_extracted_ocr_value(block_match.group(1))
                if value:
                    return value, max(confidence - 5, 70)

        return "", 0

    def is_bad_business_name_candidate(self, value):
        if not value:
            return True

        value = re.sub(r"\s+", " ", str(value)).strip()
        value_lower = value.lower()
        if len(value_lower) < 3 or len(value_lower) > 80:
            return True

        if not re.search(r"[a-z]", value_lower):
            return True

        if re.search(r"\b(?:no|number)\.?\s*\d", value_lower):
            return True

        if re.fullmatch(r"(?:no\.?\s*)?[a-z0-9\-]{4,}", value_lower) and sum(character.isalpha() for character in value_lower) <= 2:
            return True

        return any(bad_word in value_lower for bad_word in self.BAD_BUSINESS_NAME_WORDS)

    def normalize_business_name(self, value):
        if not value:
            return ""

        value = re.sub(r"\s+", " ", value).strip(" :,-")
        stop_words = [
            "Owner",
            "Proprietor",
            "Registrant",
            "Business Address",
            "Certificate",
            "Registration",
            "Date",
            "Issued",
            "This is to certify",
        ]
        for stop in stop_words:
            value = re.sub(rf"\b{re.escape(stop)}\b.*", "", value, flags=re.IGNORECASE).strip()

        value = value.upper()
        value = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", value)
        value = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", value)
        value = re.sub(r"(?<=[A-Z])5(?=[A-Z])", "S", value)
        value = re.sub(r"(?<=[A-Z])8(?=[A-Z])", "B", value)
        return value

    def is_valid_gross_sales_business_name(self, value):
        if self.is_bad_business_name_candidate(value):
            return False

        value_lower = str(value or "").lower()
        address_words = ["street", "st.", "brgy", "barangay", "laguna", "province", "city", "municipality"]
        label_words = ["name of business", "business name", "business address", "name of owner", "tin"]
        if any(word in value_lower for word in address_words + label_words):
            return False

        return True

    def is_valid_business_address_candidate(self, value):
        value = str(value or "").strip()
        if len(value) < 8 or len(value) > 180:
            return False
        if self.contains_known_label(value):
            return False
        lowered = value.lower()
        location_words = ["street", "st.", "brgy", "barangay", "victoria", "laguna", "city", "municipality", "province", "road", "ave"]
        return any(word in lowered for word in location_words)

    def is_valid_tin_candidate(self, value):
        return bool(re.fullmatch(r"\d{3}-?\d{3}-?\d{3}(?:-?\d{3})?", str(value or "").strip()))

    def is_valid_sales_candidate(self, value):
        normalized = str(value or "").replace(",", "").strip()
        return bool(re.fullmatch(r"\d+(?:\.\d{1,2})?", normalized))

    def parse_gross_sales_certificate_fields(self, raw_text):
        text = self.clean_ocr_text(raw_text)
        flattened_text = self.flatten_ocr_text(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        fields = {}
        confidence = {}

        owner_name, owner_confidence = self.extract_labeled_ocr_value(
            [
                (r"Name\s+of\s+Owner", 95),
                (r"Owner\s+Name", 88),
                (r"\bOwner\b", 78),
            ],
            lines,
            flattened_text,
        )
        if owner_name and len(owner_name) <= 90:
            owner_name = self.normalize_business_name(owner_name)
            fields["owner_name"] = owner_name
            fields.update(self.split_owner_name(owner_name))
            confidence["owner_name"] = owner_confidence

        business_name, business_confidence = self.extract_labeled_ocr_value(
            [
                (r"Name\s+of\s+Business", 96),
                (r"Business\s+Name", 94),
                (r"Name\s+Business", 88),
                (r"Name\s+of\s+Buslness", 86),
                (r"Name\s+of\s+Busmess", 86),
            ],
            lines,
            flattened_text,
        )
        business_name = self.normalize_business_name(business_name)
        if business_name and self.is_valid_gross_sales_business_name(business_name):
            fields["business_name"] = business_name
            fields["businessName"] = business_name
            fields["business_name_confidence"] = "high" if business_confidence >= 90 else "medium"
            confidence["business_name"] = business_confidence
            confidence["businessName"] = business_confidence
        else:
            fields["business_name_confidence"] = "low"

        business_address, address_confidence = self.extract_labeled_ocr_value(
            [
                (r"Business\s+Address", 95),
                (r"Address\s+of\s+Business", 88),
                (r"\bAddress\b", 76),
            ],
            lines,
            flattened_text,
        )
        if business_address and self.is_valid_business_address_candidate(business_address):
            fields["business_address"] = business_address
            fields["businessAddress"] = business_address
            confidence["business_address"] = address_confidence
            confidence["businessAddress"] = address_confidence

        tin, tin_confidence = self.extract_labeled_ocr_value(
            [
                (r"\bTIN\b", 96),
                (r"Tax\s+Identification\s+Number", 90),
            ],
            lines,
            flattened_text,
        )
        tin_match = re.search(r"\d{3}-?\d{3}-?\d{3}(?:-?\d{3})?", tin or flattened_text)
        if tin_match:
            tin_value = tin_match.group(0)
            if self.is_valid_tin_candidate(tin_value):
                fields["tin"] = tin_value
                confidence["tin"] = tin_confidence or 80

        date_issued, date_confidence = self.extract_labeled_ocr_value(
            [
                (r"Date\s+Issued", 95),
                (r"Issued\s+Date", 88),
                (r"Date\s+of\s+Issue", 86),
            ],
            lines,
            flattened_text,
        )
        if date_issued:
            fields["date_issued"] = date_issued
            fields["dateIssued"] = date_issued
            confidence["date_issued"] = date_confidence
            confidence["dateIssued"] = date_confidence

        gross_sales, sales_confidence = self.extract_labeled_ocr_value(
            [
                (r"TOTAL\s+SALES", 96),
                (r"Total\s+Sales", 96),
                (r"Gross\s+Sales", 92),
                (r"Sales", 74),
            ],
            lines,
            flattened_text,
        )
        sales_match = re.search(r"\d[\d,]*(?:\.\d{1,2})?", gross_sales or "")
        if not sales_match:
            sales_match = re.search(r"(?:TOTAL\s+SALES|Total\s+Sales|Gross\s+Sales)\D+(\d[\d,]*(?:\.\d{1,2})?)", flattened_text, re.IGNORECASE)
            sales_value = sales_match.group(1) if sales_match else ""
        else:
            sales_value = sales_match.group(0)
        sales_value = sales_value.replace(",", "")
        if sales_value and self.is_valid_sales_candidate(sales_value):
            fields["gross_sales"] = sales_value
            fields["grossSales"] = sales_value
            fields["goods_value"] = sales_value
            confidence["gross_sales"] = sales_confidence or 86
            confidence["grossSales"] = sales_confidence or 86
            confidence["goods_value"] = sales_confidence or 86

        fields["field_confidence"] = confidence
        if confidence:
            fields["confidence_score"] = round(sum(confidence.values()) / len(confidence), 2)

        return fields

    def parse_dti_fields(self, raw_text):
        text = self.clean_ocr_text(raw_text)
        flattened_text = self.flatten_ocr_text(text)
        fields = {}
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        business_name_candidates = []
        owner_name = ""

        for index, line in enumerate(lines):
            if re.search(r"certificate\s+issued\s+to|issued\s+to", line, re.IGNORECASE):
                for next_line in lines[index + 1 : index + 4]:
                    candidate_owner = self.normalize_business_name(next_line)
                    if candidate_owner and len(candidate_owner) <= 80 and not self.is_bad_business_name_candidate(candidate_owner):
                        owner_name = candidate_owner
                        break
                break

        owner_match = re.search(
            r"(?:owner|proprietor|registrant)\s*[:\-]?\s*(.+)",
            text,
            re.IGNORECASE,
        )
        if owner_match:
            matched_owner = self.normalize_business_name(owner_match.group(1))
            if matched_owner and len(matched_owner) <= 80:
                owner_name = matched_owner

        if owner_name:
            fields["owner_name"] = owner_name
            fields.update(self.split_owner_name(owner_name))

        for line in lines:
            match = re.search(r"business\s*name\s*[:\-]?\s*(.+)", line, re.IGNORECASE)
            if match:
                candidate = self.normalize_business_name(match.group(1))
                if candidate != owner_name and not self.is_bad_business_name_candidate(candidate):
                    business_name_candidates.append((candidate, "high"))

        for index, line in enumerate(lines):
            if not re.search(r"certif(?:y|ies)\s+that", line, re.IGNORECASE):
                continue

            for next_line in lines[index + 1 : index + 6]:
                candidate = self.normalize_business_name(next_line)
                if not candidate or candidate == owner_name or self.is_bad_business_name_candidate(candidate):
                    continue
                if re.search(r"^\([^)]+\)$", candidate):
                    continue
                if re.search(r"\b(REGION|CALABARZON|LAGUNA|PROVINCE|CITY|MUNICIPALITY|BARANGAY|BRGY)\b", candidate, re.IGNORECASE):
                    continue
                business_name_candidates.append((candidate, "high"))
                break

        sentence_match = re.search(
            r"certif(?:y|ies)\s+that\s+(.+?)(?:\s+\([^)]+\))?\s+(?:is\s+a\s+business\s+name\s+registered|is|has been)\s+(?:registered|granted)?",
            flattened_text,
            re.IGNORECASE,
        )
        if sentence_match:
            candidate = self.normalize_business_name(sentence_match.group(1))
            candidate = re.sub(r"\s+\([^)]+\).*$", "", candidate).strip()
            candidate = re.sub(r"\b(REGION|CALABARZON|LAGUNA|PROVINCE|CITY|MUNICIPALITY|BARANGAY|BRGY)\b.*", "", candidate, flags=re.IGNORECASE).strip()
            if candidate != owner_name and not self.is_bad_business_name_candidate(candidate):
                business_name_candidates.append((candidate, "high"))

        before_owner_section = True
        for line in lines:
            if re.search(r"certificate\s+issued\s+to|issued\s+to|valid\s+from|in\s+testimony", line, re.IGNORECASE):
                before_owner_section = False
            if not before_owner_section:
                continue

            candidate = self.normalize_business_name(line)
            if candidate == owner_name or self.is_bad_business_name_candidate(candidate):
                continue

            uppercase_ratio = sum(1 for character in candidate if character.isupper()) / max(len(candidate), 1)
            if uppercase_ratio > 0.5 and len(candidate.split()) >= 2:
                business_name_candidates.append((candidate, "medium"))

        if business_name_candidates:
            business_name, confidence = sorted(business_name_candidates, key=lambda item: (item[1] != "high", len(item[0])))[0]
            fields["business_name"] = business_name
            fields["business_name_confidence"] = confidence
        else:
            fields["business_name_confidence"] = "low"

        registration_number = self.find_first_match(
            [
                r"(?:certificate\s+no\.?|registration\s+no\.?|business\s+name\s+no\.?|dti\s+registration\s+no\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
            ],
            flattened_text,
        )
        if registration_number:
            fields["registration_number"] = registration_number
            fields["dti_registration_no"] = registration_number

        business_address = self.find_first_match(
            [
                r"(?:Business Address|Business Location|Address)\s*[:\-]?\s*(.+?)(?: Owner| Proprietor| Registrant| Registration| Certificate|$)",
            ],
            flattened_text,
        )
        if business_address:
            fields["business_address"] = re.sub(r"\s+", " ", business_address).strip(" :,-")

        registration_date = self.find_first_match(
            [
                r"(?:Registration Date|Date Registered|Date of Registration|Issued on)\s*[:\-]?\s*([A-Za-z0-9 ,/\-]+?)(?: Business| Owner| Address|$)",
            ],
            flattened_text,
        )
        if registration_date:
            fields["registration_date"] = registration_date

        business_type = self.find_first_match(
            [
                r"\b(SINGLE|SOLE PROPRIETORSHIP|PARTNERSHIP|CORPORATION|COOPERATIVE)\b",
            ],
            flattened_text,
        )
        if business_type:
            fields["type_of_business"] = "SINGLE" if business_type.upper() == "SOLE PROPRIETORSHIP" else business_type.upper()
            fields["business_type"] = fields["type_of_business"]

        return fields

    def normalize_handwritten_ocr_line(self, line):
        line = str(line or "")
        replacements = {
            "8USINESS": "BUSINESS",
            "BVSINESS": "BUSINESS",
            "BUSlNESS": "BUSINESS",
            "BUS1NESS": "BUSINESS",
            "BUSl NESS": "BUSINESS",
            "B U S I N E S S": "BUSINESS",
            "NANE": "NAME",
            "MAME": "NAME",
            "NAHE": "NAME",
        }
        normalized = line.upper()
        for wrong, right in replacements.items():
            normalized = normalized.replace(wrong, right)
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"\bBUSI\s+NESS\b", "BUSINESS", normalized)
        normalized = re.sub(r"\bBUS\s*INESS\b", "BUSINESS", normalized)
        return normalized.strip()

    def parse_freeform_business_fields(self, raw_text):
        text = self.clean_ocr_text(raw_text)
        flattened_text = self.flatten_ocr_text(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        candidates = []

        label_patterns = [
            r"(?:business|bus1ness|busi\s*ness|bvsiness|8usiness)\s*(?:name|nane|mame|nahe)",
            r"(?:name\s+of\s+business|name\s+business)",
            r"(?:trade\s+name)",
        ]

        for line in lines:
            normalized_line = self.normalize_handwritten_ocr_line(line)
            for label_pattern in label_patterns:
                match = re.search(rf"{label_pattern}\s*[:\-|]?\s*(.+)", normalized_line, re.IGNORECASE)
                if match:
                    candidate = self.normalize_business_name(match.group(1))
                    if candidate and not self.is_bad_business_name_candidate(candidate):
                        candidates.append(candidate)

        normalized_flattened = self.normalize_handwritten_ocr_line(flattened_text)
        for label_pattern in label_patterns:
            match = re.search(
                rf"{label_pattern}\s*[:\-|]?\s*(.+?)(?:\s+(?:OWNER|PROPRIETOR|ADDRESS|TIN|REGISTRATION|PERMIT|DATE)\b|$)",
                normalized_flattened,
                re.IGNORECASE,
            )
            if match:
                candidate = self.normalize_business_name(match.group(1))
                if candidate and not self.is_bad_business_name_candidate(candidate):
                    candidates.append(candidate)

        if not candidates:
            return {}

        business_name = sorted(set(candidates), key=lambda value: (-len(value.split()), len(value)))[0]
        return {
            "business_name": business_name,
            "businessName": business_name,
            "business_name_confidence": "medium",
            "field_confidence": {
                "business_name": 78,
                "businessName": 78,
            },
        }

    def split_owner_name(self, owner_name):
        parts = (owner_name or "").strip().split()
        if len(parts) >= 2:
            return {
                "first_name": parts[0],
                "middle_name": " ".join(parts[1:-1]),
                "last_name": parts[-1],
            }
        if parts:
            return {"first_name": parts[0]}
        return {}

    def normalize_extracted_business_fields(self, fields):
        alias_map = {
            "date_of_application": "application_date",
            "dti_registration_no": "registration_number",
            "dti_registration_number": "registration_number",
            "registration_no": "registration_number",
            "certificate_no": "registration_number",
            "owner_first_name": "first_name",
            "owner_middle_name": "middle_name",
            "owner_last_name": "last_name",
            "registered_email": "email",
            "registered_contact_number": "contact_number",
            "business_type": "type_of_business",
            "business_types": "type_of_business",
            "capital_investment": "capitalization",
            "ownerName": "owner_name",
            "businessName": "business_name",
            "businessAddress": "business_address",
            "dateIssued": "date_issued",
            "grossSales": "gross_sales",
            "gross_sales": "goods_value",
        }
        metadata_keys = {"field_confidence", "fieldConfidence", "confidence", "confidence_score", "parser_version"}
        normalized = {}

        for key, value in (fields or {}).items():
            if value in (None, ""):
                continue

            if key in metadata_keys:
                normalized[key] = value
                continue

            normalized_key = alias_map.get(key, key)
            normalized[normalized_key] = value

            if key != normalized_key:
                normalized[key] = value

        owner_name = normalized.get("owner_name")
        if owner_name:
            for key, value in self.split_owner_name(owner_name).items():
                normalized.setdefault(key, value)

        return normalized

    def get_ocr_field_confidence_number(self, fields, key):
        confidence_aliases = {
            "business_name": ["business_name", "businessName"],
            "trade_name": ["trade_name", "tradeName"],
            "tin": ["tin"],
            "business_address": ["business_address", "businessAddress"],
            "goods_value": ["goods_value", "gross_sales", "grossSales"],
            "date_issued": ["date_issued", "dateIssued"],
            "owner_name": ["owner_name", "ownerName"],
        }
        confidence_map = fields.get("field_confidence") or fields.get("fieldConfidence") or fields.get("confidence") or {}
        for confidence_key in confidence_aliases.get(key, [key]):
            if confidence_key in confidence_map:
                value = confidence_map.get(confidence_key)
                if isinstance(value, (int, float)):
                    return float(value) * 100 if 0 < float(value) <= 1 else float(value)
                level = str(value or "").lower()
                if level == "high":
                    return 95
                if level == "medium":
                    return 80
                if level == "low":
                    return 0

        direct_value = fields.get(f"{key}_confidence")
        if isinstance(direct_value, (int, float)):
            return float(direct_value) * 100 if 0 < float(direct_value) <= 1 else float(direct_value)
        level = str(direct_value or "").lower()
        if level == "high":
            return 95
        if level == "medium":
            return 80
        if level == "low":
            return 0

        return 0

    def merge_extracted_ocr_fields(self, merged_fields, incoming_fields):
        incoming = self.normalize_extracted_business_fields(incoming_fields or {})
        confidence_map = merged_fields.setdefault("field_confidence", {})
        incoming_confidence = incoming.get("field_confidence") or {}
        metadata_keys = {"field_confidence", "fieldConfidence", "confidence", "confidence_score", "parser_version"}

        for key, value in incoming.items():
            if key in metadata_keys or key.endswith("_confidence") or value in (None, ""):
                continue

            if key == "business_name":
                owner_name = incoming.get("owner_name") or merged_fields.get("owner_name")
                if owner_name and self.normalize_business_name(value) == self.normalize_business_name(owner_name):
                    continue
                if not self.is_valid_gross_sales_business_name(value):
                    continue
                value = self.normalize_business_name(value)

            if key == "trade_name":
                value = self.clean_extracted_value(value)
                if not value or len(value) > 100 or self.contains_known_label(value):
                    continue

            if key == "tin":
                value = self.clean_tin(value)
                if not value:
                    continue

            if key == "business_address":
                value = self.clean_extracted_value(value)
                if not self.is_valid_address(value):
                    continue

            incoming_score = self.get_ocr_field_confidence_number(incoming, key)
            existing_value = merged_fields.get(key)
            existing_score = self.get_ocr_field_confidence_number(merged_fields, key)

            if not existing_value or incoming_score >= existing_score:
                merged_fields[key] = value
                if incoming_score:
                    confidence_map[key] = incoming_score

        for key, value in incoming_confidence.items():
            normalized_key = self.normalize_extracted_business_fields({key: "x"})
            confidence_key = next((candidate for candidate, candidate_value in normalized_key.items() if candidate_value == "x"), key)
            if isinstance(value, (int, float)) and value > confidence_map.get(confidence_key, 0):
                confidence_map[confidence_key] = value

        for key, value in incoming.items():
            if key.endswith("_confidence") and key not in merged_fields:
                merged_fields[key] = value

        return merged_fields

    def extract_business_fields_from_text(self, raw_text, document_type=""):
        text = self.clean_ocr_text(raw_text)
        flattened_text = self.flatten_ocr_text(text)
        document_type_lower = (document_type or "").lower()
        business_info_fields = self.parse_business_info_document(raw_text)
        freeform_fields = self.parse_freeform_business_fields(raw_text)

        def with_freeform_fallback(fields):
            fields = dict(fields or {})
            if freeform_fields:
                if not fields.get("business_name") and freeform_fields.get("business_name"):
                    fields["business_name"] = freeform_fields["business_name"]
                    fields["businessName"] = freeform_fields["business_name"]
                    fields["business_name_confidence"] = freeform_fields.get("business_name_confidence", "medium")
                confidence = fields.setdefault("field_confidence", {})
                for key, value in (freeform_fields.get("field_confidence") or {}).items():
                    confidence.setdefault(key, value)

            if business_info_fields:
                for key in ("business_name", "trade_name", "tin", "business_address"):
                    if business_info_fields.get(key):
                        fields[key] = business_info_fields[key]
                        if key == "business_name":
                            fields["businessName"] = business_info_fields[key]
                        if key == "business_address":
                            fields["businessAddress"] = business_info_fields[key]

                confidence = fields.setdefault("field_confidence", {})
                for key, value in (business_info_fields.get("field_confidence") or {}).items():
                    confidence[key] = value

                fields["confidence"] = business_info_fields.get("confidence", {})
                fields["confidence_score"] = business_info_fields.get("confidence_score")
                fields["parser_version"] = business_info_fields.get("parser_version", "business_info_v1")
            return self.normalize_extracted_business_fields(fields)

        is_gross_sales_certificate = (
            "gross" in document_type_lower
            or "sales" in document_type_lower
            or "certification" in document_type_lower
            or "name of business" in flattened_text.lower()
            or "total sales" in flattened_text.lower()
        )
        if is_gross_sales_certificate:
            return with_freeform_fallback(self.parse_gross_sales_certificate_fields(raw_text))

        if "dti" in document_type_lower or "business name" in flattened_text.lower():
            return with_freeform_fallback(self.parse_dti_fields(raw_text))

        extracted = {
            "registration_number": self.find_first_match(
                [
                    r"(?:Registration No\.?|Reg\.? No\.?|Certificate No\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
                    r"(?:DTI No\.?|SEC No\.?|CDA No\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
                    r"(?:DTI Registration No\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
                ],
                flattened_text,
            ),
            "trade_name": self.find_first_match(
                [
                    r"(?:Trade Name)\s*[:\-]?\s*([A-Za-z0-9 &.,'\-]+?)(?: Owner| Proprietor| Address| Registration|$)",
                ],
                flattened_text,
            ),
            "tin": self.find_first_match(
                [
                    r"(?:TIN|Tax Identification Number)\s*[:\-]?\s*([0-9\-]+)",
                ],
                flattened_text,
            ),
            "business_address": self.find_first_match(
                [
                    r"(?:Business Address|Business Location|Address)\s*[:\-]?\s*([A-Za-z0-9 #.,'\-]+?)(?: Barangay| Owner| Registration|$)",
                ],
                flattened_text,
            ),
            "registration_date": self.find_first_match(
                [
                    r"(?:Registration Date|Date Registered|Date of Registration)\s*[:\-]?\s*([A-Za-z0-9 ,/\-]+?)(?: Business| Owner| Address|$)",
                ],
                flattened_text,
            ),
            "type_of_business": self.find_first_match(
                [
                    r"\b(SINGLE|SOLE PROPRIETORSHIP|PARTNERSHIP|CORPORATION|COOPERATIVE)\b",
                ],
                flattened_text,
            ),
            "first_name": "",
            "middle_name": "",
            "last_name": "",
            "business_name_confidence": "low",
        }

        business_name = self.find_first_match(
            [
                r"(?:Business Name|Trade Name)\s*[:\-]?\s*([A-Za-z0-9 &.,'\-]+?)(?: Owner| Proprietor| Address| Registration|$)",
            ],
            flattened_text,
        )
        business_name = self.normalize_business_name(business_name)
        if business_name and not self.is_bad_business_name_candidate(business_name):
            extracted["business_name"] = business_name
            extracted["business_name_confidence"] = "medium"

        owner_name = self.find_first_match(
            [
                r"(?:Owner|Proprietor|Registrant|Applicant Name)\s*[:\-]?\s*([A-Za-z .,'\-]+?)(?: Address| Business| Registration|$)",
            ],
            flattened_text,
        )

        if owner_name:
            extracted["owner_name"] = owner_name
            extracted.update(self.split_owner_name(owner_name))

        if extracted.get("type_of_business") == "SOLE PROPRIETORSHIP":
            extracted["type_of_business"] = "SINGLE"

        extracted = {key: value for key, value in extracted.items() if value}
        if extracted.get("registration_number"):
            extracted["dti_registration_no"] = extracted["registration_number"]
        if extracted.get("type_of_business"):
            extracted["business_type"] = extracted["type_of_business"]

        return with_freeform_fallback(extracted)

    def verify_admin_session(self, access_token, supabase_url, supabase_client_key, supabase_service_key, admin_email):
        if not access_token:
            return False

        user = self.get_session_user(access_token, supabase_url, supabase_client_key)
        return self.user_has_admin_access(user, supabase_url, supabase_service_key, admin_email)

    def user_has_admin_access(self, user, supabase_url, supabase_service_key, admin_email):
        signed_in_email = (user.get("email") or "").lower()
        if admin_email and signed_in_email == admin_email.lower():
            return True

        profile = self.get_profile_by_auth_user_id(supabase_url, supabase_service_key, user.get("id"))
        if not profile or profile_status(profile.get("status")) != "active":
            return False
        return normalize_role(profile.get("role")) in {"super_admin", "bplo_admin"}

    def get_session_user(self, access_token, supabase_url, supabase_client_key):
        request = Request(
            f"{supabase_url.rstrip('/')}/auth/v1/user",
            headers={
                "apikey": supabase_client_key,
                "Authorization": f"Bearer {access_token}",
            },
        )

        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def delete_auth_user(self, supabase_url, supabase_service_key, user_id):
        if not user_id:
            return False

        request = Request(
            f"{supabase_url.rstrip('/')}/auth/v1/admin/users/{quote(user_id)}",
            method="DELETE",
            headers={
                "apikey": supabase_service_key,
                "Authorization": f"Bearer {supabase_service_key}",
            },
        )
        try:
            with urlopen(request, timeout=10):
                return True
        except (HTTPError, URLError, TimeoutError):
            return False

    def format_profile(self, profile, department=None):
        first_name = profile.get("first_name") or ""
        middle_name = profile.get("middle_name") or ""
        last_name = profile.get("last_name") or ""
        suffix = profile.get("suffix") or ""
        full_name = " ".join(part for part in [first_name, middle_name, last_name, suffix] if part).strip()
        role = normalize_role(profile.get("role"))
        status = profile_status(profile.get("status"))
        department = department or {}
        department_name = department.get("name") or profile.get("department_name") or "-"
        department_key = profile.get("department_key") or department_key_from_name(department_name)

        return {
            "id": profile.get("id"),
            "authUserId": profile.get("auth_user_id"),
            "name": full_name or profile.get("email") or "Unnamed user",
            "firstName": first_name,
            "middleName": middle_name,
            "lastName": last_name,
            "suffix": suffix,
            "email": profile.get("email") or "",
            "contactNumber": profile.get("contact_number") or "",
            "role": role,
            "departmentId": profile.get("department_id"),
            "department": department_name,
            "departmentKey": department_key,
            "status": status,
            "createdBy": profile.get("created_by"),
            "createdAt": profile.get("created_at") or "",
            "updatedAt": profile.get("updated_at") or "",
        }

    def load_department_by_id(self, supabase_url, supabase_service_key, department_id):
        if not department_id:
            return None
        query = urlencode({"select": "id,name,status", "id": f"eq.{department_id}", "limit": "1"})
        rows = self.service_rest_request(
            {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
            "departments",
            query=query,
        ) or []
        return rows[0] if rows else None

    def get_profile_by_auth_user_id(self, supabase_url, supabase_service_key, auth_user_id):
        if not auth_user_id:
            return None
        query = urlencode(
            {
                "select": "*",
                "auth_user_id": f"eq.{auth_user_id}",
                "limit": "1",
            }
        )
        rows = self.service_rest_request(
            {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
            "profiles",
            query=query,
        ) or []
        return rows[0] if rows else None

    def get_profile_by_email(self, supabase_url, supabase_service_key, email):
        if not email:
            return None
        query = urlencode({"select": "*", "email": f"eq.{email.lower()}", "limit": "1"})
        rows = self.service_rest_request(
            {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
            "profiles",
            query=query,
        ) or []
        return rows[0] if rows else None

    def find_department_for_profile(self, supabase_url, supabase_service_key, department_name="", department_key=""):
        departments = self.service_rest_request(
            {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
            "departments",
            query=urlencode({"select": "id,name,status", "status": "eq.Active"}),
        ) or []
        wanted_key = department_key or department_key_from_name(department_name)
        wanted_name = (department_name or "").strip().lower()
        for department in departments:
            name = (department.get("name") or "").strip()
            if wanted_key and department_key_from_name(name) == wanted_key:
                return department
            if wanted_name and name.lower() == wanted_name:
                return department
        return None

    def create_profile_record(self, supabase_url, supabase_service_key, profile_payload):
        rows = self.service_rest_request(
            {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
            "profiles",
            method="POST",
            payload=profile_payload,
            prefer="return=representation",
        ) or []
        return rows[0] if rows else None

    def update_profile_record(self, supabase_url, supabase_service_key, profile_id, profile_payload):
        if not profile_id:
            return None
        rows = self.service_rest_request(
            {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
            "profiles",
            method="PATCH",
            payload=profile_payload,
            query=urlencode({"id": f"eq.{profile_id}"}),
            prefer="return=representation",
        ) or []
        return rows[0] if rows else None

    def profile_payload_from_auth_user(self, user, role=None, status="active", department_id=None, created_by=None):
        metadata = user.get("user_metadata") or {}
        app_metadata = user.get("app_metadata") or {}
        role = normalize_role(role or app_metadata.get("role") or metadata.get("role") or "applicant")
        department_name = app_metadata.get("department_name") or app_metadata.get("department") or ""
        department_key = app_metadata.get("department_key") or department_key_from_name(department_name)
        return {
            "auth_user_id": user.get("id"),
            "first_name": metadata.get("first_name") or "",
            "middle_name": metadata.get("middle_name") or "",
            "last_name": metadata.get("last_name") or "",
            "suffix": metadata.get("suffix") or "",
            "email": (user.get("email") or "").lower(),
            "contact_number": metadata.get("contact_number") or "",
            "role": role,
            "department_id": department_id or app_metadata.get("department_id") or None,
            "department_key": department_key or None,
            "department_name": department_name or None,
            "status": profile_status(status or app_metadata.get("status")),
            "created_by": created_by,
        }

    def ensure_profile_for_user(self, supabase_url, supabase_service_key, user, admin_email=""):
        profile = self.get_profile_by_auth_user_id(supabase_url, supabase_service_key, user.get("id"))
        signed_in_email = (user.get("email") or "").lower()
        if profile:
            if admin_email and signed_in_email == admin_email.lower():
                needs_admin_repair = (
                    normalize_role(profile.get("role")) != "super_admin"
                    or profile_status(profile.get("status")) != "active"
                )
                if needs_admin_repair:
                    repaired = self.update_profile_record(
                        supabase_url,
                        supabase_service_key,
                        profile.get("id"),
                        {"role": "super_admin", "status": "active"},
                    )
                    if repaired:
                        print(
                            "[auth] admin profile repaired",
                            json.dumps(
                                {
                                    "profileId": repaired.get("id"),
                                    "authUserId": repaired.get("auth_user_id"),
                                    "email": repaired.get("email"),
                                    "role": repaired.get("role"),
                                    "status": repaired.get("status"),
                                }
                            ),
                        )
                        return repaired
            return profile

        role = "super_admin" if admin_email and signed_in_email == admin_email.lower() else None
        payload = self.profile_payload_from_auth_user(user, role=role)
        if payload.get("role") == "department_office" and not payload.get("department_id"):
            department = self.find_department_for_profile(
                supabase_url,
                supabase_service_key,
                payload.get("department_name") or "",
                payload.get("department_key") or "",
            )
            if department:
                payload["department_id"] = department.get("id")
                payload["department_name"] = department.get("name")
                payload["department_key"] = department_key_from_name(department.get("name"))
        return self.create_profile_record(supabase_url, supabase_service_key, payload)

    def get_current_user_profile(self):
        supabase_url, supabase_client_key, supabase_service_key, admin_email = self.get_admin_api_config()
        if not supabase_url or not supabase_client_key or not supabase_service_key:
            self.send_json({"error": "Profile access is not configured."}, status=500)
            return

        auth_header = self.headers.get("Authorization", "")
        access_token = auth_header.removeprefix("Bearer ").strip()
        if not access_token:
            self.send_json({"error": "No active login session was found."}, status=401)
            return

        try:
            user = self.get_session_user(access_token, supabase_url, supabase_client_key)
            profile = self.ensure_profile_for_user(supabase_url, supabase_service_key, user, admin_email)
            if not profile:
                self.send_json({"error": "No user profile was found for this account."}, status=404)
                return

            department = self.load_department_by_id(supabase_url, supabase_service_key, profile.get("department_id"))
            formatted = self.format_profile(profile, department)
            redirect_path = dashboard_path_for_role(formatted["role"])
            print(
                "[auth] profile fetched",
                json.dumps(
                    {
                        "authUserId": formatted["authUserId"],
                        "email": formatted["email"],
                        "role": formatted["role"],
                        "status": formatted["status"],
                        "redirectPath": redirect_path,
                    }
                ),
            )
            self.send_json({"profile": formatted, "redirectPath": redirect_path})
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or "Unable to load user profile."
            if error.code in {401, 403} and "profiles" not in message:
                message = "Invalid or expired session."
            self.send_json({"error": message}, status=401 if error.code in {401, 403} else error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load user profile."}, status=500)

    def create_service_audit_log(
        self,
        supabase_url,
        supabase_service_key,
        action,
        actor=None,
        entity_type=None,
        entity_id=None,
        details=None,
    ):
        actor = actor or {}
        payload = {
            "actor_user_id": actor.get("id"),
            "actor_email": actor.get("email"),
            "actor_role": ((actor.get("app_metadata") or {}).get("role") or "user"),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details or {},
            "ip_address": self.client_address[0] if self.client_address else None,
            "user_agent": self.headers.get("User-Agent"),
        }
        request = Request(
            f"{supabase_url.rstrip('/')}/rest/v1/audit_logs",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "apikey": supabase_service_key,
                "Authorization": f"Bearer {supabase_service_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )

        try:
            with urlopen(request, timeout=10):
                return True
        except (HTTPError, URLError, TimeoutError):
            return False

    def create_admin_user(self):
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        supabase_client_key = (
            os.getenv("SUPABASE_ANON_KEY", "").strip()
            or os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        )
        supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        admin_email = os.getenv("ADMIN_EMAIL", "").strip()

        if not supabase_url or not supabase_client_key or not supabase_service_key or not admin_email:
            self.send_json(
                {
                    "error": (
                        "Admin user creation is not configured. Set SUPABASE_URL, "
                        "SUPABASE_ANON_KEY or SUPABASE_PUBLISHABLE_KEY, "
                        "SUPABASE_SERVICE_ROLE_KEY, and ADMIN_EMAIL in .env."
                    )
                },
                status=500,
            )
            return

        try:
            auth_header = self.headers.get("Authorization", "")
            access_token = auth_header.removeprefix("Bearer ").strip()

            if not self.verify_admin_session(
                access_token, supabase_url, supabase_client_key, supabase_service_key, admin_email
            ):
                self.send_json({"error": "Only the configured admin can create users."}, status=403)
                return
            actor = self.get_session_user(access_token, supabase_url, supabase_client_key)

            payload = self.read_json_body()
            email = (payload.get("email") or "").strip()
            password = payload.get("password") or ""
            role = normalize_role(payload.get("role"))

            if not email or not password or not role:
                self.send_json({"error": "Email, password, and role are required."}, status=400)
                return

            if role not in {"super_admin", "bplo_admin", "department_office", "treasury", "applicant"}:
                self.send_json({"error": "Select a valid user role."}, status=400)
                return

            if self.get_profile_by_email(supabase_url, supabase_service_key, email):
                self.send_json({"error": "A profile already exists for this email address."}, status=409)
                return

            user_metadata = {
                "first_name": (payload.get("firstName") or "").strip(),
                "last_name": (payload.get("lastName") or "").strip(),
                "middle_name": (payload.get("middleName") or "").strip(),
                "suffix": (payload.get("suffix") or "").strip(),
                "contact_number": (payload.get("contactNumber") or "").strip(),
            }
            app_metadata = {"role": role, "status": "active"}
            department_id = None
            department_name = ""
            department_key = ""

            if role == "department_office":
                department_id = (payload.get("departmentId") or "").strip() or None
                department_name = (payload.get("departmentName") or "").strip()
                department_key = (payload.get("departmentKey") or "").strip()

                if department_id:
                    department_query = urlencode(
                        {
                            "select": "id,name,status",
                            "id": f"eq.{department_id}",
                            "limit": "1",
                        }
                    )
                    departments = self.service_rest_request(
                        {
                            "supabase_url": supabase_url,
                            "supabase_service_key": supabase_service_key,
                        },
                        "departments",
                        query=department_query,
                    ) or []
                    department = departments[0] if departments else None
                    if not department:
                        self.send_json({"error": "Selected department was not found."}, status=400)
                        return
                    if department.get("status") != "Active":
                        self.send_json({"error": "Selected department is inactive."}, status=400)
                        return
                    department_name = department.get("name") or department_name
                else:
                    self.send_json({"error": "Department Office users must be assigned to an active department."}, status=400)
                    return

                department_key = department_key or department_key_from_name(department_name)
                if not department_name or not department_key:
                    self.send_json({"error": "Department Office users must be assigned to an active department."}, status=400)
                    return

                app_metadata.update(
                    {
                        "department_id": department_id,
                        "department_key": department_key,
                        "department_name": department_name,
                        "department": department_name,
                    }
                )

            if role == "treasury":
                app_metadata["office"] = "Treasury Office"

            create_payload = {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": user_metadata,
                "app_metadata": app_metadata,
            }
            request_body = json.dumps(create_payload).encode("utf-8")
            request = Request(
                f"{supabase_url.rstrip('/')}/auth/v1/admin/users",
                data=request_body,
                method="POST",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                    "Content-Type": "application/json",
                },
            )

            with urlopen(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8"))

            print(
                "[auth] auth user created",
                json.dumps({"authUserId": response_payload.get("id"), "email": response_payload.get("email"), "role": role}),
            )
            profile_payload = {
                "auth_user_id": response_payload.get("id"),
                "first_name": user_metadata["first_name"],
                "middle_name": user_metadata["middle_name"],
                "last_name": user_metadata["last_name"],
                "suffix": user_metadata["suffix"],
                "email": email.lower(),
                "contact_number": user_metadata["contact_number"],
                "role": role,
                "department_id": department_id,
                "department_key": department_key or None,
                "department_name": department_name or None,
                "status": "active",
                "created_by": actor.get("id"),
            }
            try:
                profile = self.create_profile_record(supabase_url, supabase_service_key, profile_payload)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                rolled_back = self.delete_auth_user(
                    supabase_url,
                    supabase_service_key,
                    response_payload.get("id"),
                )
                raise RuntimeError(
                    "Authentication account was created, but the centralized profile could not be saved. "
                    f"Auth rollback {'succeeded' if rolled_back else 'failed'}."
                )

            if not profile:
                rolled_back = self.delete_auth_user(supabase_url, supabase_service_key, response_payload.get("id"))
                raise RuntimeError(
                    "Authentication account was created, but no centralized profile was returned. "
                    f"Auth rollback {'succeeded' if rolled_back else 'failed'}."
                )

            print(
                "[auth] profile inserted",
                json.dumps(
                    {
                        "profileId": profile.get("id"),
                        "authUserId": profile.get("auth_user_id"),
                        "email": profile.get("email"),
                        "role": profile.get("role"),
                        "status": profile.get("status"),
                    }
                ),
            )
            audit_logged = self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "user_created_by_admin",
                actor=actor,
                entity_type="user",
                entity_id=profile.get("id"),
                details={"email": response_payload.get("email"), "role": role, "authUserId": response_payload.get("id")},
            )

            self.send_json(
                {
                    "message": "User account created successfully.",
                    "userId": response_payload.get("id"),
                    "profileId": profile.get("id"),
                    "email": response_payload.get("email"),
                    "auditLogged": audit_logged,
                },
                status=201,
            )
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("msg") or response_payload.get("message") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to create user."}, status=500)
        except RuntimeError as error:
            self.send_json({"error": str(error)}, status=500)

    def get_admin_api_config(self):
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        supabase_client_key = (
            os.getenv("SUPABASE_ANON_KEY", "").strip()
            or os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        )
        supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        admin_email = os.getenv("ADMIN_EMAIL", "").strip()

        return supabase_url, supabase_client_key, supabase_service_key, admin_email

    def ensure_admin_request(self, action_label):
        supabase_url, supabase_client_key, supabase_service_key, admin_email = self.get_admin_api_config()

        if not supabase_url or not supabase_client_key or not supabase_service_key or not admin_email:
            self.send_json(
                {
                    "error": (
                        f"Admin {action_label} is not configured. Set SUPABASE_URL, "
                        "SUPABASE_ANON_KEY or SUPABASE_PUBLISHABLE_KEY, "
                        "SUPABASE_SERVICE_ROLE_KEY, and ADMIN_EMAIL in .env."
                    )
                },
                status=500,
            )
            return None

        auth_header = self.headers.get("Authorization", "")
        access_token = auth_header.removeprefix("Bearer ").strip()

        if not self.verify_admin_session(
            access_token, supabase_url, supabase_client_key, supabase_service_key, admin_email
        ):
            self.send_json({"error": "Only the configured admin can manage this area."}, status=403)
            return None

        return supabase_url, supabase_service_key

    def ensure_authenticated_request(self):
        supabase_url, supabase_client_key, supabase_service_key, _admin_email = self.get_admin_api_config()

        if not supabase_url or not supabase_client_key or not supabase_service_key:
            self.send_json(
                {
                    "error": (
                        "Audit logging is not configured. Set SUPABASE_URL, "
                        "SUPABASE_ANON_KEY or SUPABASE_PUBLISHABLE_KEY, and "
                        "SUPABASE_SERVICE_ROLE_KEY in .env."
                    )
                },
                status=500,
            )
            return None

        auth_header = self.headers.get("Authorization", "")
        access_token = auth_header.removeprefix("Bearer ").strip()

        if not access_token:
            self.send_json({"error": "A signed-in user is required for audit logging."}, status=401)
            return None

        try:
            actor = self.get_session_user(access_token, supabase_url, supabase_client_key)
        except HTTPError:
            self.send_json({"error": "Invalid or expired session."}, status=401)
            return None

        return supabase_url, supabase_service_key, actor

    def format_auth_user(self, user):
        user_metadata = user.get("user_metadata") or {}
        app_metadata = user.get("app_metadata") or {}
        first_name = user_metadata.get("first_name") or ""
        last_name = user_metadata.get("last_name") or ""
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        role = normalize_role(app_metadata.get("role") or user_metadata.get("role") or "applicant") or "applicant"
        department = (
            app_metadata.get("department_name")
            or app_metadata.get("department")
            or user_metadata.get("department")
            or "-"
        )
        email_confirmed = bool(user.get("email_confirmed_at") or user.get("confirmed_at"))
        banned_until = user.get("banned_until")

        if banned_until:
            status = "Disabled"
        elif email_confirmed:
            status = "Active"
        else:
            status = "Pending"

        return {
            "id": user.get("id"),
            "name": full_name or user.get("email") or "Unnamed user",
            "firstName": first_name,
            "lastName": last_name,
            "middleName": user_metadata.get("middle_name") or "",
            "suffix": user_metadata.get("suffix") or "",
            "contactNumber": user_metadata.get("contact_number") or "",
            "email": user.get("email") or "",
            "role": role,
            "department": department,
            "status": status,
            "createdAt": user.get("created_at") or "",
            "updatedAt": user.get("updated_at") or "",
            "lastSignInAt": user.get("last_sign_in_at") or "",
            "emailConfirmedAt": user.get("email_confirmed_at") or user.get("confirmed_at") or "",
            "bannedUntil": banned_until or "",
            "appMetadata": app_metadata,
            "userMetadata": user_metadata,
        }

    def list_admin_users(self):
        config = self.ensure_admin_request("user listing")
        if not config:
            return

        supabase_url, supabase_service_key = config
        query_string = urlencode({"select": "*", "order": "created_at.desc"})

        try:
            profiles = self.service_rest_request(
                {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
                "profiles",
                query=query_string,
            ) or []
            department_ids = sorted({profile.get("department_id") for profile in profiles if profile.get("department_id")})
            departments_by_id = {}
            if department_ids:
                departments = self.service_rest_request(
                    {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
                    "departments",
                    query=urlencode(
                        {
                            "select": "id,name,status",
                            "id": f"in.({','.join(department_ids)})",
                        }
                    ),
                ) or []
                departments_by_id = {department.get("id"): department for department in departments}

            users = [
                self.format_profile(profile, departments_by_id.get(profile.get("department_id")))
                for profile in profiles
            ]
            self.send_json({"users": users, "total": len(users)})
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load users."}, status=500)

    def list_auth_users_legacy(self):
        config = self.ensure_admin_request("legacy auth user listing")
        if not config:
            return

        supabase_url, supabase_service_key = config
        query_string = urlencode({"page": 1, "per_page": 1000})

        try:
            request = Request(
                f"{supabase_url.rstrip('/')}/auth/v1/admin/users?{query_string}",
                method="GET",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                },
            )

            with urlopen(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8"))

            raw_users = response_payload.get("users")
            if raw_users is None and isinstance(response_payload, list):
                raw_users = response_payload

            users = [self.format_auth_user(user) for user in raw_users or []]
            self.send_json({"users": users, "total": len(users)})
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("msg") or response_payload.get("message") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load users."}, status=500)

    def format_department(self, department):
        return {
            "id": department.get("id"),
            "name": department.get("name") or "",
            "description": department.get("description") or "",
            "status": department.get("status") or "Active",
            "createdAt": department.get("created_at") or "",
        }

    def list_admin_departments(self):
        config = self.ensure_admin_request("department listing")
        if not config:
            return

        supabase_url, supabase_service_key = config
        query_string = urlencode({"select": "id,name,description,status,created_at", "order": "created_at.desc"})

        try:
            request = Request(
                f"{supabase_url.rstrip('/')}/rest/v1/departments?{query_string}",
                method="GET",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                },
            )

            with urlopen(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8"))

            departments = [self.format_department(department) for department in response_payload or []]
            self.send_json({"departments": departments, "total": len(departments)})
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load departments."}, status=500)

    def create_admin_department(self):
        config = self.ensure_admin_request("department creation")
        if not config:
            return

        supabase_url, supabase_service_key = config

        try:
            payload = self.read_json_body()
            name = (payload.get("name") or "").strip()
            description = (payload.get("description") or "").strip()
            status = (payload.get("status") or "Active").strip()

            if not name:
                self.send_json({"error": "Department name is required."}, status=400)
                return

            if status not in {"Active", "Inactive"}:
                self.send_json({"error": "Department status must be Active or Inactive."}, status=400)
                return

            request_body = json.dumps(
                {"name": name, "description": description, "status": status}
            ).encode("utf-8")
            request = Request(
                f"{supabase_url.rstrip('/')}/rest/v1/departments",
                data=request_body,
                method="POST",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
            )

            with urlopen(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8"))

            department = response_payload[0] if response_payload else {}
            auth_header = self.headers.get("Authorization", "")
            access_token = auth_header.removeprefix("Bearer ").strip()
            actor = self.get_session_user(
                access_token,
                supabase_url,
                os.getenv("SUPABASE_ANON_KEY", "").strip()
                or os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip(),
            )
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "department_created",
                actor=actor,
                entity_type="department",
                entity_id=department.get("id"),
                details={"name": department.get("name"), "status": department.get("status")},
            )
            self.send_json(
                {
                    "message": "Department created successfully.",
                    "department": self.format_department(department),
                },
                status=201,
            )
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to create department."}, status=500)

    def get_request_actor(self, supabase_url):
        auth_header = self.headers.get("Authorization", "")
        access_token = auth_header.removeprefix("Bearer ").strip()
        supabase_client_key = (
            os.getenv("SUPABASE_ANON_KEY", "").strip()
            or os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        )
        return self.get_session_user(access_token, supabase_url, supabase_client_key)

    def validate_department_payload(self, payload, require_name=True):
        name = (payload.get("name") or "").strip()
        description = (payload.get("description") or "").strip()
        status = (payload.get("status") or "Active").strip()

        if require_name and not name:
            raise ValueError("Department name is required.")

        if status not in {"Active", "Inactive"}:
            raise ValueError("Department status must be Active or Inactive.")

        return {
            "name": name,
            "description": description,
            "status": status,
        }

    def update_admin_department(self, department_id):
        config = self.ensure_admin_request("department update")
        if not config:
            return

        if not department_id:
            self.send_json({"error": "Department id is required."}, status=400)
            return

        supabase_url, supabase_service_key = config

        try:
            payload = self.read_json_body()
            department_payload = self.validate_department_payload(payload)
            request_body = json.dumps(department_payload).encode("utf-8")
            query_string = urlencode({"id": f"eq.{department_id}"})
            request = Request(
                f"{supabase_url.rstrip('/')}/rest/v1/departments?{query_string}",
                data=request_body,
                method="PATCH",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
            )

            with urlopen(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8"))

            department = response_payload[0] if response_payload else {}
            actor = self.get_request_actor(supabase_url)
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "department_updated",
                actor=actor,
                entity_type="department",
                entity_id=department_id,
                details={
                    "name": department.get("name"),
                    "status": department.get("status"),
                },
            )
            self.send_json(
                {
                    "message": "Department updated successfully.",
                    "department": self.format_department(department),
                }
            )
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update department."}, status=500)

    def delete_admin_department(self, department_id):
        config = self.ensure_admin_request("department deletion")
        if not config:
            return

        if not department_id:
            self.send_json({"error": "Department id is required."}, status=400)
            return

        supabase_url, supabase_service_key = config

        try:
            query_string = urlencode({"id": f"eq.{department_id}"})
            request = Request(
                f"{supabase_url.rstrip('/')}/rest/v1/departments?{query_string}",
                method="DELETE",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                    "Prefer": "return=representation",
                },
            )

            with urlopen(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8") or "[]")

            deleted_department = response_payload[0] if response_payload else {}
            actor = self.get_request_actor(supabase_url)
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "department_deleted",
                actor=actor,
                entity_type="department",
                entity_id=department_id,
                details={
                    "name": deleted_department.get("name"),
                    "status": deleted_department.get("status"),
                },
            )
            self.send_json(
                {
                    "message": "Department deleted successfully.",
                    "department": self.format_department(deleted_department),
                }
            )
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to delete department."}, status=500)

    def supabase_rest_request(self, supabase_url, service_key, table, query=None, method="GET", payload=None, prefer=None):
        query_string = urlencode(query or {})
        url = f"{supabase_url.rstrip('/')}/rest/v1/{table}"
        if query_string:
            url = f"{url}?{query_string}"

        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer

        request = Request(url, data=data, method=method, headers=headers)
        with urlopen(request, timeout=20) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body or "[]")

    def handle_rest_error(self, error, fallback_message):
        response_body = error.read().decode("utf-8")
        try:
            response_payload = json.loads(response_body)
            message = response_payload.get("message") or response_payload.get("msg") or response_body
        except json.JSONDecodeError:
            message = response_body or fallback_message

        if "permits_permit_code_key" in message or "permit_code" in message:
            return "This permit code already exists. Use a different permit code."

        return message

    def get_query_params(self):
        return parse_qs(urlsplit(self.path).query, keep_blank_values=False)

    def first_query_value(self, params, key, default=""):
        values = params.get(key) or []
        return (values[0] if values else default) or default

    def format_business_classification(self, row, include_admin_fields=False, usage_count=0):
        payload = {
            "id": row.get("id"),
            "code": row.get("code") or "",
            "name": row.get("name") or "",
            "parentCategory": row.get("parent_category") or "",
        }
        if include_admin_fields:
            payload.update(
                {
                    "normalizedName": row.get("normalized_name") or "",
                    "description": row.get("description") or "",
                    "isActive": bool(row.get("is_active")),
                    "sortOrder": row.get("sort_order") or 0,
                    "usageCount": usage_count,
                    "createdAt": row.get("created_at") or "",
                    "updatedAt": row.get("updated_at") or "",
                }
            )
        return payload

    def business_classification_query(self, active_only=True, include_admin_fields=False):
        params = self.get_query_params()
        search = self.first_query_value(params, "search").strip()
        parent_category = self.first_query_value(params, "parentCategory").strip()
        page_raw = self.first_query_value(params, "page", "1")
        limit_raw = self.first_query_value(params, "limit", "20")
        sort = self.first_query_value(params, "sort", "name.asc").strip().lower()

        try:
            page = max(1, int(page_raw))
        except ValueError:
            page = 1

        try:
            limit = min(100, max(1, int(limit_raw)))
        except ValueError:
            limit = 20

        offset = (page - 1) * limit
        select_fields = "id,code,name,normalized_name,parent_category,description,is_active,sort_order,created_at,updated_at"
        query = {
            "select": select_fields,
            "limit": limit,
            "offset": offset,
        }
        count_query = {"select": select_fields, "limit": 10000}

        if active_only:
            query["is_active"] = "eq.true"
            count_query["is_active"] = "eq.true"

        if parent_category:
            query["parent_category"] = f"eq.{parent_category}"
            count_query["parent_category"] = f"eq.{parent_category}"

        if search:
            sanitized_search = re.sub(r"[^A-Za-z0-9 /&'\\-]+", " ", search)
            sanitized_search = re.sub(r"\s+", " ", sanitized_search).strip()[:80]
            normalized_search = normalize_business_classification_key(sanitized_search)
            terms = [f"name.ilike.*{sanitized_search}*"]
            if normalized_search:
                terms.append(f"normalized_name.ilike.*{normalized_search}*")
            query["or"] = f"({','.join(terms)})"
            count_query["or"] = query["or"]

        order_options = {
            "name.asc": "name.asc",
            "name.desc": "name.desc",
            "parent.asc": "parent_category.asc,name.asc",
            "created.desc": "created_at.desc",
            "sort": "sort_order.asc,name.asc",
        }
        query["order"] = order_options.get(sort, "name.asc")
        count_query["order"] = query["order"]

        return query, count_query, page, limit

    def list_business_classifications(self):
        config = self.ensure_authenticated_request()
        if not config:
            return

        supabase_url, supabase_service_key, _actor = config
        query, count_query, page, limit = self.business_classification_query(active_only=True)
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "business_classifications",
                query,
            ) or []
            count_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "business_classifications",
                count_query,
            ) or []
            self.send_json(
                {
                    "success": True,
                    "data": [self.format_business_classification(row) for row in rows],
                    "pagination": {"page": page, "limit": limit, "total": len(count_rows)},
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load business classifications.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load business classifications."}, status=500)

    def get_business_classification_usage_counts(self, supabase_url, service_key):
        usage_counts = {}
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "applications",
                {"select": "id,business_classification_id", "limit": 10000},
            ) or []
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return usage_counts

        for row in rows:
            classification_id = row.get("business_classification_id")
            if classification_id:
                usage_counts[classification_id] = usage_counts.get(classification_id, 0) + 1
        return usage_counts

    def list_admin_business_classifications(self):
        config = self.ensure_admin_request("business classification listing")
        if not config:
            return

        supabase_url, supabase_service_key = config
        query, count_query, page, limit = self.business_classification_query(active_only=False, include_admin_fields=True)
        params = self.get_query_params()
        status_filter = self.first_query_value(params, "status").strip()
        if status_filter == "Active":
            query["is_active"] = "eq.true"
            count_query["is_active"] = "eq.true"
        elif status_filter == "Inactive":
            query["is_active"] = "eq.false"
            count_query["is_active"] = "eq.false"

        try:
            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "business_classifications",
                query,
            ) or []
            count_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "business_classifications",
                count_query,
            ) or []
            usage_counts = self.get_business_classification_usage_counts(supabase_url, supabase_service_key)
            self.send_json(
                {
                    "success": True,
                    "classifications": [
                        self.format_business_classification(
                            row,
                            include_admin_fields=True,
                            usage_count=usage_counts.get(row.get("id"), 0),
                        )
                        for row in rows
                    ],
                    "pagination": {"page": page, "limit": limit, "total": len(count_rows)},
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load business classifications.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load business classifications."}, status=500)

    def normalize_business_classification_payload(self, payload, existing_id=""):
        name = normalize_business_classification_value(payload.get("name"))
        parent_category = (payload.get("parentCategory") or payload.get("parent_category") or "").strip()
        description = (payload.get("description") or "").strip()
        is_active = bool(payload.get("isActive", payload.get("is_active", True)))
        sort_order_raw = payload.get("sortOrder", payload.get("sort_order", 0))

        if not name:
            raise ValueError("Business classification name is required.")

        normalized_name = normalize_business_classification_key(name)
        if not normalized_name:
            raise ValueError("Business classification name is invalid.")

        try:
            sort_order = max(0, int(sort_order_raw or 0))
        except (TypeError, ValueError):
            sort_order = 0

        return {
            "code": (payload.get("code") or "").strip() or None,
            "name": name,
            "normalized_name": normalized_name,
            "parent_category": parent_category or None,
            "description": description or None,
            "is_active": is_active,
            "sort_order": sort_order,
        }

    def business_classification_exists(self, supabase_url, service_key, normalized_name, excluded_id=""):
        query = {"select": "id", "normalized_name": f"eq.{normalized_name}", "limit": 1}
        rows = self.supabase_rest_request(supabase_url, service_key, "business_classifications", query) or []
        return any(row.get("id") != excluded_id for row in rows)

    def create_admin_business_classification(self):
        config = self.ensure_admin_request("business classification creation")
        if not config:
            return

        supabase_url, supabase_service_key = config
        try:
            payload = self.normalize_business_classification_payload(self.read_json_body())
            if self.business_classification_exists(supabase_url, supabase_service_key, payload["normalized_name"]):
                self.send_json({"error": "This business classification already exists."}, status=409)
                return

            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "business_classifications",
                method="POST",
                payload=payload,
                prefer="return=representation",
            )
            actor = self.get_request_actor(supabase_url)
            created = rows[0] if rows else {}
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "business_classification_created",
                actor=actor,
                entity_type="business_classification",
                entity_id=created.get("id"),
                details={"name": created.get("name")},
            )
            self.send_json({"message": "Business classification created.", "classification": self.format_business_classification(created, True)}, status=201)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to create business classification.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to create business classification."}, status=500)

    def update_admin_business_classification(self, classification_id):
        config = self.ensure_admin_request("business classification update")
        if not config:
            return

        supabase_url, supabase_service_key = config
        try:
            classification_id = (classification_id or "").strip()
            if not classification_id:
                self.send_json({"error": "Business classification is required."}, status=400)
                return

            payload = self.normalize_business_classification_payload(self.read_json_body(), existing_id=classification_id)
            if self.business_classification_exists(supabase_url, supabase_service_key, payload["normalized_name"], excluded_id=classification_id):
                self.send_json({"error": "This business classification already exists."}, status=409)
                return

            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "business_classifications",
                {"id": f"eq.{classification_id}"},
                method="PATCH",
                payload=payload,
                prefer="return=representation",
            )
            if not rows:
                self.send_json({"error": "Business classification not found."}, status=404)
                return

            actor = self.get_request_actor(supabase_url)
            updated = rows[0]
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "business_classification_updated",
                actor=actor,
                entity_type="business_classification",
                entity_id=classification_id,
                details={
                    "name": updated.get("name"),
                    "isActive": updated.get("is_active"),
                    "parentCategory": updated.get("parent_category"),
                },
            )
            self.send_json({"message": "Business classification updated.", "classification": self.format_business_classification(updated, True)})
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update business classification.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update business classification."}, status=500)

    def get_active_business_classification(self, supabase_url, service_key, classification_id):
        classification_id = (classification_id or "").strip()
        if not classification_id:
            return None

        rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "business_classifications",
            {
                "select": "id,name,parent_category,is_active",
                "id": f"eq.{classification_id}",
                "is_active": "eq.true",
                "limit": 1,
            },
        ) or []
        return rows[0] if rows else None

    def create_notification(self, supabase_url, service_key, user_id, title, message, notification_type="system", source_role="System", application_id=None):
        if not user_id or not title or not message:
            return None

        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "notifications",
                method="POST",
                payload={
                    "user_id": user_id,
                    "application_id": application_id,
                    "title": title,
                    "message": message,
                    "type": notification_type,
                    "source_role": source_role,
                },
                prefer="return=representation",
            )
            return rows[0] if rows else None
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None

    def create_notifications(self, supabase_url, service_key, notifications):
        payload = [
            notification
            for notification in notifications
            if notification.get("user_id") and notification.get("title") and notification.get("message")
        ]
        if not payload:
            return []

        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "notifications",
                method="POST",
                payload=payload,
                prefer="return=representation",
            )
            return rows or []
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return []

    def get_application_owner_id(self, supabase_url, service_key, application_id):
        if not application_id:
            return ""

        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "applications",
                {
                    "select": "id,applicant_id",
                    "id": f"eq.{application_id}",
                    "limit": 1,
                },
            )
            return (rows[0] or {}).get("applicant_id") if rows else ""
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return ""

    def find_application_by_reference(self, supabase_url, service_key, reference):
        reference = (reference or "").strip()
        if not reference:
            return None

        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "applications",
                {
                    "select": "id,applicant_id,business_info",
                    "id": f"eq.{reference}",
                    "limit": 1,
                },
            )
            if rows:
                return rows[0]
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            pass

        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "applications",
                {
                    "select": "id,applicant_id,business_info",
                    "order": "created_at.desc",
                    "limit": 500,
                },
            )
            reference_lower = reference.lower()
            for row in rows or []:
                if (row.get("id") or "").lower().startswith(reference_lower):
                    return row
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None

        return None

    def notify_application_owner(self, supabase_url, service_key, application_id, title, message, notification_type="system", source_role="System"):
        user_id = self.get_application_owner_id(supabase_url, service_key, application_id)
        return self.create_notification(
            supabase_url,
            service_key,
            user_id,
            title,
            message,
            notification_type=notification_type,
            source_role=source_role,
            application_id=application_id,
        )

    def get_department_notification_users(self, config, department):
        department_id = department.get("id")
        department_key = department_key_from_name(department.get("name"))
        queries = []
        if department_id:
            queries.append({"select": "auth_user_id", "role": "eq.department_office", "status": "eq.active", "department_id": f"eq.{department_id}"})
            queries.append({"select": "auth_user_id", "role": "eq.department_office", "status": "eq.Active", "department_id": f"eq.{department_id}"})
        if department_key:
            queries.append({"select": "auth_user_id", "role": "eq.department_office", "status": "eq.active", "department_key": f"eq.{department_key}"})
            queries.append({"select": "auth_user_id", "role": "eq.department_office", "status": "eq.Active", "department_key": f"eq.{department_key}"})

        users = []
        seen = set()
        for query in queries:
            try:
                rows = self.service_rest_request(config, "profiles", query=urlencode(query)) or []
            except HTTPError:
                rows = []
            for row in rows:
                user_id = row.get("auth_user_id")
                if user_id and user_id not in seen:
                    seen.add(user_id)
                    users.append(user_id)
        return users

    def notify_department_assignment(self, config, department, application):
        user_ids = self.get_department_notification_users(config, department)
        if not user_ids:
            return 0
        info = application.get("business_info") or {}
        business_name = self.app_business_name(info)
        reference = (application.get("id") or "")[:8]
        department_name = department.get("name") or department_key_from_name(department.get("name")).replace("_", " ").title()
        sent_count = 0
        for user_id in user_ids:
            notification = self.create_notification(
                config["supabase_url"],
                config["supabase_service_key"],
                user_id,
                "New Application Assigned",
                f"{business_name} ({reference}) has been routed to {department_name} for review.",
                notification_type="system",
                source_role="BPLO",
                application_id=application.get("id"),
            )
            if notification:
                sent_count += 1
        return sent_count

    def format_notification(self, notification):
        return {
            "id": notification.get("id"),
            "userId": notification.get("user_id"),
            "applicationId": notification.get("application_id"),
            "title": notification.get("title") or "",
            "message": notification.get("message") or "",
            "type": notification.get("type") or "system",
            "sourceRole": notification.get("source_role") or "System",
            "isRead": bool(notification.get("is_read")),
            "createdAt": notification.get("created_at") or "",
            "readAt": notification.get("read_at") or "",
        }

    def format_permit_document(self, document):
        requirement_type = document.get("requirement_type") or "Required"
        return {
            "id": document.get("id"),
            "permitId": document.get("permit_id"),
            "documentName": document.get("document_name") or "",
            "shortDescription": document.get("short_description") or "",
            "requirementType": requirement_type,
            "acceptedFileTypes": document.get("accepted_file_types") or "",
            "maxFileSize": document.get("max_file_size") or "",
            "uploadRequired": bool(document.get("upload_required")),
            "notes": document.get("notes") or "",
            "createdAt": document.get("created_at") or "",
            "updatedAt": document.get("updated_at") or "",
        }

    def format_permit(self, permit, documents=None, offices=None):
        return {
            "id": permit.get("id"),
            "permitName": permit.get("permit_name") or "",
            "permitCode": permit.get("permit_code") or "",
            "category": permit.get("category") or "",
            "description": permit.get("description") or "",
            "status": permit.get("status") or "Draft",
            "processingFee": permit.get("processing_fee"),
            "applicantNotes": permit.get("applicant_notes") or "",
            "createdAt": permit.get("created_at") or "",
            "updatedAt": permit.get("updated_at") or "",
            "documents": documents if documents is not None else [],
            "requiredOffices": offices if offices is not None else [],
        }

    def normalize_permit_payload(self, payload):
        permit_name = (payload.get("permitName") or "").strip()
        permit_code = (payload.get("permitCode") or "").strip()
        category = (payload.get("category") or "").strip()
        description = (payload.get("description") or "").strip()
        status = (payload.get("status") or "Draft").strip()
        applicant_notes = (payload.get("applicantNotes") or "").strip()
        processing_fee_raw = payload.get("processingFee")

        if not permit_name:
            raise ValueError("Permit name is required.")
        if not permit_code:
            raise ValueError("Permit code is required.")
        if not category:
            raise ValueError("Permit category is required.")
        if status not in {"Active", "Inactive", "Draft"}:
            raise ValueError("Permit status must be Active, Inactive, or Draft.")

        processing_fee = None
        if processing_fee_raw not in (None, ""):
            processing_fee = float(processing_fee_raw)
            if processing_fee < 0:
                raise ValueError("Processing fee cannot be negative.")

        documents = payload.get("documents") or []
        normalized_documents = []
        for document in documents:
            document_name = (document.get("documentName") or document.get("name") or "").strip()
            requirement_type = (document.get("requirementType") or "Required").strip().title()
            accepted_file_types = (
                document.get("acceptedFileTypes") or document.get("fileTypes") or ""
            ).strip()
            if not document_name:
                raise ValueError("Every document requirement needs a document name.")
            if requirement_type not in {"Required", "Optional"}:
                raise ValueError("Document requirement type must be Required or Optional.")
            if not accepted_file_types:
                raise ValueError(f"Accepted file types are required for {document_name}.")

            normalized_documents.append(
                {
                    "document_name": document_name,
                    "short_description": (document.get("shortDescription") or document.get("description") or "").strip(),
                    "requirement_type": requirement_type,
                    "accepted_file_types": accepted_file_types,
                    "max_file_size": (document.get("maxFileSize") or document.get("maxSize") or "").strip(),
                    "upload_required": bool(document.get("uploadRequired", requirement_type == "Required")),
                    "notes": (document.get("notes") or "").strip(),
                }
            )

        if status == "Active" and not any(doc["requirement_type"] == "Required" for doc in normalized_documents):
            raise ValueError("Add at least one required document before activating a permit.")

        required_office_ids = []
        for office_id in payload.get("requiredOfficeIds") or []:
            office_id = str(office_id).strip()
            if office_id and office_id not in required_office_ids:
                required_office_ids.append(office_id)

        return {
            "permit": {
                "permit_name": permit_name,
                "permit_code": permit_code,
                "category": category,
                "description": description,
                "status": status,
                "processing_fee": processing_fee,
                "applicant_notes": applicant_notes,
            },
            "documents": normalized_documents,
            "requiredOfficeIds": required_office_ids,
        }

    def get_permit_bundle(self, supabase_url, service_key, permit_id, active_only=False):
        permit_query = {
            "select": "id,permit_name,permit_code,category,description,status,processing_fee,applicant_notes,created_at,updated_at",
            "id": f"eq.{permit_id}",
            "limit": 1,
        }
        if active_only:
            permit_query["status"] = "eq.Active"

        permits = self.supabase_rest_request(supabase_url, service_key, "permits", permit_query)
        if not permits:
            return None

        documents = self.supabase_rest_request(
            supabase_url,
            service_key,
            "permit_documents",
            {
                "select": "id,permit_id,document_name,short_description,requirement_type,accepted_file_types,max_file_size,upload_required,notes,created_at,updated_at",
                "permit_id": f"eq.{permit_id}",
                "order": "requirement_type.asc,created_at.asc",
            },
        )
        office_rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "permit_required_offices",
            {"select": "id,permit_id,office_id,created_at", "permit_id": f"eq.{permit_id}", "order": "created_at.asc"},
        )
        office_ids = [row.get("office_id") for row in office_rows if row.get("office_id")]
        offices = []
        if office_ids:
            departments = self.supabase_rest_request(
                supabase_url,
                service_key,
                "departments",
                {
                    "select": "id,name,description,status",
                    "id": f"in.({','.join(office_ids)})",
                },
            )
            department_by_id = {department.get("id"): department for department in departments or []}
            offices = [
                {
                    "id": office_id,
                    "name": (department_by_id.get(office_id) or {}).get("name") or "Office",
                    "description": (department_by_id.get(office_id) or {}).get("description") or "",
                }
                for office_id in office_ids
            ]

        return self.format_permit(
            permits[0],
            [self.format_permit_document(document) for document in documents or []],
            offices,
        )

    def list_admin_permits(self):
        config = self.ensure_admin_request("permit listing")
        if not config:
            return

        supabase_url, supabase_service_key = config
        try:
            permits = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permits",
                {
                    "select": "id,permit_name,permit_code,category,description,status,processing_fee,applicant_notes,created_at,updated_at",
                    "order": "created_at.desc",
                },
            )
            self.send_json({"permits": [self.format_permit(permit) for permit in permits or []], "total": len(permits or [])})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load permits.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load permits."}, status=500)

    def get_admin_permit(self, permit_id):
        config = self.ensure_admin_request("permit viewing")
        if not config:
            return

        supabase_url, supabase_service_key = config
        try:
            permit = self.get_permit_bundle(supabase_url, supabase_service_key, permit_id)
            if not permit:
                self.send_json({"error": "Permit not found."}, status=404)
                return
            self.send_json({"permit": permit})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load permit."}, status=500)

    def create_admin_permit(self):
        config = self.ensure_admin_request("permit creation")
        if not config:
            return

        supabase_url, supabase_service_key = config
        try:
            normalized = self.normalize_permit_payload(self.read_json_body())
            created = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permits",
                method="POST",
                payload=normalized["permit"],
                prefer="return=representation",
            )
            permit = created[0] if created else {}
            permit_id = permit.get("id")

            if normalized["documents"]:
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "permit_documents",
                    method="POST",
                    payload=[{**document, "permit_id": permit_id} for document in normalized["documents"]],
                    prefer="return=minimal",
                )

            if normalized["requiredOfficeIds"]:
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "permit_required_offices",
                    method="POST",
                    payload=[{"permit_id": permit_id, "office_id": office_id} for office_id in normalized["requiredOfficeIds"]],
                    prefer="return=minimal",
                )

            actor = self.get_request_actor(supabase_url)
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "permit_created",
                actor=actor,
                entity_type="permit",
                entity_id=permit_id,
                details={"permitName": permit.get("permit_name"), "status": permit.get("status")},
            )
            self.send_json(
                {"message": "Permit created successfully.", "permit": self.get_permit_bundle(supabase_url, supabase_service_key, permit_id)},
                status=201,
            )
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to create permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to create permit."}, status=500)

    def update_admin_permit(self, permit_id):
        config = self.ensure_admin_request("permit update")
        if not config:
            return

        supabase_url, supabase_service_key = config
        try:
            normalized = self.normalize_permit_payload(self.read_json_body())
            updated = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permits",
                {"id": f"eq.{permit_id}"},
                method="PATCH",
                payload=normalized["permit"],
                prefer="return=representation",
            )
            if not updated:
                self.send_json({"error": "Permit not found."}, status=404)
                return

            self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permit_documents",
                {"permit_id": f"eq.{permit_id}"},
                method="DELETE",
                prefer="return=minimal",
            )
            self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permit_required_offices",
                {"permit_id": f"eq.{permit_id}"},
                method="DELETE",
                prefer="return=minimal",
            )

            if normalized["documents"]:
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "permit_documents",
                    method="POST",
                    payload=[{**document, "permit_id": permit_id} for document in normalized["documents"]],
                    prefer="return=minimal",
                )
            if normalized["requiredOfficeIds"]:
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "permit_required_offices",
                    method="POST",
                    payload=[{"permit_id": permit_id, "office_id": office_id} for office_id in normalized["requiredOfficeIds"]],
                    prefer="return=minimal",
                )

            actor = self.get_request_actor(supabase_url)
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "permit_updated",
                actor=actor,
                entity_type="permit",
                entity_id=permit_id,
                details={"permitName": updated[0].get("permit_name"), "status": updated[0].get("status")},
            )
            self.send_json({"message": "Permit updated successfully.", "permit": self.get_permit_bundle(supabase_url, supabase_service_key, permit_id)})
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update permit."}, status=500)

    def delete_admin_permit(self, permit_id):
        config = self.ensure_admin_request("permit deletion")
        if not config:
            return

        supabase_url, supabase_service_key = config
        try:
            deleted = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permits",
                {"id": f"eq.{permit_id}"},
                method="DELETE",
                prefer="return=representation",
            )
            actor = self.get_request_actor(supabase_url)
            deleted_permit = deleted[0] if deleted else {}
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "permit_deleted",
                actor=actor,
                entity_type="permit",
                entity_id=permit_id,
                details={"permitName": deleted_permit.get("permit_name")},
            )
            self.send_json({"message": "Permit deleted successfully.", "permit": self.format_permit(deleted_permit)})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to delete permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to delete permit."}, status=500)

    def ensure_applicant_request(self, action_label):
        supabase_url, supabase_client_key, supabase_service_key, _admin_email = self.get_admin_api_config()
        if not supabase_url or not supabase_client_key or not supabase_service_key:
            self.send_json(
                {
                    "error": (
                        f"Applicant {action_label} is not configured. Set SUPABASE_URL, "
                        "SUPABASE_ANON_KEY or SUPABASE_PUBLISHABLE_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env."
                    )
                },
                status=500,
            )
            return None

        auth_header = self.headers.get("Authorization", "")
        access_token = auth_header.removeprefix("Bearer ").strip()
        if not access_token:
            self.send_json({"error": "Please sign in before continuing."}, status=401)
            return None

        try:
            user = self.get_session_user(access_token, supabase_url, supabase_client_key)
        except HTTPError:
            self.send_json({"error": "Invalid or expired session."}, status=401)
            return None

        return supabase_url, supabase_service_key, user

    def list_applicant_notifications(self):
        config = self.ensure_applicant_request("notification listing")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "notifications",
                {
                    "select": "id,user_id,application_id,title,message,type,source_role,is_read,created_at,read_at",
                    "user_id": f"eq.{user.get('id')}",
                    "order": "created_at.desc",
                    "limit": 20,
                },
            ) or []
            unread_count = sum(1 for row in rows if not row.get("is_read"))
            self.send_json(
                {
                    "notifications": [self.format_notification(row) for row in rows],
                    "unreadCount": unread_count,
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load notifications.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load notifications."}, status=500)

    def mark_applicant_notification_read(self, notification_id):
        config = self.ensure_applicant_request("notification update")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "notifications",
                {
                    "id": f"eq.{notification_id}",
                    "user_id": f"eq.{user.get('id')}",
                },
                method="PATCH",
                payload={"is_read": True, "read_at": utc_now_iso()},
                prefer="return=representation",
            )
            if not rows:
                self.send_json({"error": "Notification not found."}, status=404)
                return
            self.send_json({"message": "Notification marked as read.", "notification": self.format_notification(rows[0])})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update notification.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update notification."}, status=500)

    def mark_all_applicant_notifications_read(self):
        config = self.ensure_applicant_request("notification update")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "notifications",
                {
                    "user_id": f"eq.{user.get('id')}",
                    "is_read": "eq.false",
                },
                method="PATCH",
                payload={"is_read": True, "read_at": utc_now_iso()},
                prefer="return=representation",
            ) or []
            self.send_json({"message": "Notifications marked as read.", "updated": len(rows)})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update notifications.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update notifications."}, status=500)

    def delete_applicant_notification(self, notification_id):
        config = self.ensure_applicant_request("notification deletion")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "notifications",
                {
                    "id": f"eq.{notification_id}",
                    "user_id": f"eq.{user.get('id')}",
                },
                method="DELETE",
                prefer="return=representation",
            )
            if not rows:
                self.send_json({"error": "Notification not found."}, status=404)
                return
            self.send_json({"message": "Notification deleted.", "notification": self.format_notification(rows[0])})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to delete notification.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to delete notification."}, status=500)

    def list_applicant_permits(self):
        config = self.ensure_applicant_request("permit listing")
        if not config:
            return

        supabase_url, supabase_service_key, _user = config
        try:
            permits = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permits",
                {
                    "select": "id,permit_name,permit_code,category,description,status,processing_fee,applicant_notes,created_at,updated_at",
                    "status": "eq.Active",
                    "order": "created_at.desc",
                },
            )
            self.send_json({"permits": [self.format_permit(permit) for permit in permits or []], "total": len(permits or [])})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load permits.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load permits."}, status=500)

    def get_applicant_permit(self, permit_id):
        config = self.ensure_applicant_request("permit viewing")
        if not config:
            return

        supabase_url, supabase_service_key, _user = config
        try:
            permit = self.get_permit_bundle(supabase_url, supabase_service_key, permit_id, active_only=True)
            if not permit:
                self.send_json({"error": "Permit not found or inactive."}, status=404)
                return
            self.send_json({"permit": permit})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load permit."}, status=500)

    def start_applicant_application(self):
        config = self.ensure_applicant_request("application creation")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            payload = self.read_json_body()
            permit_id = (payload.get("permitId") or "").strip()
            if not permit_id:
                self.send_json({"error": "Permit is required."}, status=400)
                return

            permit = self.get_permit_bundle(supabase_url, supabase_service_key, permit_id, active_only=True)
            if not permit:
                self.send_json({"error": "Permit not found or inactive."}, status=404)
                return

            created = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                method="POST",
                payload={
                    "permit_id": permit_id,
                    "applicant_id": user.get("id"),
                    "status": "Draft",
                    "permit_snapshot": permit,
                },
                prefer="return=representation",
            )
            application = created[0] if created else {}
            application_id = application.get("id")

            document_rows = [
                {
                    "application_id": application_id,
                    "permit_document_id": document.get("id"),
                    "document_snapshot": document,
                    "upload_status": "Pending",
                }
                for document in permit.get("documents", [])
            ]
            if document_rows:
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "application_documents",
                    method="POST",
                    payload=document_rows,
                    prefer="return=minimal",
                )

            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "application_started",
                actor=user,
                entity_type="application",
                entity_id=application_id,
                details={"permitId": permit_id, "permitName": permit.get("permitName")},
            )
            self.create_notification(
                supabase_url,
                supabase_service_key,
                user.get("id"),
                "Application Started",
                "Your business permit application record has been created.",
                notification_type="system",
                source_role="System",
                application_id=application_id,
            )
            self.send_json({"message": "Application started.", "application": application, "permit": permit}, status=201)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to start application.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to start application."}, status=500)

    def update_applicant_application_document(self):
        config = self.ensure_applicant_request("document upload")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            payload = self.read_json_body()
            application_id = (payload.get("applicationId") or "").strip()
            permit_document_id = (payload.get("permitDocumentId") or "").strip()
            file_name = (payload.get("fileName") or "").strip()
            file_url = (payload.get("fileUrl") or "").strip()
            upload_status = (payload.get("uploadStatus") or ("Uploaded" if file_name else "Removed")).strip()

            if upload_status not in {"Pending", "Uploaded", "Removed"}:
                self.send_json({"error": "Invalid upload status."}, status=400)
                return
            if not application_id or not permit_document_id:
                self.send_json({"error": "Application and document are required."}, status=400)
                return

            owned = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {"select": "id,permit_id", "id": f"eq.{application_id}", "applicant_id": f"eq.{user.get('id')}", "limit": 1},
            )
            if not owned:
                self.send_json({"error": "Application not found."}, status=404)
                return
            application = owned[0]

            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "id",
                    "application_id": f"eq.{application_id}",
                    "permit_document_id": f"eq.{permit_document_id}",
                    "limit": 1,
                },
            )
            if not rows:
                permit_documents = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "permit_documents",
                    {
                        "select": "id,permit_id,document_name,short_description,requirement_type,accepted_file_types,max_file_size,upload_required,notes,created_at,updated_at",
                        "id": f"eq.{permit_document_id}",
                        "permit_id": f"eq.{application.get('permit_id')}",
                        "limit": 1,
                    },
                )
                if not permit_documents:
                    self.send_json({"error": "Application document not found."}, status=404)
                    return

                created_document_rows = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "application_documents",
                    method="POST",
                    payload={
                        "application_id": application_id,
                        "permit_document_id": permit_document_id,
                        "document_snapshot": self.format_permit_document(permit_documents[0]),
                        "upload_status": "Pending",
                    },
                    prefer="return=representation",
                )
                rows = created_document_rows or []

            updated = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {"id": f"eq.{rows[0].get('id')}"},
                method="PATCH",
                payload={
                    "file_name": file_name or None,
                    "file_url": file_url or None,
                    "upload_status": upload_status,
                    "uploaded_at": utc_now_iso() if upload_status == "Uploaded" else None,
                },
                prefer="return=representation",
            )
            if upload_status == "Uploaded":
                self.create_notification(
                    supabase_url,
                    supabase_service_key,
                    user.get("id"),
                    "Document Uploaded",
                    f"{file_name or 'Your document'} was uploaded successfully.",
                    notification_type="document",
                    source_role="System",
                    application_id=application_id,
                )
            elif upload_status == "Removed":
                self.create_notification(
                    supabase_url,
                    supabase_service_key,
                    user.get("id"),
                    "Document Removed",
                    "A document was removed from your application requirements.",
                    notification_type="document",
                    source_role="System",
                    application_id=application_id,
                )
            self.send_json({"message": "Document updated.", "document": updated[0] if updated else {}})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update document.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update document."}, status=500)

    def get_applicant_application_ocr_fields(self, application_id):
        config = self.ensure_applicant_request("OCR field loading")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        application_id = (application_id or "").strip()
        if not application_id:
            self.send_json({"error": "Application is required."}, status=400)
            return

        try:
            application_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {
                    "select": "id,applicant_id",
                    "id": f"eq.{application_id}",
                    "applicant_id": f"eq.{user.get('id')}",
                    "limit": 1,
                },
            )
            if not application_rows:
                self.send_json({"error": "Application not found."}, status=404)
                return

            merged_fields = {}

            document_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "ocr_extracted_fields",
                    "application_id": f"eq.{application_id}",
                    "order": "created_at.asc",
                },
            ) or []
            for row in document_rows:
                fields = row.get("ocr_extracted_fields") or {}
                if isinstance(fields, dict):
                    self.merge_extracted_ocr_fields(merged_fields, fields)

            ocr_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_ocr_results",
                {
                    "select": "extracted_fields",
                    "application_id": f"eq.{application_id}",
                    "order": "created_at.asc",
                },
            ) or []
            for row in ocr_rows:
                fields = row.get("extracted_fields") or {}
                if isinstance(fields, dict):
                    self.merge_extracted_ocr_fields(merged_fields, fields)

            self.send_json(
                {
                    "success": True,
                    "fields": merged_fields,
                    "extracted_fields": merged_fields,
                    "extractedFields": merged_fields,
                    "ocrResultCount": len(ocr_rows or []),
                    "documentOcrCount": sum(
                        1
                        for row in document_rows
                        if isinstance(row.get("ocr_extracted_fields"), dict) and row.get("ocr_extracted_fields")
                    ),
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load OCR fields.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load OCR fields."}, status=500)

    def extract_applicant_document_ocr(self):
        config = self.ensure_applicant_request("OCR extraction")
        if not config:
            return

        supabase_url, supabase_service_key, user = config

        try:
            payload = self.read_json_body()

            application_id = (payload.get("applicationId") or "").strip()
            permit_document_id = (payload.get("permitDocumentId") or "").strip()
            file_name = (payload.get("fileName") or "").strip()
            file_url = (payload.get("fileUrl") or "").strip()
            document_type = (payload.get("documentType") or "").strip()

            if not application_id or not permit_document_id or not file_url:
                self.send_json({"error": "Application, document, and file path are required."}, status=400)
                return

            owned = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {
                    "select": "id",
                    "id": f"eq.{application_id}",
                    "applicant_id": f"eq.{user.get('id')}",
                    "limit": 1,
                },
            )

            if not owned:
                self.send_json({"error": "Application not found."}, status=404)
                return

            document_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "id",
                    "application_id": f"eq.{application_id}",
                    "permit_document_id": f"eq.{permit_document_id}",
                    "limit": 1,
                },
            )

            if not document_rows:
                self.send_json({"error": "Application document not found."}, status=404)
                return

            application_document_id = document_rows[0].get("id")

            file_bytes = self.download_storage_file(
                supabase_url,
                supabase_service_key,
                "application-documents",
                file_url,
            )

            raw_text = self.extract_text_from_file(file_name, file_bytes)
            print("RAW OCR TEXT:")
            print(raw_text)
            extracted_fields = self.extract_business_fields_from_text(raw_text, document_type)
            confidence_score = extracted_fields.get("confidence_score")

            self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {"id": f"eq.{application_document_id}"},
                method="PATCH",
                payload={
                    "ocr_status": "Completed",
                    "ocr_raw_text": raw_text,
                    "ocr_extracted_fields": extracted_fields,
                },
                prefer="return=representation",
            )

            ocr_payload = {
                "application_id": application_id,
                "application_document_id": application_document_id,
                "permit_document_id": permit_document_id,
                "file_name": file_name,
                "file_url": file_url,
                "document_type": document_type,
                "raw_text": raw_text,
                "extracted_fields": extracted_fields,
                "confidence_score": confidence_score,
                "parser_version": extracted_fields.get("parser_version", "business_info_v1"),
                "ocr_status": "Completed",
            }
            try:
                ocr_rows = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "application_ocr_results",
                    method="POST",
                    payload=ocr_payload,
                    prefer="return=representation",
                )
            except HTTPError as error:
                response_body = error.read().decode("utf-8")
                if error.code == 400 and "parser_version" in response_body:
                    fallback_payload = dict(ocr_payload)
                    fallback_payload.pop("parser_version", None)
                    ocr_rows = self.supabase_rest_request(
                        supabase_url,
                        supabase_service_key,
                        "application_ocr_results",
                        method="POST",
                        payload=fallback_payload,
                        prefer="return=representation",
                    )
                else:
                    raise
            self.create_notification(
                supabase_url,
                supabase_service_key,
                user.get("id"),
                "OCR Extraction Completed",
                f"{file_name or 'Your document'} was read and matched to available form fields.",
                notification_type="document",
                source_role="System",
                application_id=application_id,
            )

            self.send_json(
                {
                    "success": True,
                    "message": "OCR completed.",
                    "ocr": ocr_rows[0] if ocr_rows else {},
                    "extracted_fields": extracted_fields,
                    "extractedFields": extracted_fields,
                }
            )

        except Exception as error:
            self.send_json({"error": str(error) or "Unable to process OCR."}, status=500)

    def submit_applicant_application(self):
        config = self.ensure_applicant_request("application submission")
        if not config:
            return

        supabase_url, supabase_service_key, user = config

        try:
            payload = self.read_json_body()
            application_id = (payload.get("application_id") or payload.get("applicationId") or "").strip()
            business_info = payload.get("business_info") or payload.get("businessInfo") or {}

            if not application_id:
                self.send_json({"error": "Missing application_id."}, status=400)
                return

            if not isinstance(business_info, dict) or not business_info:
                self.send_json({"error": "Missing business information."}, status=400)
                return

            required_business_fields = {
                "business_name": "Business name",
                "business_address": "Business address",
                "first_name": "First name",
                "last_name": "Last name",
                "business_classification_id": "Business classification",
            }
            missing_business_fields = [
                label
                for field_name, label in required_business_fields.items()
                if not str(business_info.get(field_name) or "").strip()
            ]
            if missing_business_fields:
                self.send_json(
                    {"error": f"Please complete: {', '.join(missing_business_fields)}."},
                    status=400,
                )
                return

            classification = self.get_active_business_classification(
                supabase_url,
                supabase_service_key,
                business_info.get("business_classification_id"),
            )
            if not classification:
                self.send_json({"error": "Please select a valid business classification."}, status=400)
                return

            business_info["business_classification"] = classification.get("name") or business_info.get("business_classification")
            business_info["business_classification_id"] = classification.get("id")
            business_info["business_classification_parent_category"] = classification.get("parent_category") or ""

            application_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {
                    "select": "id,permit_id,applicant_id,status",
                    "id": f"eq.{application_id}",
                    "applicant_id": f"eq.{user.get('id')}",
                    "limit": 1,
                },
            )
            if not application_rows:
                self.send_json({"error": "Application not found."}, status=404)
                return

            application = application_rows[0]
            document_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "id,file_url,upload_status,document_snapshot,ocr_status",
                    "application_id": f"eq.{application_id}",
                },
            )

            missing_documents = []
            processing_documents = []
            for document in document_rows or []:
                snapshot = document.get("document_snapshot") or {}
                requirement_type = snapshot.get("requirementType") or snapshot.get("requirement_type") or ""
                upload_required = snapshot.get("uploadRequired")
                if upload_required is None:
                    upload_required = snapshot.get("upload_required", True)

                if requirement_type == "Required" and upload_required is not False:
                    if not document.get("file_url") or document.get("upload_status") != "Uploaded":
                        missing_documents.append(document)

                if document.get("upload_status") == "Uploaded" and document.get("ocr_status") == "Processing":
                    processing_documents.append(document)

            if missing_documents:
                self.send_json({"error": "Please upload all required documents before submitting."}, status=400)
                return

            if processing_documents:
                self.send_json({"error": "Please wait for OCR to finish before submitting."}, status=400)
                return

            submitted_at = utc_now_iso()
            updated_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {"id": f"eq.{application_id}"},
                method="PATCH",
                payload={
                    "business_info": business_info,
                    "business_classification_id": classification.get("id"),
                    "status": "Submitted",
                    "progress": "Submitted",
                    "submitted_at": submitted_at,
                },
                prefer="return=representation",
            )

            office_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permit_required_offices",
                {
                    "select": "office_id",
                    "permit_id": f"eq.{application.get('permit_id')}",
                },
            ) or []
            office_ids = [row.get("office_id") for row in office_rows if row.get("office_id")]

            departments = []
            if office_ids:
                departments = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "departments",
                    {
                        "select": "id,name",
                        "id": f"in.({','.join(office_ids)})",
                    },
                ) or []

            created_assignments = []
            for department in departments:
                department_key = department_key_from_name(department.get("name"))
                if not department_key:
                    continue

                existing_assignment = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "department_application_assignments",
                    {
                        "select": "id",
                        "application_id": f"eq.{application_id}",
                        "department_key": f"eq.{department_key}",
                        "limit": 1,
                    },
                )
                if existing_assignment:
                    continue

                assignment_rows = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "department_application_assignments",
                    method="POST",
                    payload={
                        "application_id": application_id,
                        "department_key": department_key,
                        "evaluation_status": "Pending",
                        "verification_status": "Unverified",
                        "assigned_by": user.get("id"),
                    },
                    prefer="return=representation",
                )
                if assignment_rows:
                    created_assignments.append(assignment_rows[0])

            self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_status_history",
                method="POST",
                payload={
                    "application_id": application_id,
                    "status": "Submitted",
                    "remarks": "Application submitted by applicant.",
                    "created_by": user.get("id"),
                },
                prefer="return=minimal",
            )

            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "application_submitted",
                actor=user,
                entity_type="application",
                entity_id=application_id,
                details={
                    "businessName": business_info.get("business_name"),
                    "assignedDepartments": [item.get("department_key") for item in created_assignments],
                },
            )
            self.create_notification(
                supabase_url,
                supabase_service_key,
                user.get("id"),
                "Application Submitted",
                "Your application has been submitted successfully.",
                notification_type="status",
                source_role="System",
                application_id=application_id,
            )

            self.send_json(
                {
                    "success": True,
                    "message": "Application submitted successfully.",
                    "application": updated_rows[0] if updated_rows else {},
                    "assignments": created_assignments,
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to submit application.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to submit application."}, status=500)

    def create_audit_log(self):
        config = self.ensure_authenticated_request()
        if not config:
            return

        supabase_url, supabase_service_key, actor = config

        try:
            payload = self.read_json_body()
            action = (payload.get("action") or "").strip()
            entity_type = (payload.get("entityType") or "").strip() or None
            entity_id = (payload.get("entityId") or "").strip() or None
            details = payload.get("details") or {}

            if not action:
                self.send_json({"error": "Audit action is required."}, status=400)
                return

            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                action,
                actor=actor,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
            )
            self.send_json({"message": "Audit log recorded."}, status=201)
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to record audit log."}, status=500)

    def format_audit_log(self, audit_log):
        return {
            "id": audit_log.get("id"),
            "actorEmail": audit_log.get("actor_email") or "System",
            "actorRole": audit_log.get("actor_role") or "-",
            "action": audit_log.get("action") or "",
            "entityType": audit_log.get("entity_type") or "-",
            "entityId": audit_log.get("entity_id") or "-",
            "details": audit_log.get("details") or {},
            "ipAddress": audit_log.get("ip_address") or "-",
            "userAgent": audit_log.get("user_agent") or "-",
            "createdAt": audit_log.get("created_at") or "",
        }

    def list_admin_audit_logs(self):
        config = self.ensure_admin_request("audit log viewing")
        if not config:
            return

        supabase_url, supabase_service_key = config
        query_string = urlencode(
            {
                "select": (
                    "id,actor_user_id,actor_email,actor_role,action,entity_type,"
                    "entity_id,details,ip_address,user_agent,created_at"
                ),
                "order": "created_at.desc",
                "limit": "500",
            }
        )

        try:
            request = Request(
                f"{supabase_url.rstrip('/')}/rest/v1/audit_logs?{query_string}",
                method="GET",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                },
            )

            with urlopen(request, timeout=15) as response:
                response_payload = json.loads(response.read().decode("utf-8"))

            logs = [self.format_audit_log(log) for log in response_payload or []]
            self.send_json({"logs": logs, "total": len(logs)})
        except HTTPError as error:
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or "Supabase rejected the request."

            self.send_json({"error": message}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load audit logs."}, status=500)

    def list_admin_applications(self):
        config = self.ensure_admin_request("application listing")
        if not config:
            return

        supabase_url, supabase_service_key = config

        try:
            applications = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {
                    "select": "id,permit_id,applicant_id,status,progress,business_info,permit_snapshot,submitted_at,reviewed_at,created_at,updated_at",
                    "order": "created_at.desc",
                    "limit": 200,
                },
            ) or []

            application_ids = [application.get("id") for application in applications if application.get("id")]
            documents_by_application = {}
            ocr_by_application = {}
            assignments_by_application = {}

            if application_ids:
                id_filter = f"in.({','.join(application_ids)})"
                documents = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "application_documents",
                    {
                        "select": "id,application_id,permit_document_id,file_name,file_url,upload_status,ocr_status,ocr_extracted_fields,created_at,updated_at",
                        "application_id": id_filter,
                        "order": "created_at.asc",
                    },
                ) or []
                ocr_results = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "application_ocr_results",
                    {
                        "select": "id,application_id,application_document_id,document_type,extracted_fields,ocr_status,error_message,created_at",
                        "application_id": id_filter,
                        "order": "created_at.desc",
                    },
                ) or []
                assignments = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "department_application_assignments",
                    {
                        "select": "id,application_id,department_key,evaluation_status,verification_status,remarks,created_at,updated_at",
                        "application_id": id_filter,
                        "deleted_at": "is.null",
                        "order": "created_at.asc",
                    },
                ) or []

                for document in documents:
                    documents_by_application.setdefault(document.get("application_id"), []).append(document)
                for ocr_result in ocr_results:
                    ocr_by_application.setdefault(ocr_result.get("application_id"), []).append(ocr_result)
                for assignment in assignments:
                    assignments_by_application.setdefault(assignment.get("application_id"), []).append(assignment)

            formatted = []
            for application in applications:
                application_id = application.get("id")
                business_info = application.get("business_info") or {}
                formatted.append(
                    {
                        "id": application_id,
                        "referenceNumber": (application_id or "")[:8],
                        "businessName": business_info.get("business_name") or business_info.get("businessName") or "",
                        "ownerName": business_info.get("owner_name") or " ".join(
                            part
                            for part in [
                                business_info.get("first_name"),
                                business_info.get("middle_name"),
                                business_info.get("last_name"),
                            ]
                            if part
                        ).strip(),
                        "status": application.get("status") or "",
                        "progress": application.get("progress") or "",
                        "submittedAt": application.get("submitted_at") or "",
                        "businessInfo": business_info,
                        "permit": application.get("permit_snapshot") or {},
                        "documents": documents_by_application.get(application_id, []),
                        "ocrResults": ocr_by_application.get(application_id, []),
                        "officeProgress": assignments_by_application.get(application_id, []),
                        "createdAt": application.get("created_at") or "",
                        "updatedAt": application.get("updated_at") or "",
                    }
                )

            self.send_json({"applications": formatted, "total": len(formatted)})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load applications.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load applications."}, status=500)

    def admin_config_with_actor(self, action_label):
        config = self.ensure_admin_request(action_label)
        if not config:
            return None
        supabase_url, supabase_service_key = config
        try:
            return {
                "supabase_url": supabase_url,
                "supabase_service_key": supabase_service_key,
                "actor": self.get_request_actor(supabase_url),
            }
        except HTTPError:
            self.send_json({"error": "Invalid or expired staff session."}, status=401)
            return None

    def safe_float(self, value, default=0):
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def money(self, value):
        return round(self.safe_float(value), 2)

    def generate_workflow_number(self, prefix):
        return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:5].upper()}"

    def app_owner_name(self, business_info):
        return (
            business_info.get("owner_name")
            or " ".join(
                part
                for part in [
                    business_info.get("first_name") or business_info.get("firstName"),
                    business_info.get("middle_name") or business_info.get("middleName"),
                    business_info.get("last_name") or business_info.get("lastName"),
                ]
                if part
            ).strip()
            or "-"
        )

    def app_business_name(self, business_info):
        return business_info.get("business_name") or business_info.get("businessName") or "-"

    def app_business_address(self, business_info):
        return (
            business_info.get("business_address")
            or business_info.get("businessAddress")
            or " ".join(
                part
                for part in [
                    business_info.get("unit_street") or business_info.get("unitStreet"),
                    business_info.get("business_barangay") or business_info.get("businessBarangay"),
                    business_info.get("business_municipality") or business_info.get("businessMunicipality"),
                ]
                if part
            ).strip()
            or "-"
        )

    def load_application_core(self, supabase_url, service_key, application_id):
        rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "applications",
            {
                "select": "id,permit_id,applicant_id,status,progress,payment_status,assessment_status,business_info,permit_snapshot,business_classification_id,submitted_at,reviewed_at,initial_reviewed_by,initial_reviewed_at,finalized_by,finalized_at,created_at,updated_at",
                "id": f"eq.{application_id}",
                "limit": 1,
            },
        ) or []
        return rows[0] if rows else None

    def load_application_bundle(self, supabase_url, service_key, application_id):
        application = self.load_application_core(supabase_url, service_key, application_id)
        if not application:
            return None

        documents = self.supabase_rest_request(
            supabase_url,
            service_key,
            "application_documents",
            {
                "select": "id,application_id,permit_document_id,document_snapshot,file_name,file_url,upload_status,ocr_status,remarks,uploaded_at,created_at,updated_at",
                "application_id": f"eq.{application_id}",
                "order": "created_at.asc",
            },
        ) or []
        doc_reviews = self.supabase_rest_request(
            supabase_url,
            service_key,
            "application_document_reviews",
            {
                "select": "*",
                "application_id": f"eq.{application_id}",
                "is_deleted": "eq.false",
                "order": "created_at.desc",
            },
        ) or []
        department_reviews = self.supabase_rest_request(
            supabase_url,
            service_key,
            "application_department_reviews",
            {
                "select": "*",
                "application_id": f"eq.{application_id}",
                "order": "assigned_at.asc",
            },
        ) or []
        assessment_rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "assessments",
            {"select": "*", "application_id": f"eq.{application_id}", "limit": 1},
        ) or []
        assessment = assessment_rows[0] if assessment_rows else None
        assessment_items = []
        if assessment:
            assessment_items = self.supabase_rest_request(
                supabase_url,
                service_key,
                "assessment_items",
                {
                    "select": "*",
                    "assessment_id": f"eq.{assessment.get('id')}",
                    "is_active": "eq.true",
                    "order": "department_key.asc,created_at.asc",
                },
            ) or []
        queue_rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "treasury_payment_queue",
            {"select": "*", "application_id": f"eq.{application_id}", "order": "created_at.desc", "limit": 1},
        ) or []
        payment_rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "payments",
            {"select": "*", "application_id": f"eq.{application_id}", "order": "created_at.desc", "limit": 5},
        ) or []
        receipt_rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "official_receipts",
            {"select": "*", "application_id": f"eq.{application_id}", "order": "issued_at.desc", "limit": 5},
        ) or []
        permit_rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "business_permits",
            {"select": "*", "application_id": f"eq.{application_id}", "limit": 1},
        ) or []
        profile = self.get_profile_by_auth_user_id(supabase_url, service_key, application.get("applicant_id")) or {}
        classification = None
        if application.get("business_classification_id"):
            classification = self.supabase_rest_request(
                supabase_url,
                service_key,
                "business_classifications",
                {
                    "select": "id,name,parent_category",
                    "id": f"eq.{application.get('business_classification_id')}",
                    "limit": 1,
                },
            ) or []
            classification = classification[0] if classification else None

        return {
            "application": application,
            "applicant": self.format_profile(profile) if profile else {},
            "classification": classification or {},
            "documents": documents,
            "documentReviews": doc_reviews,
            "departmentReviews": department_reviews,
            "assessment": assessment,
            "assessmentItems": assessment_items,
            "treasuryQueue": queue_rows[0] if queue_rows else None,
            "payments": payment_rows,
            "receipts": receipt_rows,
            "businessPermit": permit_rows[0] if permit_rows else None,
        }

    def get_admin_application_review(self, application_id):
        config = self.ensure_admin_request("application review")
        if not config:
            return
        supabase_url, service_key = config
        try:
            bundle = self.load_application_bundle(supabase_url, service_key, application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return
            self.create_service_audit_log(
                supabase_url,
                service_key,
                "application_viewed",
                actor=self.get_request_actor(supabase_url),
                entity_type="application",
                entity_id=application_id,
            )
            self.send_json({"application": self.format_admin_review_bundle(bundle)})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load application review.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load application review."}, status=500)

    def format_admin_review_bundle(self, bundle):
        app = bundle["application"]
        info = app.get("business_info") or {}
        permit = app.get("permit_snapshot") or {}
        classification = bundle.get("classification") or {}
        assessment = bundle.get("assessment") or {}
        items = bundle.get("assessmentItems") or []
        department_totals = {}
        for item in items:
            key = item.get("department_key") or "bplo"
            department_totals[key] = department_totals.get(key, 0) + self.money(item.get("final_amount"))

        return {
            "id": app.get("id"),
            "controlNumber": (app.get("id") or "")[:8],
            "applicationType": info.get("application_type") or info.get("applicationType") or "New Application",
            "permitType": permit.get("permitName") or permit.get("permit_name") or "Business Permit",
            "status": app.get("status") or "Draft",
            "progress": app.get("progress") or "",
            "paymentStatus": app.get("payment_status") or "Unpaid",
            "assessmentStatus": app.get("assessment_status") or "Draft",
            "submittedAt": app.get("submitted_at") or app.get("created_at") or "",
            "updatedAt": app.get("updated_at") or "",
            "reviewedAt": app.get("initial_reviewed_at") or app.get("reviewed_at") or "",
            "applicant": {
                "name": (bundle.get("applicant") or {}).get("name") or self.app_owner_name(info),
                "email": (bundle.get("applicant") or {}).get("email") or info.get("email") or "",
                "contactNumber": (bundle.get("applicant") or {}).get("contactNumber") or info.get("contact_number") or "",
                "address": info.get("home_address") or info.get("residential_address") or "",
                "verificationStatus": (bundle.get("applicant") or {}).get("status") or "-",
            },
            "business": {
                "name": self.app_business_name(info),
                "tradeName": info.get("trade_name") or info.get("tradeName") or "",
                "classification": classification.get("name") or info.get("business_classification") or "",
                "parentCategory": classification.get("parent_category") or info.get("business_parent_category") or "",
                "ownershipType": info.get("ownership_type") or info.get("ownershipType") or "",
                "address": self.app_business_address(info),
                "tin": info.get("tin") or "",
                "registrationNumber": info.get("registration_number") or info.get("dti_sec_cda_number") or "",
                "capitalInvestment": info.get("capital_investment") or info.get("capitalInvestment") or "",
                "grossSales": info.get("gross_sales") or info.get("grossSales") or "",
                "employees": info.get("number_of_employees") or info.get("numberOfEmployees") or "",
                "businessArea": info.get("business_area") or info.get("businessArea") or "",
                "deliveryVehicles": info.get("delivery_vehicles") or info.get("deliveryVehicles") or "",
                "signboardArea": info.get("signboard_area") or info.get("signboardArea") or "",
                "storageArea": info.get("storage_area") or info.get("storageArea") or "",
            },
            "documents": bundle.get("documents") or [],
            "documentReviews": bundle.get("documentReviews") or [],
            "departmentReviews": bundle.get("departmentReviews") or [],
            "assessment": assessment,
            "assessmentItems": items,
            "departmentTotals": department_totals,
            "treasuryQueue": bundle.get("treasuryQueue"),
            "payments": bundle.get("payments") or [],
            "receipts": bundle.get("receipts") or [],
            "businessPermit": bundle.get("businessPermit"),
        }

    def get_or_create_assessment(self, config, application_id):
        rows = self.service_rest_request(
            config,
            "assessments",
            query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "limit": "1"}),
        ) or []
        if rows:
            return rows[0]
        created = self.service_rest_request(
            config,
            "assessments",
            method="POST",
            payload={
                "application_id": application_id,
                "assessment_number": self.generate_workflow_number("SOA"),
                "status": "In Progress",
            },
            prefer="return=representation",
        ) or []
        return created[0] if created else None

    def recalculate_assessment(self, config, assessment_id):
        items = self.service_rest_request(
            config,
            "assessment_items",
            query=urlencode({"select": "*", "assessment_id": f"eq.{assessment_id}", "is_active": "eq.true"}),
        ) or []
        subtotal = sum(self.money(item.get("amount")) for item in items)
        penalties = sum(self.money(item.get("penalty")) for item in items)
        discounts = sum(self.money(item.get("discount")) for item in items)
        grand_total = sum(self.money(item.get("final_amount")) for item in items)
        updated = self.service_rest_request(
            config,
            "assessments",
            method="PATCH",
            payload={
                "subtotal": subtotal,
                "penalty_total": penalties,
                "discount_total": discounts,
                "grand_total": grand_total,
                "updated_at": utc_now_iso(),
            },
            query=urlencode({"id": f"eq.{assessment_id}"}),
            prefer="return=representation",
        ) or []
        return updated[0] if updated else None

    def approve_admin_initial_review(self, application_id):
        config = self.admin_config_with_actor("initial review approval")
        if not config:
            return
        try:
            app = self.load_application_core(config["supabase_url"], config["supabase_service_key"], application_id)
            if not app:
                self.send_json({"error": "Application not found."}, status=404)
                return
            if app.get("status") in {"Rejected", "Permit Ready for Release", "Released"}:
                self.send_json({"error": "This application can no longer be approved for initial review."}, status=400)
                return
            documents = self.service_rest_request(
                config,
                "application_documents",
                query=urlencode({"select": "id,upload_status", "application_id": f"eq.{application_id}"}),
            ) or []
            missing = [doc for doc in documents if doc.get("upload_status") != "Uploaded"]
            if missing:
                self.send_json({"error": "You cannot approve this application because required documents are still pending."}, status=400)
                return

            now = utc_now_iso()
            self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={
                    "status": "Under Department Evaluation",
                    "progress": "Department Evaluation",
                    "reviewed_at": now,
                    "initial_reviewed_at": now,
                    "initial_reviewed_by": config["actor"].get("id"),
                    "updated_at": now,
                },
                query=urlencode({"id": f"eq.{application_id}"}),
                prefer="return=representation",
            )
            routing_result = self.create_required_department_reviews(config, app)
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "initial_review_approved",
                actor=config["actor"],
                entity_type="application",
                entity_id=application_id,
            )
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                "Initial Review Approved",
                "Your application passed BPLO initial review and has been forwarded to the required offices.",
                notification_type="status",
                source_role="BPLO",
            )
            info = app.get("business_info") or {}
            self.send_json(
                {
                    "message": "Initial review approved and routed to required departments.",
                    "routing": routing_result,
                    "application": {
                        "id": application_id,
                        "controlNumber": (application_id or "")[:8],
                        "businessName": self.app_business_name(info),
                        "applicantName": self.app_owner_name(info),
                        "status": "Under Department Evaluation",
                        "progress": "Department Evaluation",
                    },
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to approve initial review.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to approve initial review."}, status=500)

    def create_required_department_reviews(self, config, application):
        permit_id = application.get("permit_id")
        offices = self.service_rest_request(
            config,
            "permit_required_offices",
            query=urlencode({"select": "office_id", "permit_id": f"eq.{permit_id}"}),
        ) or []
        office_ids = [item.get("office_id") for item in offices if item.get("office_id")]
        departments = []
        if office_ids:
            departments = self.service_rest_request(
                config,
                "departments",
                query=urlencode({"select": "id,name,status", "id": f"in.({','.join(office_ids)})", "status": "eq.Active"}),
            ) or []
        now = utc_now_iso()
        routed_departments = []
        total_notifications = 0
        for department in departments:
            department_key = department_key_from_name(department.get("name"))
            if not department_key:
                continue
            review_created = False
            legacy_visible = False
            route_state = "existing"
            review_payload = {
                "application_id": application.get("id"),
                "department_id": department.get("id"),
                "department_key": department_key,
                "status": "Pending",
                "assigned_at": now,
                "updated_at": now,
            }
            existing_reviews = self.service_rest_request(
                config,
                "application_department_reviews",
                query=urlencode({"select": "id,status", "application_id": f"eq.{application.get('id')}", "department_key": f"eq.{department_key}", "limit": "1"}),
            ) or []
            if existing_reviews:
                if existing_reviews[0].get("status") in {"Not Started", "Pending"}:
                    self.service_rest_request(
                        config,
                        "application_department_reviews",
                        method="PATCH",
                        payload={"department_id": department.get("id"), "status": "Pending", "updated_at": now},
                        query=urlencode({"id": f"eq.{existing_reviews[0].get('id')}"}),
                    )
                    route_state = "refreshed"
            else:
                self.service_rest_request(config, "application_department_reviews", method="POST", payload=review_payload, prefer="return=representation")
                review_created = True
                route_state = "created"

            legacy_payload = {
                "application_id": application.get("id"),
                "department_key": department_key,
                "evaluation_status": "Pending",
                "verification_status": "Unverified",
                "assigned_by": config["actor"].get("id"),
                "updated_at": now,
            }
            try:
                existing_assignments = self.service_rest_request(
                    config,
                    "department_application_assignments",
                    query=urlencode({"select": "id,evaluation_status", "application_id": f"eq.{application.get('id')}", "department_key": f"eq.{department_key}", "deleted_at": "is.null", "limit": "1"}),
                ) or []
                if existing_assignments:
                    if existing_assignments[0].get("evaluation_status") == "Pending":
                        self.service_rest_request(
                            config,
                            "department_application_assignments",
                            method="PATCH",
                            payload=legacy_payload,
                            query=urlencode({"id": f"eq.{existing_assignments[0].get('id')}"}),
                        )
                    legacy_visible = True
                else:
                    self.service_rest_request(config, "department_application_assignments", method="POST", payload=legacy_payload, prefer="return=representation")
                    review_created = True
                    legacy_visible = True
            except HTTPError:
                pass

            notification_count = 0
            if review_created:
                notification_count = self.notify_department_assignment(config, department, application)
                total_notifications += notification_count
            routed_departments.append(
                {
                    "id": department.get("id"),
                    "name": department.get("name") or department_key.replace("_", " ").title(),
                    "key": department_key,
                    "routeState": route_state,
                    "applicationVisible": True,
                    "legacyVisible": legacy_visible,
                    "notificationsSent": notification_count,
                }
            )
        return {
            "departments": routed_departments,
            "departmentCount": len(routed_departments),
            "notificationsSent": total_notifications,
        }

    def sync_department_review_status(self, config, application_id, department_key, status, remarks):
        now = utc_now_iso()
        status_map = {
            "Pending": "Under Review",
            "Approved": "Approved",
            "Rejected": "Rejected",
        }
        review_status = status_map.get(status, "Under Review")
        review_payload = {
            "status": review_status,
            "remarks": remarks,
            "updated_at": now,
        }
        if review_status == "Under Review":
            review_payload["started_at"] = now
        if review_status == "Approved":
            review_payload["approved_at"] = now
            review_payload["completed_at"] = now
        if review_status == "Rejected":
            review_payload["rejected_at"] = now
            review_payload["completed_at"] = now

        rows = self.service_rest_request(
            config,
            "application_department_reviews",
            query=urlencode({"select": "id", "application_id": f"eq.{application_id}", "department_key": f"eq.{department_key}", "limit": "1"}),
        ) or []
        if rows:
            self.service_rest_request(
                config,
                "application_department_reviews",
                method="PATCH",
                payload=review_payload,
                query=urlencode({"id": f"eq.{rows[0].get('id')}"}),
            )
        else:
            self.service_rest_request(
                config,
                "application_department_reviews",
                method="POST",
                payload={
                    "application_id": application_id,
                    "department_id": config.get("department_id"),
                    "department_key": department_key,
                    "assigned_user_id": config["actor"].get("id"),
                    "assigned_at": now,
                    **review_payload,
                },
                prefer="return=representation",
            )

        reviews = self.service_rest_request(
            config,
            "application_department_reviews",
            query=urlencode({"select": "status", "application_id": f"eq.{application_id}"}),
        ) or []
        if not reviews:
            return

        statuses = [row.get("status") or "Pending" for row in reviews]
        approved_count = sum(1 for value in statuses if value in {"Approved", "Completed"})
        total_count = len(statuses)
        if any(value == "Rejected" for value in statuses):
            app_status = "Department Review Needs Action"
            progress = "Department Review"
        elif total_count and approved_count == total_count:
            app_status = "Ready for Assessment"
            progress = "Department Review Complete"
        else:
            app_status = "Under Department Evaluation"
            progress = f"Department Evaluation ({approved_count}/{total_count} approved)"

        self.service_rest_request(
            config,
            "applications",
            method="PATCH",
            payload={"status": app_status, "progress": progress, "updated_at": now},
            query=urlencode({"id": f"eq.{application_id}"}),
        )

    def reject_admin_application(self, application_id):
        self.change_admin_application_status(application_id, "Rejected", "Rejected", "application_rejected", "Application Rejected")

    def request_admin_application_revision(self, application_id):
        self.change_admin_application_status(application_id, "For Revision", "Revision Requested", "revision_requested", "Revision Requested")

    def change_admin_application_status(self, application_id, status, progress, audit_action, title):
        config = self.admin_config_with_actor(status.lower())
        if not config:
            return
        try:
            payload = self.read_json_body()
            remarks = (payload.get("remarks") or payload.get("reason") or "").strip()
            if status in {"Rejected", "For Revision"} and not remarks:
                self.send_json({"error": "Remarks are required for this action."}, status=400)
                return
            rows = self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={"status": status, "progress": progress, "updated_at": utc_now_iso()},
                query=urlencode({"id": f"eq.{application_id}"}),
                prefer="return=representation",
            ) or []
            if not rows:
                self.send_json({"error": "Application not found."}, status=404)
                return
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                audit_action,
                actor=config["actor"],
                entity_type="application",
                entity_id=application_id,
                details={"remarks": remarks},
            )
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                title,
                remarks or f"Your application status is now {status}.",
                notification_type="status",
                source_role="BPLO",
            )
            self.send_json({"message": f"Application updated to {status}.", "application": rows[0]})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update application status.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update application status."}, status=500)

    def create_admin_document_review(self):
        config = self.admin_config_with_actor("document review")
        if not config:
            return
        try:
            payload = self.read_json_body()
            status = (payload.get("status") or "Under Review").strip()
            if status not in {"Pending", "Under Review", "Verified", "Rejected", "For Revision", "Resubmitted"}:
                self.send_json({"error": "Select a valid document review status."}, status=400)
                return
            review = {
                "application_id": (payload.get("applicationId") or "").strip(),
                "document_id": (payload.get("documentId") or "").strip(),
                "reviewer_id": config["actor"].get("id"),
                "department_key": (payload.get("departmentKey") or "bplo").strip(),
                "status": status,
                "remarks": (payload.get("remarks") or "").strip(),
                "reviewed_at": utc_now_iso(),
            }
            if not review["application_id"] or not review["document_id"]:
                self.send_json({"error": "Application and document are required."}, status=400)
                return
            rows = self.service_rest_request(config, "application_document_reviews", method="POST", payload=review, prefer="return=representation") or []
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "document_reviewed", actor=config["actor"], entity_type="application_document", entity_id=review["document_id"], details={"status": status})
            self.send_json({"message": "Document review saved.", "review": rows[0] if rows else {}}, status=201)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to save document review.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to save document review."}, status=500)

    def update_admin_document_review(self, review_id):
        config = self.admin_config_with_actor("document review update")
        if not config:
            return
        try:
            payload = self.read_json_body()
            update = {
                "status": (payload.get("status") or "Under Review").strip(),
                "remarks": (payload.get("remarks") or "").strip(),
                "reviewed_at": utc_now_iso(),
                "updated_at": utc_now_iso(),
            }
            rows = self.service_rest_request(config, "application_document_reviews", method="PATCH", payload=update, query=urlencode({"id": f"eq.{review_id}", "is_deleted": "eq.false"}), prefer="return=representation") or []
            if not rows:
                self.send_json({"error": "Document review not found."}, status=404)
                return
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "document_review_updated", actor=config["actor"], entity_type="application_document_review", entity_id=review_id, details=update)
            self.send_json({"message": "Document review updated.", "review": rows[0]})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update document review.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update document review."}, status=500)

    def get_admin_application_assessment(self, application_id):
        config = self.admin_config_with_actor("assessment viewing")
        if not config:
            return
        try:
            assessment = self.get_or_create_assessment(config, application_id)
            self.recalculate_assessment(config, assessment.get("id"))
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            self.send_json({"assessment": self.format_admin_review_bundle(bundle)})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load assessment.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load assessment."}, status=500)

    def build_assessment_item_payload(self, config, payload, existing=None):
        assessment_id = (payload.get("assessmentId") or (existing or {}).get("assessment_id") or "").strip()
        application_id = (payload.get("applicationId") or (existing or {}).get("application_id") or "").strip()
        quantity = self.safe_float(payload.get("quantity"), 1)
        rate = self.safe_float(payload.get("rate"), 0)
        amount = self.safe_float(payload.get("amount"), quantity * rate)
        penalty = self.safe_float(payload.get("penalty"), 0)
        discount = self.safe_float(payload.get("discount"), 0)
        final_amount = self.safe_float(payload.get("finalAmount"), amount + penalty - discount)
        return {
            "assessment_id": assessment_id,
            "application_id": application_id,
            "department_key": (payload.get("departmentKey") or (existing or {}).get("department_key") or "bplo").strip(),
            "fee_type_id": (payload.get("feeTypeId") or None),
            "fee_name": (payload.get("feeName") or (existing or {}).get("fee_name") or "").strip(),
            "category": (payload.get("category") or (existing or {}).get("category") or "Regulatory Fees and Charges").strip(),
            "computation_basis": (payload.get("computationBasis") or "").strip(),
            "formula_type": (payload.get("formulaType") or (existing or {}).get("formula_type") or "fixed").strip(),
            "quantity": quantity,
            "unit": (payload.get("unit") or "").strip(),
            "rate": rate,
            "percentage": self.safe_float(payload.get("percentage"), 0),
            "base_amount": self.safe_float(payload.get("baseAmount"), amount),
            "amount": self.money(amount),
            "penalty": self.money(penalty),
            "discount": self.money(discount),
            "final_amount": self.money(final_amount),
            "remarks": (payload.get("remarks") or "").strip(),
            "status": (payload.get("status") or "Submitted").strip(),
            "updated_by": config["actor"].get("id"),
            "updated_at": utc_now_iso(),
        }

    def create_admin_assessment_item(self):
        config = self.admin_config_with_actor("assessment item creation")
        if not config:
            return
        try:
            payload = self.read_json_body()
            application_id = (payload.get("applicationId") or "").strip()
            if not application_id:
                self.send_json({"error": "Application is required."}, status=400)
                return
            assessment = self.get_or_create_assessment(config, application_id)
            payload["assessmentId"] = assessment.get("id")
            item = self.build_assessment_item_payload(config, payload)
            if not item["fee_name"]:
                self.send_json({"error": "Fee item name is required."}, status=400)
                return
            item["created_by"] = config["actor"].get("id")
            rows = self.service_rest_request(config, "assessment_items", method="POST", payload=item, prefer="return=representation") or []
            updated_assessment = self.recalculate_assessment(config, assessment.get("id"))
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "fee_created", actor=config["actor"], entity_type="assessment_item", entity_id=(rows[0] if rows else {}).get("id"), details={"feeName": item["fee_name"]})
            self.send_json({"message": "Assessment item added.", "item": rows[0] if rows else {}, "assessment": updated_assessment}, status=201)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to create assessment item.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to create assessment item."}, status=500)

    def update_admin_assessment_item(self, item_id):
        config = self.admin_config_with_actor("assessment item update")
        if not config:
            return
        try:
            existing = self.service_rest_request(config, "assessment_items", query=urlencode({"select": "*", "id": f"eq.{item_id}", "limit": "1"})) or []
            if not existing:
                self.send_json({"error": "Assessment item not found."}, status=404)
                return
            assessment = self.service_rest_request(config, "assessments", query=urlencode({"select": "id,status", "id": f"eq.{existing[0].get('assessment_id')}", "limit": "1"})) or []
            if assessment and assessment[0].get("status") in {"Completed", "For Payment", "Paid"}:
                self.send_json({"error": "This assessment is locked and can no longer be edited."}, status=400)
                return
            item = self.build_assessment_item_payload(config, self.read_json_body(), existing=existing[0])
            item.pop("assessment_id", None)
            item.pop("application_id", None)
            rows = self.service_rest_request(config, "assessment_items", method="PATCH", payload=item, query=urlencode({"id": f"eq.{item_id}", "is_active": "eq.true"}), prefer="return=representation") or []
            updated_assessment = self.recalculate_assessment(config, existing[0].get("assessment_id"))
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "fee_updated", actor=config["actor"], entity_type="assessment_item", entity_id=item_id, details={"feeName": item.get("fee_name")})
            self.send_json({"message": "Assessment item updated.", "item": rows[0] if rows else {}, "assessment": updated_assessment})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update assessment item.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update assessment item."}, status=500)

    def delete_admin_assessment_item(self, item_id):
        config = self.admin_config_with_actor("assessment item removal")
        if not config:
            return
        try:
            existing = self.service_rest_request(config, "assessment_items", query=urlencode({"select": "*", "id": f"eq.{item_id}", "limit": "1"})) or []
            if not existing:
                self.send_json({"error": "Assessment item not found."}, status=404)
                return
            rows = self.service_rest_request(config, "assessment_items", method="PATCH", payload={"is_active": False, "status": "Cancelled", "updated_by": config["actor"].get("id"), "updated_at": utc_now_iso()}, query=urlencode({"id": f"eq.{item_id}"}), prefer="return=representation") or []
            updated_assessment = self.recalculate_assessment(config, existing[0].get("assessment_id"))
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "fee_removed", actor=config["actor"], entity_type="assessment_item", entity_id=item_id, details={"softDelete": True})
            self.send_json({"message": "Assessment item removed.", "item": rows[0] if rows else {}, "assessment": updated_assessment})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to remove assessment item.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to remove assessment item."}, status=500)

    def complete_admin_assessment(self, application_id):
        config = self.admin_config_with_actor("assessment completion")
        if not config:
            return
        try:
            app = self.load_application_core(config["supabase_url"], config["supabase_service_key"], application_id)
            if not app:
                self.send_json({"error": "Application not found."}, status=404)
                return
            if app.get("status") in {"Rejected", "For Revision"}:
                self.send_json({"error": "This application has an unresolved rejection or revision request."}, status=400)
                return
            assessment = self.get_or_create_assessment(config, application_id)
            assessment = self.recalculate_assessment(config, assessment.get("id"))
            items = self.service_rest_request(config, "assessment_items", query=urlencode({"select": "id", "assessment_id": f"eq.{assessment.get('id')}", "is_active": "eq.true"})) or []
            if not items:
                self.send_json({"error": "The assessment cannot be completed because no fee items were submitted."}, status=400)
                return
            now = utc_now_iso()
            updated_assessment = self.service_rest_request(
                config,
                "assessments",
                method="PATCH",
                payload={"status": "For Payment", "completed_by": config["actor"].get("id"), "completed_at": now, "locked_at": now, "updated_at": now},
                query=urlencode({"id": f"eq.{assessment.get('id')}"}),
                prefer="return=representation",
            ) or []
            self.service_rest_request(config, "assessment_items", method="PATCH", payload={"status": "Locked", "updated_at": now}, query=urlencode({"assessment_id": f"eq.{assessment.get('id')}", "is_active": "eq.true"}))
            self.service_rest_request(config, "applications", method="PATCH", payload={"status": "For Payment", "progress": "Payment Required", "assessment_status": "Completed", "payment_status": "For Payment", "updated_at": now}, query=urlencode({"id": f"eq.{application_id}"}))
            queue_rows = self.service_rest_request(
                config,
                "treasury_payment_queue",
                query=urlencode({"select": "*", "assessment_id": f"eq.{assessment.get('id')}", "limit": "1"}),
            ) or []
            if queue_rows:
                queue_rows = self.service_rest_request(
                    config,
                    "treasury_payment_queue",
                    method="PATCH",
                    payload={"status": "Waiting for Payment", "amount_due": assessment.get("grand_total") or 0, "updated_at": now},
                    query=urlencode({"id": f"eq.{queue_rows[0].get('id')}"}),
                    prefer="return=representation",
                ) or queue_rows
            else:
                queue_rows = self.service_rest_request(
                    config,
                    "treasury_payment_queue",
                    method="POST",
                    payload={"application_id": application_id, "assessment_id": assessment.get("id"), "queue_number": self.generate_workflow_number("Q"), "status": "Waiting for Payment", "amount_due": assessment.get("grand_total") or 0},
                    prefer="return=representation",
                ) or []
            info = app.get("business_info") or {}
            try:
                self.service_rest_request(config, "treasury_records", method="POST", payload={"application_no": (application_id or "")[:8], "applicant": self.app_owner_name(info), "business_name": self.app_business_name(info), "amount": assessment.get("grand_total") or 0, "step": "Assessment", "status": "Ready", "current_step": "Payment Queue", "record_type": "payment", "transaction_date": datetime.now(timezone.utc).date().isoformat(), "remarks": "Generated from completed assessment."}, prefer="return=minimal")
            except HTTPError:
                pass
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "assessment_completed", actor=config["actor"], entity_type="assessment", entity_id=assessment.get("id"), details={"grandTotal": assessment.get("grand_total")})
            self.notify_application_owner(config["supabase_url"], config["supabase_service_key"], application_id, "Payment Required", "Your assessment is complete. Please proceed to Treasury for payment.", notification_type="payment", source_role="BPLO")
            self.send_json({"message": "Assessment completed and routed to Treasury.", "assessment": updated_assessment[0] if updated_assessment else assessment, "queue": queue_rows[0] if queue_rows else {}})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to complete assessment.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to complete assessment."}, status=500)

    def finalize_admin_application(self, application_id):
        config = self.admin_config_with_actor("application finalization")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return
            app = bundle["application"]
            payments = bundle.get("payments") or []
            confirmed_payment = next((payment for payment in payments if payment.get("payment_status") == "Confirmed"), None)
            if not confirmed_payment:
                self.send_json({"error": "This application cannot be finalized because payment has not been verified."}, status=400)
                return
            if bundle.get("businessPermit"):
                self.send_json({"message": "Business permit was already generated.", "permit": bundle.get("businessPermit")})
                return

            info = app.get("business_info") or {}
            permit_snapshot = app.get("permit_snapshot") or {}
            issue_date = datetime.now(timezone.utc).date()
            expiration_date = issue_date.replace(year=issue_date.year + 1)
            permit_number = self.generate_workflow_number("BP")
            verification_code = self.generate_workflow_number("VERIFY")
            permit_payload = {
                "application_id": application_id,
                "permit_number": permit_number,
                "control_number": (application_id or "")[:8],
                "business_name": self.app_business_name(info),
                "owner_name": self.app_owner_name(info),
                "business_classification": (bundle.get("classification") or {}).get("name") or info.get("business_classification") or "",
                "business_address": self.app_business_address(info),
                "permit_type": permit_snapshot.get("permitName") or permit_snapshot.get("permit_name") or "Business Permit",
                "issue_date": issue_date.isoformat(),
                "expiration_date": expiration_date.isoformat(),
                "status": "Ready for Release",
                "verification_code": verification_code,
                "qr_code_value": f"BPLO:{permit_number}:{verification_code}",
                "issued_by": config["actor"].get("id"),
            }
            rows = self.service_rest_request(config, "business_permits", method="POST", payload=permit_payload, prefer="return=representation") or []
            self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={"status": "Permit Ready for Release", "progress": "Permit Generated", "finalized_by": config["actor"].get("id"), "finalized_at": utc_now_iso(), "updated_at": utc_now_iso()},
                query=urlencode({"id": f"eq.{application_id}"}),
            )
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "permit_generated", actor=config["actor"], entity_type="business_permit", entity_id=(rows[0] if rows else {}).get("id"), details={"permitNumber": permit_number})
            self.send_json({"message": "Application finalized and business permit generated.", "permit": rows[0] if rows else permit_payload})
        except ValueError:
            self.send_json({"error": "Unable to calculate the permit expiration date."}, status=500)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to finalize application.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to finalize application."}, status=500)

    def release_admin_business_permit(self, application_id):
        config = self.admin_config_with_actor("business permit release")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return

            permit = bundle.get("businessPermit")
            if not permit:
                self.send_json({"error": "Finalize the application before releasing the business permit."}, status=400)
                return

            app = bundle["application"]
            current_status = app.get("status") or ""
            if current_status == "Released":
                self.send_json({"message": "Business permit has already been released.", "permit": permit})
                return

            now = utc_now_iso()
            self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={"status": "Released", "progress": "Permit Released", "updated_at": now},
                query=urlencode({"id": f"eq.{application_id}"}),
            )
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "permit_released_for_pickup",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"permitNumber": permit.get("permit_number"), "applicationId": application_id},
            )
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                "Business Permit Ready for Pickup",
                "Your business permit is ready to be claimed at the BPLO office. Please bring your claim requirements upon pickup.",
                notification_type="permit",
                source_role="BPLO",
            )
            self.send_json({"message": "Business permit released successfully and applicant notified for pickup.", "permit": permit})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to release the business permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to release the business permit."}, status=500)

    def list_treasury_payment_queue(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            rows = self.service_rest_request(
                config,
                "treasury_payment_queue",
                query=urlencode({"select": "*,assessments(*),applications(id,status,business_info,permit_snapshot)", "order": "queued_at.desc", "limit": "300"}),
            ) or []
            queue = []
            for row in rows:
                app = row.get("applications") or {}
                info = app.get("business_info") or {}
                assessment = row.get("assessments") or {}
                queue.append(
                    {
                        "id": row.get("id"),
                        "applicationId": row.get("application_id"),
                        "assessmentId": row.get("assessment_id"),
                        "queueNumber": row.get("queue_number"),
                        "status": row.get("status"),
                        "amountDue": self.money(row.get("amount_due")),
                        "queuedAt": row.get("queued_at"),
                        "controlNumber": (row.get("application_id") or "")[:8],
                        "assessmentNumber": assessment.get("assessment_number") or "",
                        "applicant": self.app_owner_name(info),
                        "businessName": self.app_business_name(info),
                        "permitType": (app.get("permit_snapshot") or {}).get("permitName") or (app.get("permit_snapshot") or {}).get("permit_name") or "Business Permit",
                    }
                )
            self.send_json({"queue": queue, "total": len(queue)})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to load Treasury payment queue.")

    def confirm_treasury_payment(self, queue_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            payload = self.read_json_body()
            amount_paid = self.safe_float(payload.get("amountPaid"), 0)
            payment_method = (payload.get("paymentMethod") or "Cash").strip()
            remarks = (payload.get("remarks") or "").strip()
            queue_rows = self.service_rest_request(config, "treasury_payment_queue", query=urlencode({"select": "*", "id": f"eq.{queue_id}", "limit": "1"})) or []
            if not queue_rows:
                self.send_json({"error": "Payment queue record not found."}, status=404)
                return
            queue = queue_rows[0]
            amount_due = self.safe_float(queue.get("amount_due"), 0)
            if queue.get("status") == "Paid":
                self.send_json({"error": "This payment has already been confirmed."}, status=400)
                return
            if amount_paid < amount_due:
                self.send_json({"error": "Amount paid is below the amount due."}, status=400)
                return
            or_number = (payload.get("officialReceiptNumber") or self.generate_workflow_number("OR")).strip()
            payment_payload = {
                "application_id": queue.get("application_id"),
                "assessment_id": queue.get("assessment_id"),
                "queue_id": queue_id,
                "payment_reference": self.generate_workflow_number("PAY"),
                "amount_due": amount_due,
                "amount_paid": amount_paid,
                "change_amount": self.money(amount_paid - amount_due),
                "payment_method": payment_method,
                "payment_status": "Confirmed",
                "official_receipt_number": or_number,
                "paid_at": utc_now_iso(),
                "cashier_id": config["actor"].get("id"),
                "remarks": remarks,
            }
            payments = self.service_rest_request(config, "payments", method="POST", payload=payment_payload, prefer="return=representation") or []
            payment = payments[0] if payments else payment_payload
            receipts = self.service_rest_request(
                config,
                "official_receipts",
                method="POST",
                payload={"payment_id": payment.get("id"), "application_id": queue.get("application_id"), "receipt_number": or_number, "issued_by": config["actor"].get("id"), "status": "Issued"},
                prefer="return=representation",
            ) or []
            now = utc_now_iso()
            self.service_rest_request(config, "treasury_payment_queue", method="PATCH", payload={"status": "Paid", "completed_at": now, "assigned_cashier_id": config["actor"].get("id"), "updated_at": now}, query=urlencode({"id": f"eq.{queue_id}"}))
            self.service_rest_request(config, "assessments", method="PATCH", payload={"status": "Paid", "updated_at": now}, query=urlencode({"id": f"eq.{queue.get('assessment_id')}"}))
            self.service_rest_request(config, "applications", method="PATCH", payload={"status": "Payment Verified", "progress": "Ready for Finalization", "payment_status": "Payment Verified", "assessment_status": "Paid", "updated_at": now}, query=urlencode({"id": f"eq.{queue.get('application_id')}"}))
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "payment_confirmed", actor=config["actor"], entity_type="payment", entity_id=payment.get("id"), details={"officialReceiptNumber": or_number, "amountPaid": amount_paid})
            self.notify_application_owner(config["supabase_url"], config["supabase_service_key"], queue.get("application_id"), "Payment Confirmed", f"Your payment was verified. Official Receipt No. {or_number}.", notification_type="payment", source_role="Treasury")
            self.send_json({"message": "Payment confirmed and official receipt generated.", "payment": payment, "receipt": receipts[0] if receipts else {}})
        except HTTPError as error:
            self.treasury_error(error, "Unable to confirm payment.")
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to confirm payment.")

    def ensure_department_request(self):
        supabase_url, supabase_client_key, supabase_service_key, _admin_email = self.get_admin_api_config()

        if not supabase_url or not supabase_client_key or not supabase_service_key:
            self.send_json(
                {
                    "error": (
                        "Department office access is not configured. Set SUPABASE_URL, "
                        "SUPABASE_ANON_KEY or SUPABASE_PUBLISHABLE_KEY, and "
                        "SUPABASE_SERVICE_ROLE_KEY in .env."
                    )
                },
                status=500,
            )
            return None

        auth_header = self.headers.get("Authorization", "")
        access_token = auth_header.removeprefix("Bearer ").strip()
        if not access_token:
            self.send_json({"error": "Please log in as a department office user."}, status=401)
            return None

        try:
            actor = self.get_session_user(access_token, supabase_url, supabase_client_key)
        except HTTPError:
            self.send_json({"error": "Invalid or expired session."}, status=401)
            return None

        profile = self.get_profile_by_auth_user_id(supabase_url, supabase_service_key, actor.get("id"))
        if not profile:
            self.send_json({"error": "No centralized user profile was found for this account."}, status=403)
            return None

        role = normalize_role(profile.get("role"))
        status = profile_status(profile.get("status"))
        department = self.load_department_by_id(supabase_url, supabase_service_key, profile.get("department_id"))
        department_name = (department or {}).get("name") or profile.get("department_name")
        department_key = profile.get("department_key") or department_key_from_name(department_name)

        if status != "active":
            self.send_json({"error": f"This account is {status} and cannot access the dashboard."}, status=403)
            return None

        if role != "department_office" or not department_key:
            self.send_json(
                {
                    "error": (
                        "This page is only for department office accounts. "
                        "Ask an admin to assign this account to an active department."
                    )
                },
                status=403,
            )
            return None

        return {
            "supabase_url": supabase_url,
            "supabase_service_key": supabase_service_key,
            "actor": actor,
            "profile": profile,
            "department_id": profile.get("department_id"),
            "department_key": department_key,
            "department_name": department_name or department_key.replace("_", " ").title(),
        }

    def service_rest_request(self, config, table, method="GET", payload=None, query=None, prefer=None):
        url = f"{config['supabase_url'].rstrip('/')}/rest/v1/{table}"
        if query:
            url = f"{url}?{query}"

        data = None
        headers = {
            "apikey": config["supabase_service_key"],
            "Authorization": f"Bearer {config['supabase_service_key']}",
        }

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if prefer:
            headers["Prefer"] = prefer

        request = Request(url, data=data, method=method, headers=headers)
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            if not body:
                return None
            return json.loads(body)

    def department_error(self, error, fallback):
        if isinstance(error, HTTPError):
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or fallback
            self.send_json({"error": message}, status=error.code)
            return

        self.send_json({"error": str(error) or fallback}, status=500)

    def get_department_profile(self):
        config = self.ensure_department_request()
        if not config:
            return

        actor = config["actor"]
        profile = self.format_profile(config["profile"])
        self.send_json(
            {
                "user": {
                    "id": actor.get("id"),
                    "email": actor.get("email"),
                    "name": profile["name"] or actor.get("email") or "Department user",
                    "role": profile["role"],
                    "departmentKey": config["department_key"],
                    "departmentName": config["department_name"],
                }
            }
        )

    def format_department_assignment(self, assignment):
        application = assignment.get("applications") or {}
        payload = application.get("business_info") or {}
        permit_snapshot = application.get("permit_snapshot") or {}
        applicant_name = " ".join(
            part
            for part in [
                payload.get("first_name") or payload.get("firstName"),
                payload.get("middle_name") or payload.get("middleName"),
                payload.get("last_name") or payload.get("lastName"),
            ]
            if part
        ).strip()
        return {
            "assignmentId": assignment.get("id"),
            "applicationId": assignment.get("application_id"),
            "referenceNumber": (application.get("id") or "-")[:8],
            "businessName": payload.get("business_name") or payload.get("businessName") or "-",
            "status": assignment.get("evaluation_status") or "Pending",
            "remarks": assignment.get("remarks") or "",
            "verificationStatus": assignment.get("verification_status") or "Unverified",
            "inspectionDate": assignment.get("inspection_date") or "",
            "inspectionTime": assignment.get("inspection_time") or "",
            "inspectionRemarks": assignment.get("inspection_remarks") or "",
            "assignedAt": assignment.get("created_at") or "",
            "applicant": {
                "name": applicant_name or payload.get("owner_name") or "",
                "email": payload.get("email") or payload.get("business_email") or payload.get("businessEmail") or "",
                "contact": payload.get("contact_number") or payload.get("business_mobile") or payload.get("businessMobile") or "",
                "address": payload.get("home_address") or payload.get("business_address") or payload.get("businessAddress") or "",
            },
            "application": {
                "type": permit_snapshot.get("permitName") or permit_snapshot.get("permit_name") or "",
                "status": application.get("status") or "",
                "progress": application.get("progress") or "",
                "submittedId": (application.get("id") or "")[:8],
                "submittedAt": application.get("submitted_at") or application.get("created_at") or "",
                "payload": payload,
            },
        }

    def format_department_review_assignment(self, review):
        application = review.get("applications") or {}
        payload = application.get("business_info") or {}
        permit_snapshot = application.get("permit_snapshot") or {}
        applicant_name = " ".join(
            part
            for part in [
                payload.get("first_name") or payload.get("firstName"),
                payload.get("middle_name") or payload.get("middleName"),
                payload.get("last_name") or payload.get("lastName"),
            ]
            if part
        ).strip()
        status = review.get("status") or "Pending"
        if status == "Not Started":
            status = "Pending"
        if status == "Completed":
            status = "Approved"
        return {
            "assignmentId": review.get("id"),
            "applicationId": review.get("application_id"),
            "referenceNumber": (application.get("id") or "-")[:8],
            "businessName": payload.get("business_name") or payload.get("businessName") or "-",
            "status": status,
            "remarks": review.get("remarks") or "",
            "verificationStatus": "Verified" if status in {"Approved", "Completed"} else "Unverified",
            "inspectionDate": "",
            "inspectionTime": "",
            "inspectionRemarks": "",
            "assignedAt": review.get("assigned_at") or review.get("created_at") or "",
            "applicant": {
                "name": applicant_name or payload.get("owner_name") or "",
                "email": payload.get("email") or payload.get("business_email") or payload.get("businessEmail") or "",
                "contact": payload.get("contact_number") or payload.get("business_mobile") or payload.get("businessMobile") or "",
                "address": payload.get("home_address") or payload.get("business_address") or payload.get("businessAddress") or "",
            },
            "application": {
                "type": permit_snapshot.get("permitName") or permit_snapshot.get("permit_name") or "",
                "status": application.get("status") or "",
                "progress": application.get("progress") or "",
                "submittedId": (application.get("id") or "")[:8],
                "submittedAt": application.get("submitted_at") or application.get("created_at") or "",
                "payload": payload,
            },
        }

    def get_department_assignments(self, config, application_id=None):
        select = (
            "id,application_id,department_key,evaluation_status,remarks,verification_status,"
            "inspection_date,inspection_time,inspection_remarks,created_at,updated_at,"
            "applications(id,permit_id,applicant_id,status,progress,business_info,permit_snapshot,submitted_at,created_at)"
        )
        filters = {
            "select": select,
            "department_key": f"eq.{config['department_key']}",
            "deleted_at": "is.null",
            "order": "created_at.desc",
        }
        if application_id:
            filters["application_id"] = f"eq.{application_id}"

        merged = []
        seen = set()
        try:
            legacy_rows = self.service_rest_request(
                config,
                "department_application_assignments",
                query=urlencode(filters),
            ) or []
        except HTTPError:
            legacy_rows = []

        for row in legacy_rows:
            app_id = row.get("application_id")
            if app_id:
                seen.add(app_id)
            merged.append(row)

        review_select = (
            "id,application_id,department_id,department_key,status,remarks,assigned_at,started_at,"
            "completed_at,approved_at,rejected_at,created_at,updated_at,"
            "applications(id,permit_id,applicant_id,status,progress,business_info,permit_snapshot,submitted_at,created_at)"
        )
        review_filters = {
            "select": review_select,
            "department_key": f"eq.{config['department_key']}",
            "order": "assigned_at.desc",
        }
        if application_id:
            review_filters["application_id"] = f"eq.{application_id}"

        reviews = self.service_rest_request(
            config,
            "application_department_reviews",
            query=urlencode(review_filters),
        ) or []
        for review in reviews:
            app_id = review.get("application_id")
            if app_id and app_id in seen:
                continue
            merged.append({"__department_review__": True, **review})

        return merged

    def list_department_applications(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            assignments = [
                self.format_department_review_assignment(item) if item.get("__department_review__") else self.format_department_assignment(item)
                for item in self.get_department_assignments(config)
            ]
            counts = {"Pending": 0, "Approved": 0, "Rejected": 0}
            for assignment in assignments:
                status = assignment["status"]
                if status in {"Pending", "Under Review", "For Revision"}:
                    counts["Pending"] += 1
                elif status in counts:
                    counts[status] += 1

            self.send_json(
                {
                    "applications": assignments,
                    "counts": {
                        "pending": counts["Pending"],
                        "approved": counts["Approved"],
                        "rejected": counts["Rejected"],
                        "totalApplicants": len(assignments),
                    },
                    "departmentName": config["department_name"],
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to load department applications.")

    def get_department_application(self, application_id):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            assignments = self.get_department_assignments(config, application_id=application_id)
            if not assignments:
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            assignment = (
                self.format_department_review_assignment(assignments[0])
                if assignments[0].get("__department_review__")
                else self.format_department_assignment(assignments[0])
            )
            query = urlencode(
                {
                    "select": "*",
                    "department_key": f"eq.{config['department_key']}",
                    "application_id": f"eq.{application_id}",
                    "deleted_at": "is.null",
                    "order": "created_at.desc",
                }
            )
            remarks = self.service_rest_request(config, "department_remarks", query=query) or []
            inspections = [
                self.format_department_inspection_record(record)
                for record in (self.service_rest_request(config, "department_inspections", query=query) or [])
            ]
            verifications = self.service_rest_request(config, "department_verifications", query=query) or []
            self.send_json(
                {
                    "application": assignment,
                    "remarks": remarks,
                    "inspections": inspections,
                    "verifications": verifications,
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to load application details.")

    def inspection_metadata_marker(self):
        return "__department_inspection_meta__:"

    def pack_department_inspection_remarks(self, remarks="", end_time="", location_address="", proof_files=None):
        metadata = {
            "remarks": (remarks or "").strip(),
            "endTime": (end_time or "").strip(),
            "locationAddress": (location_address or "").strip(),
            "proofFiles": proof_files or [],
        }
        return f"{self.inspection_metadata_marker()}{json.dumps(metadata, separators=(',', ':'))}"

    def unpack_department_inspection_remarks(self, remarks):
        text = remarks or ""
        marker = self.inspection_metadata_marker()
        if not text.startswith(marker):
            return {
                "remarks": text,
                "endTime": "",
                "locationAddress": "",
                "proofFiles": [],
            }
        try:
            metadata = json.loads(text[len(marker):] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        return {
            "remarks": metadata.get("remarks") or "",
            "endTime": metadata.get("endTime") or "",
            "locationAddress": metadata.get("locationAddress") or "",
            "proofFiles": metadata.get("proofFiles") or [],
        }

    def format_department_inspection_record(self, record):
        if not record:
            return {}
        formatted = dict(record)
        metadata = self.unpack_department_inspection_remarks(record.get("remarks"))
        formatted["remarks"] = metadata["remarks"]
        formatted["end_time"] = metadata["endTime"]
        formatted["location_address"] = metadata["locationAddress"]
        formatted["proof_files"] = metadata["proofFiles"]
        return formatted

    def get_department_workspace_assessment_item(self, config, application_id):
        assessment_rows = self.service_rest_request(
            config,
            "assessments",
            query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "limit": "1"}),
        ) or []
        assessment = assessment_rows[0] if assessment_rows else None
        if not assessment:
            return None, None

        item_rows = self.service_rest_request(
            config,
            "assessment_items",
            query=urlencode(
                {
                    "select": "*",
                    "assessment_id": f"eq.{assessment.get('id')}",
                    "application_id": f"eq.{application_id}",
                    "department_key": f"eq.{config['department_key']}",
                    "is_active": "eq.true",
                    "order": "created_at.asc",
                }
            ),
        ) or []
        return assessment, (item_rows[-1] if item_rows else None), item_rows

    def get_department_workspace_inspection(self, config, application_id):
        rows = self.service_rest_request(
            config,
            "department_inspections",
            query=urlencode(
                {
                    "select": "*",
                    "application_id": f"eq.{application_id}",
                    "department_key": f"eq.{config['department_key']}",
                    "deleted_at": "is.null",
                    "order": "updated_at.desc",
                    "limit": "1",
                }
            ),
        ) or []
        return self.format_department_inspection_record(rows[0]) if rows else None

    def get_department_application_workspace(self, application_id):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            if not self.get_department_assignments(config, application_id=application_id):
                self.send_json({"error": "Application not found for this department."}, status=404)
                return
            assessment, item, items = self.get_department_workspace_assessment_item(config, application_id)
            inspection = self.get_department_workspace_inspection(config, application_id)
            self.send_json({"assessment": assessment, "assessmentItem": item, "assessmentItems": items, "inspection": inspection})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to load saved department form data.")

    def update_department_application_evaluation(self, application_id):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            status = (payload.get("status") or "").strip()
            remarks = (payload.get("remarks") or "").strip()
            verification_status = (payload.get("verificationStatus") or "").strip()

            if status not in {"Pending", "Approved", "Rejected"}:
                self.send_json({"error": "Status must be Pending, Approved, or Rejected."}, status=400)
                return

            if status == "Rejected" and not remarks:
                self.send_json({"error": "Remarks are required when rejecting an application."}, status=400)
                return

            current = self.get_department_assignments(config, application_id=application_id)
            if not current:
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            update_payload = {
                "evaluation_status": status,
                "remarks": remarks,
                "updated_at": utc_now_iso(),
            }
            if verification_status:
                update_payload["verification_status"] = verification_status

            query = urlencode(
                {
                    "application_id": f"eq.{application_id}",
                    "department_key": f"eq.{config['department_key']}",
                    "deleted_at": "is.null",
                }
            )
            updated = self.service_rest_request(
                config,
                "department_application_assignments",
                method="PATCH",
                payload=update_payload,
                query=query,
                prefer="return=representation",
            )
            self.sync_department_review_status(config, application_id, config["department_key"], status, remarks)
            actor = config["actor"]
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "department_application_evaluation_updated",
                actor=actor,
                entity_type="department_application_assignment",
                entity_id=application_id,
                details={"department": config["department_key"], "status": status, "remarks": remarks},
            )
            department_name = config["department_name"]
            if status == "Approved":
                notification_message = f"{department_name} has approved your submitted documents."
            elif status == "Rejected":
                notification_message = f"{department_name} requested a correction. Please review the remarks."
            else:
                notification_message = f"{department_name} updated your application review status to {status}."
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                "Department Review Updated",
                notification_message,
                notification_type="status",
                source_role=department_name,
            )
            self.send_json({"message": "Application evaluation updated.", "assignment": updated[0] if updated else {}})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to update application evaluation.")

    def list_department_requirements(self):
        self.list_department_owned_records("department_requirement_checklists", "requirements")

    def list_department_inspections(self):
        self.list_department_owned_records("department_inspections", "inspections")

    def list_department_reports(self):
        self.list_department_owned_records("department_reports", "reports")

    def list_department_owned_records(self, table, response_key):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            query = urlencode(
                {
                    "select": "*",
                    "department_key": f"eq.{config['department_key']}",
                    "deleted_at": "is.null",
                    "order": "created_at.desc",
                }
            )
            rows = self.service_rest_request(config, table, query=query) or []
            if table == "department_inspections":
                rows = [self.format_department_inspection_record(record) for record in rows]
            self.send_json({response_key: rows, "total": len(rows)})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, f"Unable to load {response_key}.")

    def create_department_requirement(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            title = (payload.get("title") or "").strip()
            description = (payload.get("description") or "").strip()
            status = (payload.get("status") or "Draft").strip()

            if not title:
                self.send_json({"error": "Requirement title is required."}, status=400)
                return

            if status not in {"Draft", "Active"}:
                self.send_json({"error": "Requirement status must be Draft or Active."}, status=400)
                return

            record = {
                "department_key": config["department_key"],
                "title": title,
                "description": description,
                "is_required": bool(payload.get("isRequired", True)),
                "status": status,
                "created_by": config["actor"].get("id"),
            }
            rows = self.service_rest_request(
                config,
                "department_requirement_checklists",
                method="POST",
                payload=record,
                prefer="return=representation",
            )
            created = rows[0] if rows else {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "requirement_created",
                actor=config["actor"],
                entity_type="department_requirement",
                entity_id=created.get("id"),
                details={"department": config["department_key"], "title": title},
            )
            self.send_json({"message": "Requirement created.", "requirement": created}, status=201)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to create requirement.")

    def update_department_requirement(self, record_id):
        payload = self.read_json_body()
        allowed = {
            "title": (payload.get("title") or "").strip(),
            "description": (payload.get("description") or "").strip(),
            "is_required": bool(payload.get("isRequired", True)),
            "status": (payload.get("status") or "Draft").strip(),
        }
        if not allowed["title"]:
            self.send_json({"error": "Requirement title is required."}, status=400)
            return
        if allowed["status"] not in {"Draft", "Active"}:
            self.send_json({"error": "Requirement status must be Draft or Active."}, status=400)
            return
        self.update_department_record(
            "department_requirement_checklists",
            record_id,
            allowed,
            "requirement_updated",
            "department_requirement",
        )

    def upsert_department_assessment(self, application_id):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            application_id = (application_id or payload.get("applicationId") or "").strip()
            if not application_id:
                self.send_json({"error": "Application is required."}, status=400)
                return
            if not self.get_department_assignments(config, application_id=application_id):
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            assessment = self.get_or_create_assessment(config, application_id)
            if not assessment:
                self.send_json({"error": "Unable to prepare assessment record."}, status=500)
                return

            incoming_items = payload.get("items") if isinstance(payload.get("items"), list) else None
            if incoming_items is None:
                incoming_items = [payload]

            cleaned_items = []
            for raw_item in incoming_items:
                if not isinstance(raw_item, dict):
                    continue
                fee_name = (raw_item.get("feeName") or "Department fee").strip()
                category = (raw_item.get("category") or "").strip()
                amount = self.money(self.safe_float(raw_item.get("amount"), 0))
                penalty = self.money(self.safe_float(raw_item.get("penalty"), 0))
                if not fee_name and not category and amount == 0 and penalty == 0:
                    continue
                if not fee_name:
                    self.send_json({"error": "Fee description is required."}, status=400)
                    return
                item_payload = dict(raw_item)
                item_payload["feeName"] = fee_name
                item_payload["assessmentId"] = assessment.get("id")
                item_payload["applicationId"] = application_id
                item_payload["departmentKey"] = config["department_key"]
                item_payload["remarks"] = (raw_item.get("remarks") or payload.get("remarks") or "").strip()
                item_payload["finalAmount"] = self.money(amount + penalty)
                cleaned_items.append(item_payload)

            if not cleaned_items:
                self.send_json({"error": "At least one fee item is required."}, status=400)
                return

            existing_rows = self.service_rest_request(
                config,
                "assessment_items",
                query=urlencode(
                    {
                        "select": "*",
                        "assessment_id": f"eq.{assessment.get('id')}",
                        "application_id": f"eq.{application_id}",
                        "department_key": f"eq.{config['department_key']}",
                        "is_active": "eq.true",
                        "order": "created_at.asc",
                    }
                ),
            ) or []
            existing_by_id = {str(row.get("id")): row for row in existing_rows if row.get("id")}
            saved_items = []
            submitted_ids = set()

            for raw_item in cleaned_items:
                item_id = (raw_item.get("id") or "").strip()
                existing = existing_by_id.get(item_id)
                item = self.build_assessment_item_payload(config, raw_item, existing=existing)
                item["status"] = "Submitted"
                if existing:
                    item.pop("assessment_id", None)
                    item.pop("application_id", None)
                    rows = self.service_rest_request(
                        config,
                        "assessment_items",
                        method="PATCH",
                        payload=item,
                        query=urlencode({"id": f"eq.{existing.get('id')}", "is_active": "eq.true"}),
                        prefer="return=representation",
                    ) or []
                    saved_item = rows[0] if rows else {}
                    submitted_ids.add(str(existing.get("id")))
                    action = "department_fee_updated"
                else:
                    item["created_by"] = config["actor"].get("id")
                    rows = self.service_rest_request(
                        config,
                        "assessment_items",
                        method="POST",
                        payload=item,
                        prefer="return=representation",
                    ) or []
                    saved_item = rows[0] if rows else {}
                    if saved_item.get("id"):
                        submitted_ids.add(str(saved_item.get("id")))
                    action = "department_fee_created"
                if saved_item:
                    saved_items.append(saved_item)
                self.create_service_audit_log(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    action,
                    actor=config["actor"],
                    entity_type="assessment_item",
                    entity_id=saved_item.get("id"),
                    details={"department": config["department_key"], "applicationId": application_id, "feeName": item.get("fee_name")},
                )

            removed_ids = [str(row.get("id")) for row in existing_rows if str(row.get("id")) not in submitted_ids]
            if removed_ids:
                self.service_rest_request(
                    config,
                    "assessment_items",
                    method="PATCH",
                    payload={
                        "is_active": False,
                        "status": "Cancelled",
                        "updated_by": config["actor"].get("id"),
                        "updated_at": utc_now_iso(),
                    },
                    query=urlencode({"id": f"in.({','.join(removed_ids)})"}),
                    prefer="return=minimal",
                )

            updated_assessment = self.recalculate_assessment(config, assessment.get("id"))
            refreshed_items = self.service_rest_request(
                config,
                "assessment_items",
                query=urlencode(
                    {
                        "select": "*",
                        "assessment_id": f"eq.{assessment.get('id')}",
                        "application_id": f"eq.{application_id}",
                        "department_key": f"eq.{config['department_key']}",
                        "is_active": "eq.true",
                        "order": "created_at.asc",
                    }
                ),
            ) or []
            self.send_json(
                {
                    "message": "Department assessment saved.",
                    "item": refreshed_items[-1] if refreshed_items else (saved_items[-1] if saved_items else {}),
                    "items": refreshed_items,
                    "assessment": updated_assessment,
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to save department assessment.")

    def create_department_inspection(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            application_id = (payload.get("applicationId") or "").strip()
            scheduled_date = (payload.get("scheduledDate") or "").strip()
            scheduled_time = (payload.get("scheduledTime") or "").strip()
            remarks = (payload.get("remarks") or "").strip()
            end_time = (payload.get("endTime") or "").strip()
            location_address = (payload.get("locationAddress") or "").strip()
            proof_files = payload.get("proofFiles") if isinstance(payload.get("proofFiles"), list) else []

            if not application_id or not scheduled_date or not scheduled_time:
                self.send_json({"error": "Application, date, and time are required."}, status=400)
                return

            if not self.get_department_assignments(config, application_id=application_id):
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            record = {
                "application_id": application_id,
                "department_key": config["department_key"],
                "scheduled_date": scheduled_date,
                "scheduled_time": scheduled_time,
                "remarks": self.pack_department_inspection_remarks(remarks, end_time, location_address, proof_files),
                "status": (payload.get("status") or "Draft").strip(),
                "created_by": config["actor"].get("id"),
            }
            existing = self.service_rest_request(
                config,
                "department_inspections",
                query=urlencode(
                    {
                        "select": "*",
                        "application_id": f"eq.{application_id}",
                        "department_key": f"eq.{config['department_key']}",
                        "deleted_at": "is.null",
                        "order": "updated_at.desc",
                        "limit": "1",
                    }
                ),
            ) or []
            if existing:
                record.pop("application_id", None)
                record.pop("department_key", None)
                record.pop("created_by", None)
                rows = self.service_rest_request(
                    config,
                    "department_inspections",
                    method="PATCH",
                    payload=record,
                    query=urlencode({"id": f"eq.{existing[0].get('id')}", "department_key": f"eq.{config['department_key']}", "deleted_at": "is.null"}),
                    prefer="return=representation",
                )
                action = "inspection_updated"
                message = "Inspection schedule updated."
            else:
                rows = self.service_rest_request(
                    config,
                    "department_inspections",
                    method="POST",
                    payload=record,
                    prefer="return=representation",
                )
                action = "inspection_created"
                message = "Inspection schedule created."
            created = self.format_department_inspection_record((rows or [{}])[0])
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                action,
                actor=config["actor"],
                entity_type="department_inspection",
                entity_id=created.get("id"),
                details={"department": config["department_key"], "applicationId": application_id},
            )
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                "Inspection Scheduled" if action == "inspection_created" else "Inspection Updated",
                f"{config['department_name']} {'scheduled' if action == 'inspection_created' else 'updated'} your inspection on {scheduled_date} at {scheduled_time}.",
                notification_type="inspection",
                source_role=config["department_name"],
            )
            self.send_json({"message": message, "inspection": created}, status=200 if existing else 201)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to create inspection schedule.")

    def update_department_inspection(self, record_id):
        payload = self.read_json_body()
        record = {
            "scheduled_date": (payload.get("scheduledDate") or "").strip(),
            "scheduled_time": (payload.get("scheduledTime") or "").strip(),
            "remarks": self.pack_department_inspection_remarks(
                (payload.get("remarks") or "").strip(),
                (payload.get("endTime") or "").strip(),
                (payload.get("locationAddress") or "").strip(),
                payload.get("proofFiles") if isinstance(payload.get("proofFiles"), list) else [],
            ),
            "status": (payload.get("status") or "Draft").strip(),
        }
        if not record["scheduled_date"] or not record["scheduled_time"]:
            self.send_json({"error": "Inspection date and time are required."}, status=400)
            return
        self.update_department_record(
            "department_inspections",
            record_id,
            record,
            "inspection_updated",
            "department_inspection",
        )

    def get_bplo_notification_users(self, config):
        queries = [
            {"select": "auth_user_id", "role": "in.(bplo_admin,super_admin)", "status": "eq.active"},
            {"select": "auth_user_id", "role": "in.(bplo_admin,super_admin)", "status": "eq.Active"},
        ]
        users = []
        seen = set()
        for query in queries:
            try:
                rows = self.service_rest_request(config, "profiles", query=urlencode(query)) or []
            except HTTPError:
                rows = []
            for row in rows:
                user_id = row.get("auth_user_id")
                if user_id and user_id not in seen:
                    seen.add(user_id)
                    users.append(user_id)
        return users

    def send_department_inspection_notification(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            application_id = (payload.get("applicationId") or "").strip()
            scheduled_date = (payload.get("scheduledDate") or "").strip()
            scheduled_time = (payload.get("scheduledTime") or "").strip()
            end_time = (payload.get("endTime") or "").strip()
            location_address = (payload.get("locationAddress") or "").strip()
            remarks = (payload.get("remarks") or "").strip()
            status = (payload.get("status") or "Scheduled").strip()

            if not application_id or not scheduled_date or not scheduled_time:
                self.send_json({"error": "Application, inspection date, and start time are required."}, status=400)
                return

            assignments = self.get_department_assignments(config, application_id=application_id)
            if not assignments:
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            application = self.load_application_core(config["supabase_url"], config["supabase_service_key"], application_id) or {}
            business_info = application.get("business_info") or {}
            business_name = self.app_business_name(business_info)
            applicant_name = self.app_owner_name(business_info)
            time_range = f"{scheduled_time} to {end_time}" if end_time else scheduled_time
            location_copy = f" at {location_address}" if location_address else ""
            remarks_copy = f" Remarks: {remarks}" if remarks else ""
            reference = (application_id or "")[:8]

            applicant_user_id = application.get("applicant_id")
            admin_user_ids = self.get_bplo_notification_users(config)
            notification_payloads = []
            if applicant_user_id:
                notification_payloads.append(
                    {
                        "user_id": applicant_user_id,
                        "application_id": application_id,
                        "title": "Inspection Schedule Notification",
                        "message": f"{config['department_name']} set your inspection for {scheduled_date} at {time_range}{location_copy}.{remarks_copy}",
                        "type": "inspection",
                        "source_role": config["department_name"],
                    }
                )
            notification_payloads.extend(
                {
                    "user_id": user_id,
                    "application_id": application_id,
                    "title": "Department Inspection Update",
                    "message": f"{config['department_name']} notified {applicant_name or 'the applicant'} about the {status.lower()} inspection for {business_name} ({reference}) on {scheduled_date} at {time_range}.",
                    "type": "inspection",
                    "source_role": config["department_name"],
                }
                for user_id in admin_user_ids
            )

            created_notifications = self.create_notifications(
                config["supabase_url"],
                config["supabase_service_key"],
                notification_payloads,
            )
            created_user_ids = {row.get("user_id") for row in created_notifications}
            applicant_notified = bool(applicant_user_id and applicant_user_id in created_user_ids)
            admin_sent = sum(1 for user_id in admin_user_ids if user_id in created_user_ids)

            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "inspection_notification_sent",
                actor=config["actor"],
                entity_type="application",
                entity_id=application_id,
                details={"department": config["department_key"], "applicantNotified": applicant_notified, "adminNotifications": admin_sent},
            )
            self.send_json(
                {
                    "message": "Inspection notification sent to the applicant and BPLO staff.",
                    "applicantNotified": applicant_notified,
                    "adminNotifications": admin_sent,
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to send inspection notification.")

    def create_department_remark(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            application_id = (payload.get("applicationId") or "").strip()
            remark = (payload.get("remark") or "").strip()

            if not application_id or not remark:
                self.send_json({"error": "Application and remark are required."}, status=400)
                return

            if not self.get_department_assignments(config, application_id=application_id):
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            record = {
                "application_id": application_id,
                "department_key": config["department_key"],
                "remark": remark,
                "status": (payload.get("status") or "Draft").strip(),
                "created_by": config["actor"].get("id"),
            }
            rows = self.service_rest_request(
                config,
                "department_remarks",
                method="POST",
                payload=record,
                prefer="return=representation",
            )
            created = rows[0] if rows else {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "remark_created",
                actor=config["actor"],
                entity_type="department_remark",
                entity_id=created.get("id"),
                details={"department": config["department_key"], "applicationId": application_id},
            )
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                "Office Remark Added",
                f"{config['department_name']} added a remark to your application.",
                notification_type="status",
                source_role=config["department_name"],
            )
            self.send_json({"message": "Remark created.", "remark": created}, status=201)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to create remark.")

    def create_department_verification(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            application_id = (payload.get("applicationId") or "").strip()
            requirement_id = (payload.get("requirementId") or "").strip() or None
            status = (payload.get("status") or "").strip()
            remarks = (payload.get("remarks") or "").strip()

            if not application_id or status not in {"Pending", "Verified", "Rejected"}:
                self.send_json({"error": "Application and a valid verification status are required."}, status=400)
                return

            if not self.get_department_assignments(config, application_id=application_id):
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            record = {
                "application_id": application_id,
                "department_key": config["department_key"],
                "requirement_id": requirement_id,
                "verification_status": status,
                "remarks": remarks,
                "created_by": config["actor"].get("id"),
            }
            rows = self.service_rest_request(
                config,
                "department_verifications",
                method="POST",
                payload=record,
                prefer="return=representation",
            )
            created = rows[0] if rows else {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "verification_created",
                actor=config["actor"],
                entity_type="department_verification",
                entity_id=created.get("id"),
                details={"department": config["department_key"], "applicationId": application_id, "status": status},
            )
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                "Document Verification Updated",
                f"{config['department_name']} marked a requirement as {status}.",
                notification_type="document",
                source_role=config["department_name"],
            )
            self.send_json({"message": "Verification record created.", "verification": created}, status=201)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to create verification record.")

    def update_department_verification(self, record_id):
        payload = self.read_json_body()
        status = (payload.get("status") or "").strip()
        if status not in {"Pending", "Verified", "Rejected"}:
            self.send_json({"error": "Verification status must be Pending, Verified, or Rejected."}, status=400)
            return
        self.update_department_record(
            "department_verifications",
            record_id,
            {"verification_status": status, "remarks": (payload.get("remarks") or "").strip()},
            "verification_updated",
            "department_verification",
        )

    def validate_department_report_payload(self, payload):
        report = {
            "applicant_name": (payload.get("applicantName") or "").strip(),
            "business_name": (payload.get("businessName") or "").strip(),
            "report_type": (payload.get("reportType") or "").strip(),
            "report_date": (payload.get("reportDate") or "").strip(),
            "status": (payload.get("status") or "Pending").strip(),
            "remarks": (payload.get("remarks") or "").strip(),
        }
        if not report["applicant_name"] or not report["business_name"] or not report["report_type"]:
            raise ValueError("Applicant, business name, and report type are required.")
        if not report["report_date"]:
            raise ValueError("Report date is required.")
        if report["status"] not in {"Completed", "Approved", "Pending", "For Revision", "Draft"}:
            raise ValueError("Report status is invalid.")
        return report

    def create_department_report(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            report = self.validate_department_report_payload(self.read_json_body())
            report["department_key"] = config["department_key"]
            report["created_by"] = config["actor"].get("id")
            rows = self.service_rest_request(
                config,
                "department_reports",
                method="POST",
                payload=report,
                prefer="return=representation",
            )
            created = rows[0] if rows else {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "report_created",
                actor=config["actor"],
                entity_type="department_report",
                entity_id=created.get("id"),
                details={"department": config["department_key"], "reportType": report["report_type"]},
            )
            self.send_json({"message": "Report created.", "report": created}, status=201)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to create report.")

    def update_department_report(self, record_id):
        try:
            report = self.validate_department_report_payload(self.read_json_body())
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
            return

        self.update_department_record(
            "department_reports",
            record_id,
            report,
            "report_updated",
            "department_report",
        )

    def default_department_settings(self, config):
        actor = config["actor"]
        metadata = actor.get("user_metadata") or {}
        full_name = " ".join(
            part for part in [metadata.get("first_name"), metadata.get("last_name")] if part
        ).strip() or actor.get("email") or "Department staff"
        return {
            "profile_settings": {
                "staffName": full_name,
                "emailAddress": actor.get("email") or "",
                "contactNumber": "",
                "positionRole": "Department Staff",
                "departmentOffice": config["department_name"],
            },
            "office_information": {
                "officeName": config["department_name"],
                "officeEmail": actor.get("email") or "",
                "officeHead": "",
                "officeAddress": "",
                "officeContactNumber": "",
            },
            "notification_settings": {
                "newApplicationAssigned": True,
                "newDocumentUploaded": True,
                "inspectionScheduleReminder": True,
                "applicantResubmission": True,
                "bploAdminUpdates": True,
                "emailNotifications": True,
                "systemNotifications": True,
            },
            "inspection_settings": {
                "defaultInspectionDuration": "60 minutes",
                "maximumInspectionsPerDay": "8",
                "availableInspectionDays": "Monday to Friday",
                "defaultAssignedInspector": full_name,
                "availableInspectionTime": "8:00 AM - 5:00 PM",
            },
            "report_settings": {
                "defaultReportFormat": "PDF",
                "includeOfficeLogo": True,
                "includeInspectorSignature": True,
                "reportHeaderText": f"{config['department_name']} Site Inspection Report",
                "reportFooterText": "This is a system generated report. Thank you.",
            },
            "security_settings": {
                "twoStepVerification": False,
                "lastLogin": "",
                "accountActivity": "No recent activity.",
            },
        }

    def normalize_department_settings_payload(self, payload, config):
        defaults = self.default_department_settings(config)
        normalized = {}
        for key, default_value in defaults.items():
            value = payload.get(key)
            if value is None:
                value = payload.get("settings", {}).get(key) if isinstance(payload.get("settings"), dict) else None
            if not isinstance(value, dict):
                value = {}
            merged = dict(default_value)
            merged.update(value)
            normalized[key] = merged
        return normalized

    def get_department_settings(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            query = urlencode(
                {
                    "select": "*",
                    "department_key": f"eq.{config['department_key']}",
                    "deleted_at": "is.null",
                    "limit": "1",
                }
            )
            rows = self.service_rest_request(config, "department_settings", query=query) or []
            settings = rows[0] if rows else {
                "id": None,
                "department_key": config["department_key"],
                **self.default_department_settings(config),
            }
            self.send_json({"settings": settings})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to load settings.")

    def upsert_department_settings(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            settings_payload = self.normalize_department_settings_payload(payload, config)
            settings_payload["department_key"] = config["department_key"]
            settings_payload["created_by"] = config["actor"].get("id")
            settings_payload["deleted_at"] = None

            query = urlencode({"on_conflict": "department_key"})
            rows = self.service_rest_request(
                config,
                "department_settings",
                method="POST",
                payload=settings_payload,
                query=query,
                prefer="resolution=merge-duplicates,return=representation",
            )
            saved = rows[0] if rows else {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "settings_saved",
                actor=config["actor"],
                entity_type="department_settings",
                entity_id=saved.get("id"),
                details={"department": config["department_key"]},
            )
            self.send_json({"message": "Settings saved.", "settings": saved})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to save settings.")

    def delete_department_settings(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            query = urlencode(
                {
                    "department_key": f"eq.{config['department_key']}",
                    "deleted_at": "is.null",
                }
            )
            rows = self.service_rest_request(
                config,
                "department_settings",
                method="PATCH",
                payload={"deleted_at": utc_now_iso(), "updated_at": utc_now_iso()},
                query=query,
                prefer="return=representation",
            )
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "settings_deleted",
                actor=config["actor"],
                entity_type="department_settings",
                entity_id=(rows[0] or {}).get("id") if rows else None,
                details={"department": config["department_key"], "softDelete": True},
            )
            self.send_json({"message": "Settings reset.", "settings": rows[0] if rows else {}})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to reset settings.")

    def update_department_record(self, table, record_id, payload, action, entity_type):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload["updated_at"] = utc_now_iso()
            query = urlencode(
                {
                    "id": f"eq.{record_id}",
                    "department_key": f"eq.{config['department_key']}",
                    "deleted_at": "is.null",
                }
            )
            rows = self.service_rest_request(
                config,
                table,
                method="PATCH",
                payload=payload,
                query=query,
                prefer="return=representation",
            )
            if not rows:
                self.send_json({"error": "Record not found for this department."}, status=404)
                return
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                action,
                actor=config["actor"],
                entity_type=entity_type,
                entity_id=record_id,
                details={"department": config["department_key"]},
            )
            updated_record = rows[0]
            application_id = updated_record.get("application_id")
            if table == "department_inspections" and application_id:
                self.notify_application_owner(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    application_id,
                    "Inspection Updated",
                    f"{config['department_name']} updated your inspection schedule.",
                    notification_type="inspection",
                    source_role=config["department_name"],
                )
            elif table == "department_verifications" and application_id:
                verification_status = updated_record.get("verification_status") or "updated"
                self.notify_application_owner(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    application_id,
                    "Document Verification Updated",
                    f"{config['department_name']} marked a requirement as {verification_status}.",
                    notification_type="document",
                    source_role=config["department_name"],
                )
            self.send_json({"message": "Record updated.", "record": rows[0]})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to update record.")

    def soft_delete_department_record(self, table, record_id, action):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            query = urlencode(
                {
                    "id": f"eq.{record_id}",
                    "department_key": f"eq.{config['department_key']}",
                    "status": "eq.Draft",
                    "deleted_at": "is.null",
                }
            )
            rows = self.service_rest_request(
                config,
                table,
                method="PATCH",
                payload={"deleted_at": utc_now_iso(), "updated_at": utc_now_iso()},
                query=query,
                prefer="return=representation",
            )
            if not rows:
                self.send_json({"error": "Only draft department-created records can be deleted."}, status=404)
                return

            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                action,
                actor=config["actor"],
                entity_type=table,
                entity_id=record_id,
                details={"department": config["department_key"], "softDelete": True},
            )
            self.send_json({"message": "Draft record deleted.", "record": rows[0]})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to delete draft record.")

    def ensure_treasury_request(self):
        supabase_url, supabase_client_key, supabase_service_key, _admin_email = self.get_admin_api_config()
        if not supabase_url or not supabase_client_key or not supabase_service_key:
            self.send_json({"error": "Treasury access is not configured."}, status=500)
            return None

        auth_header = self.headers.get("Authorization", "")
        access_token = auth_header.removeprefix("Bearer ").strip()
        if not access_token:
            self.send_json({"error": "Please log in as a treasury user."}, status=401)
            return None

        try:
            actor = self.get_session_user(access_token, supabase_url, supabase_client_key)
        except HTTPError:
            self.send_json({"error": "Invalid or expired session."}, status=401)
            return None

        profile = self.get_profile_by_auth_user_id(supabase_url, supabase_service_key, actor.get("id"))
        if not profile:
            self.send_json({"error": "No centralized user profile was found for this account."}, status=403)
            return None

        role = normalize_role(profile.get("role"))
        status = profile_status(profile.get("status"))
        if status != "active":
            self.send_json({"error": f"This account is {status} and cannot access the dashboard."}, status=403)
            return None

        if role != "treasury":
            self.send_json({"error": "This page is only for Treasury accounts."}, status=403)
            return None

        return {
            "supabase_url": supabase_url,
            "supabase_service_key": supabase_service_key,
            "actor": actor,
            "profile": profile,
        }

    def treasury_error(self, error, fallback):
        if isinstance(error, HTTPError):
            response_body = error.read().decode("utf-8")
            try:
                response_payload = json.loads(response_body)
                message = response_payload.get("message") or response_payload.get("msg") or response_body
            except json.JSONDecodeError:
                message = response_body or fallback
            self.send_json({"error": message}, status=error.code)
            return
        self.send_json({"error": str(error) or fallback}, status=500)

    def get_treasury_profile(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        actor = config["actor"]
        profile = self.format_profile(config["profile"])
        self.send_json({"user": {"id": actor.get("id"), "email": actor.get("email"), "name": profile["name"] or "Treasury Staff", "role": profile["role"]}})

    def format_treasury_record(self, record):
        return {
            "id": record.get("id"),
            "applicationNo": record.get("application_no") or "",
            "orNo": record.get("or_no") or "",
            "applicant": record.get("applicant") or "",
            "businessName": record.get("business_name") or "",
            "amount": float(record.get("amount") or 0),
            "step": record.get("step") or "Assessment",
            "status": record.get("status") or "Pending",
            "currentStep": record.get("current_step") or record.get("step") or "Assessment",
            "recordType": record.get("record_type") or "payment",
            "transactionDate": record.get("transaction_date") or "",
            "remarks": record.get("remarks") or "",
            "createdAt": record.get("created_at") or "",
        }

    def list_treasury_records(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            query = urlencode({"select": "*", "deleted_at": "is.null", "order": "created_at.desc", "limit": "500"})
            rows = self.service_rest_request(config, "treasury_records", query=query) or []
            records = [self.format_treasury_record(row) for row in rows]
            total_collections = sum(record["amount"] for record in records if record["status"] == "Paid")
            counts = {
                "totalCollections": total_collections,
                "assessmentReview": sum(1 for record in records if record["step"] == "Assessment"),
                "readyForPayment": sum(1 for record in records if record["status"] in {"Ready", "Pending"}),
                "receiptsIssued": sum(1 for record in records if record["status"] == "Paid" or record["currentStep"] == "Official Receipt"),
            }
            self.send_json({"records": records, "counts": counts})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to load treasury records.")

    def validate_treasury_payload(self, payload):
        record = {
            "application_no": (payload.get("applicationNo") or "").strip(),
            "or_no": (payload.get("orNo") or "").strip(),
            "applicant": (payload.get("applicant") or "").strip(),
            "business_name": (payload.get("businessName") or "").strip(),
            "amount": payload.get("amount") or 0,
            "step": (payload.get("step") or "Assessment").strip(),
            "status": (payload.get("status") or "Pending").strip(),
            "current_step": (payload.get("currentStep") or payload.get("step") or "Assessment").strip(),
            "record_type": (payload.get("recordType") or "payment").strip(),
            "transaction_date": (payload.get("transactionDate") or "").strip(),
            "remarks": (payload.get("remarks") or "").strip(),
        }
        if not record["application_no"] or not record["applicant"] or not record["business_name"]:
            raise ValueError("Application number, applicant, and business name are required.")
        if record["status"] not in {"Paid", "Pending", "Ready", "Generated", "Not Generated", "Accepted"}:
            raise ValueError("Treasury status is invalid.")
        if not record["transaction_date"]:
            record["transaction_date"] = datetime.now(timezone.utc).date().isoformat()
        return record

    def create_treasury_record(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            record = self.validate_treasury_payload(self.read_json_body())
            record["created_by"] = config["actor"].get("id")
            rows = self.service_rest_request(config, "treasury_records", method="POST", payload=record, prefer="return=representation")
            created = rows[0] if rows else {}
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "treasury_record_created", actor=config["actor"], entity_type="treasury_record", entity_id=created.get("id"), details={"applicationNo": record["application_no"]})
            application = self.find_application_by_reference(config["supabase_url"], config["supabase_service_key"], record["application_no"])
            if application:
                self.create_notification(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    application.get("applicant_id"),
                    "Treasury Update",
                    f"Your treasury record is now {record['status']} for {record['current_step']}.",
                    notification_type="payment",
                    source_role="Treasury",
                    application_id=application.get("id"),
                )
            self.send_json({"message": "Treasury record created.", "record": self.format_treasury_record(created)}, status=201)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to create treasury record.")

    def update_treasury_record(self, record_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            payload = self.validate_treasury_payload(self.read_json_body())
            payload["updated_at"] = utc_now_iso()
            query = urlencode({"id": f"eq.{record_id}", "deleted_at": "is.null"})
            rows = self.service_rest_request(config, "treasury_records", method="PATCH", payload=payload, query=query, prefer="return=representation")
            if not rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "treasury_record_updated", actor=config["actor"], entity_type="treasury_record", entity_id=record_id, details={"applicationNo": payload["application_no"]})
            application = self.find_application_by_reference(config["supabase_url"], config["supabase_service_key"], payload["application_no"])
            if application:
                status = payload["status"]
                if status == "Paid":
                    title = "Payment Verified"
                    message = "Your payment has been verified by Treasury."
                elif payload["current_step"] == "SOA Generation":
                    title = "Statement of Account Available"
                    message = "Your Statement of Account is now available."
                elif payload["current_step"] == "Official Receipt":
                    title = "Official Receipt Updated"
                    message = "Your Official Receipt has been generated or updated."
                else:
                    title = "Treasury Update"
                    message = f"Your treasury record is now {status} for {payload['current_step']}."
                self.create_notification(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    application.get("applicant_id"),
                    title,
                    message,
                    notification_type="payment",
                    source_role="Treasury",
                    application_id=application.get("id"),
                )
            self.send_json({"message": "Treasury record updated.", "record": self.format_treasury_record(rows[0])})
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to update treasury record.")

    def ensure_treasury_completion_state(self, config, record):
        application_reference = (record.get("application_no") or "").strip()
        application = self.find_application_by_reference(
            config["supabase_url"],
            config["supabase_service_key"],
            application_reference,
        ) if application_reference else None
        application_id = application.get("id") if application else None
        or_number = (record.get("or_no") or "").strip() or "Pending Official Receipt"
        business_name = (record.get("business_name") or "").strip() or "this application"
        now = utc_now_iso()

        payment = None
        receipt = None
        queue = None
        assessment_id = None
        amount_due = self.money(record.get("amount"))

        if application_id:
            queue_rows = self.service_rest_request(
                config,
                "treasury_payment_queue",
                query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "order": "created_at.desc", "limit": 1}),
            ) or []
            queue = queue_rows[0] if queue_rows else None
            assessment_id = queue.get("assessment_id") if queue else None
            if not assessment_id:
                assessment_rows = self.service_rest_request(
                    config,
                    "assessments",
                    query=urlencode({"select": "id", "application_id": f"eq.{application_id}", "order": "created_at.desc", "limit": 1}),
                ) or []
                assessment_id = (assessment_rows[0] or {}).get("id") if assessment_rows else None

            payment_rows = self.service_rest_request(
                config,
                "payments",
                query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "order": "created_at.desc", "limit": 5}),
            ) or []
            payment = next((row for row in payment_rows if row.get("payment_status") == "Confirmed"), None)
            if not payment:
                payment_payload = {
                    "application_id": application_id,
                    "assessment_id": assessment_id,
                    "queue_id": queue.get("id") if queue else None,
                    "payment_reference": self.generate_workflow_number("PAY"),
                    "amount_due": amount_due,
                    "amount_paid": amount_due,
                    "change_amount": 0,
                    "payment_method": "Cash",
                    "payment_status": "Confirmed",
                    "official_receipt_number": or_number,
                    "paid_at": now,
                    "cashier_id": config["actor"].get("id"),
                    "remarks": (record.get("remarks") or "Treasury workflow completed.").strip(),
                }
                created_payments = self.service_rest_request(
                    config,
                    "payments",
                    method="POST",
                    payload=payment_payload,
                    prefer="return=representation",
                ) or []
                payment = created_payments[0] if created_payments else payment_payload

            receipt_rows = self.service_rest_request(
                config,
                "official_receipts",
                query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "receipt_number": f"eq.{or_number}", "limit": 1}),
            ) or []
            receipt = receipt_rows[0] if receipt_rows else None
            if not receipt:
                created_receipts = self.service_rest_request(
                    config,
                    "official_receipts",
                    method="POST",
                    payload={
                        "payment_id": payment.get("id"),
                        "application_id": application_id,
                        "receipt_number": or_number,
                        "issued_by": config["actor"].get("id"),
                        "issued_at": now,
                        "status": "Issued",
                    },
                    prefer="return=representation",
                ) or []
                receipt = created_receipts[0] if created_receipts else {}

            if queue and queue.get("status") != "Paid":
                self.service_rest_request(
                    config,
                    "treasury_payment_queue",
                    method="PATCH",
                    payload={"status": "Paid", "completed_at": now, "assigned_cashier_id": config["actor"].get("id"), "updated_at": now},
                    query=urlencode({"id": f"eq.{queue.get('id')}"}),
                )

            if assessment_id:
                self.service_rest_request(
                    config,
                    "assessments",
                    method="PATCH",
                    payload={"status": "Paid", "updated_at": now},
                    query=urlencode({"id": f"eq.{assessment_id}"}),
                )

            self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={
                    "status": "Payment Verified",
                    "progress": "Ready for Finalization",
                    "payment_status": "Payment Verified",
                    "assessment_status": "Paid",
                    "updated_at": now,
                },
                query=urlencode({"id": f"eq.{application_id}"}),
            )

        return {
            "application": application,
            "applicationId": application_id,
            "applicationReference": application_reference,
            "businessName": business_name,
            "orNumber": or_number,
            "payment": payment,
            "receipt": receipt,
        }

    def sync_treasury_record_completion(self, record_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            rows = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "*", "id": f"eq.{record_id}", "deleted_at": "is.null", "limit": 1}),
            ) or []
            if not rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return

            state = self.ensure_treasury_completion_state(config, rows[0])
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "treasury_completion_synced",
                actor=config["actor"],
                entity_type="treasury_record",
                entity_id=record_id,
                details={
                    "applicationNo": state["applicationReference"],
                    "applicationStatusUpdated": bool(state["applicationId"]),
                    "officialReceiptNumber": state["orNumber"],
                },
            )
            self.send_json(
                {
                    "message": "Treasury workflow synced to the application record.",
                    "applicationStatusUpdated": bool(state["applicationId"]),
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to sync treasury completion.")

    def notify_treasury_print_complete(self, record_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            rows = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "*", "id": f"eq.{record_id}", "deleted_at": "is.null", "limit": 1}),
            ) or []
            if not rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return

            record = rows[0]
            state = self.ensure_treasury_completion_state(config, record)
            application_id = state["applicationId"]
            application_reference = state["applicationReference"]
            business_name = state["businessName"]
            or_number = state["orNumber"]
            payment = state["payment"]
            receipt = state["receipt"]

            applicant_sent = False
            if application_id:
                applicant_notification = self.notify_application_owner(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    application_id,
                    "Payment Completed",
                    f"Your payment for {business_name} has been completed and your official receipt {or_number} is ready.",
                    notification_type="payment",
                    source_role="Treasury",
                )
                applicant_sent = bool(applicant_notification)

            admin_user_ids = self.get_bplo_notification_users(config)
            admin_notifications = []
            for user_id in admin_user_ids:
                admin_notifications.append(
                    {
                        "user_id": user_id,
                        "application_id": application_id,
                        "title": "Payment Completed",
                        "message": f"Payment has been completed for {business_name}. Official Receipt {or_number} is ready for final processing.",
                        "type": "payment",
                        "source_role": "Treasury",
                    }
                )
            admin_sent = self.create_notifications(
                config["supabase_url"],
                config["supabase_service_key"],
                admin_notifications,
            ) if admin_notifications else 0

            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "treasury_print_notification_sent",
                actor=config["actor"],
                entity_type="treasury_record",
                entity_id=record_id,
                details={
                    "applicationNo": application_reference,
                    "officialReceiptNumber": or_number,
                    "applicantNotified": applicant_sent,
                    "adminNotifications": admin_sent,
                    "applicationStatusUpdated": bool(application_id),
                    "paymentId": payment.get("id") if payment else None,
                    "receiptId": receipt.get("id") if receipt else None,
                },
            )
            self.send_json(
                {
                    "message": "Payment completion notifications sent and application is ready for finalization.",
                    "applicantNotified": applicant_sent,
                    "adminNotifications": admin_sent,
                    "applicationStatusUpdated": bool(application_id),
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to send payment completion notifications.")

    def soft_delete_treasury_record(self, record_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            query = urlencode({"id": f"eq.{record_id}", "deleted_at": "is.null"})
            rows = self.service_rest_request(config, "treasury_records", method="PATCH", payload={"deleted_at": utc_now_iso(), "updated_at": utc_now_iso()}, query=query, prefer="return=representation")
            if not rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "treasury_record_deleted", actor=config["actor"], entity_type="treasury_record", entity_id=record_id, details={"softDelete": True})
            self.send_json({"message": "Treasury record deleted.", "record": self.format_treasury_record(rows[0])})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to delete treasury record.")


def main():
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"BPLO app running at http://{HOST}:{PORT}")
    print("Static assets, CSS, and JS are all served from the same port.")
    print("Press Ctrl+C to stop the server.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
