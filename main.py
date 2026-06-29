from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import os
import re
import tempfile

import fitz
import pytesseract
from PIL import Image


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
        "bplo_admin": "/admin/dashboard",
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

        if request_path == "/api/me/profile":
            self.get_current_user_profile()
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

        if request_path == "/admin/api/users":
            self.create_admin_user()
            return

        if request_path == "/admin/api/departments":
            self.create_admin_department()
            return

        if request_path == "/admin/api/permits":
            self.create_admin_permit()
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

    def extract_text_from_file(self, file_name, file_bytes):
        file_name_lower = (file_name or "").lower()

        if file_name_lower.endswith(".pdf"):
            document = fitz.open(stream=file_bytes, filetype="pdf")
            extracted_pages = []

            for page in document:
                pix = page.get_pixmap(dpi=200)
                image_bytes = pix.tobytes("png")
                image = Image.open(BytesIO(image_bytes))
                text = pytesseract.image_to_string(image)
                extracted_pages.append(text)

            return "\n".join(extracted_pages)

        image = Image.open(BytesIO(file_bytes))
        return pytesseract.image_to_string(image)

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

    def find_first_match(self, patterns, text):
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip(" :,-")
        return ""

    def clean_extracted_ocr_value(self, value):
        value = re.sub(r"[:|_]+", " ", str(value or ""))
        value = re.sub(r"\s+", " ", value)
        return value.strip(" :-")

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

        return value.upper()

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
        normalized = {}

        for key, value in (fields or {}).items():
            if value in (None, ""):
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
            "business_address": ["business_address", "businessAddress"],
            "goods_value": ["goods_value", "gross_sales", "grossSales"],
            "date_issued": ["date_issued", "dateIssued"],
            "owner_name": ["owner_name", "ownerName"],
        }
        confidence_map = fields.get("field_confidence") or fields.get("fieldConfidence") or {}
        for confidence_key in confidence_aliases.get(key, [key]):
            if confidence_key in confidence_map:
                value = confidence_map.get(confidence_key)
                if isinstance(value, (int, float)):
                    return float(value)
                level = str(value or "").lower()
                if level == "high":
                    return 95
                if level == "medium":
                    return 80
                if level == "low":
                    return 0

        direct_value = fields.get(f"{key}_confidence")
        if isinstance(direct_value, (int, float)):
            return float(direct_value)
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
        metadata_keys = {"field_confidence", "fieldConfidence", "confidence", "confidence_score"}

        for key, value in incoming.items():
            if key in metadata_keys or key.endswith("_confidence") or value in (None, ""):
                continue

            if key == "business_name":
                owner_name = incoming.get("owner_name") or merged_fields.get("owner_name")
                if owner_name and self.normalize_business_name(value) == self.normalize_business_name(owner_name):
                    continue
                if not self.is_valid_gross_sales_business_name(value):
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

        is_gross_sales_certificate = (
            "gross" in document_type_lower
            or "sales" in document_type_lower
            or "certification" in document_type_lower
            or "name of business" in flattened_text.lower()
            or "total sales" in flattened_text.lower()
        )
        if is_gross_sales_certificate:
            return self.normalize_extracted_business_fields(self.parse_gross_sales_certificate_fields(raw_text))

        if "dti" in document_type_lower or "business name" in flattened_text.lower():
            return self.normalize_extracted_business_fields(self.parse_dti_fields(raw_text))

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

        return self.normalize_extracted_business_fields(extracted)

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

            ocr_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_ocr_results",
                method="POST",
                payload={
                    "application_id": application_id,
                    "application_document_id": application_document_id,
                    "permit_document_id": permit_document_id,
                    "file_name": file_name,
                    "file_url": file_url,
                    "document_type": document_type,
                    "raw_text": raw_text,
                    "extracted_fields": extracted_fields,
                    "confidence_score": confidence_score,
                    "ocr_status": "Completed",
                },
                prefer="return=representation",
            )
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

        return self.service_rest_request(
            config,
            "department_application_assignments",
            query=urlencode(filters),
        ) or []

    def list_department_applications(self):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            assignments = [self.format_department_assignment(item) for item in self.get_department_assignments(config)]
            counts = {"Pending": 0, "Approved": 0, "Rejected": 0}
            for assignment in assignments:
                status = assignment["status"]
                if status in counts:
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

            assignment = self.format_department_assignment(assignments[0])
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
            inspections = self.service_rest_request(config, "department_inspections", query=query) or []
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
                "remarks": remarks,
                "status": (payload.get("status") or "Draft").strip(),
                "created_by": config["actor"].get("id"),
            }
            rows = self.service_rest_request(
                config,
                "department_inspections",
                method="POST",
                payload=record,
                prefer="return=representation",
            )
            created = rows[0] if rows else {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "inspection_created",
                actor=config["actor"],
                entity_type="department_inspection",
                entity_id=created.get("id"),
                details={"department": config["department_key"], "applicationId": application_id},
            )
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                "Inspection Scheduled",
                f"{config['department_name']} scheduled your inspection on {scheduled_date} at {scheduled_time}.",
                notification_type="inspection",
                source_role=config["department_name"],
            )
            self.send_json({"message": "Inspection schedule created.", "inspection": created}, status=201)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to create inspection schedule.")

    def update_department_inspection(self, record_id):
        payload = self.read_json_body()
        record = {
            "scheduled_date": (payload.get("scheduledDate") or "").strip(),
            "scheduled_time": (payload.get("scheduledTime") or "").strip(),
            "remarks": (payload.get("remarks") or "").strip(),
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
