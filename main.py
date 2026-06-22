from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import os


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ENV_FILE = BASE_DIR / ".env"


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

        if request_path == "/admin/api/users":
            self.list_admin_users()
            return

        if request_path == "/admin/api/departments":
            self.list_admin_departments()
            return

        if request_path == "/admin/api/audit-logs":
            self.list_admin_audit_logs()
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

        if request_path.startswith("/admin/api/departments/"):
            department_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_department(department_id)
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

        if request_path.startswith("/admin/api/departments/"):
            department_id = request_path.rsplit("/", 1)[-1]
            self.delete_admin_department(department_id)
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

    def verify_admin_session(self, access_token, supabase_url, supabase_client_key, admin_email):
        if not access_token:
            return False

        user = self.get_session_user(access_token, supabase_url, supabase_client_key)
        return (user.get("email") or "").lower() == admin_email.lower()

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
                access_token, supabase_url, supabase_client_key, admin_email
            ):
                self.send_json({"error": "Only the configured admin can create users."}, status=403)
                return
            actor = self.get_session_user(access_token, supabase_url, supabase_client_key)

            payload = self.read_json_body()
            email = (payload.get("email") or "").strip()
            password = payload.get("password") or ""
            role = (payload.get("role") or "").strip()

            if not email or not password or not role:
                self.send_json({"error": "Email, password, and role are required."}, status=400)
                return

            user_metadata = {
                "first_name": (payload.get("firstName") or "").strip(),
                "last_name": (payload.get("lastName") or "").strip(),
                "middle_name": (payload.get("middleName") or "").strip(),
                "suffix": (payload.get("suffix") or "").strip(),
                "contact_number": (payload.get("contactNumber") or "").strip(),
            }
            create_payload = {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": user_metadata,
                "app_metadata": {"role": role},
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

            audit_logged = self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "user_created_by_admin",
                actor=actor,
                entity_type="user",
                entity_id=response_payload.get("id"),
                details={"email": response_payload.get("email"), "role": role},
            )

            self.send_json(
                {
                    "message": "User account created successfully.",
                    "userId": response_payload.get("id"),
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
            access_token, supabase_url, supabase_client_key, admin_email
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
        role = app_metadata.get("role") or user_metadata.get("role") or "client"
        department = app_metadata.get("department") or user_metadata.get("department") or "-"
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

        app_metadata = actor.get("app_metadata") or {}
        role = app_metadata.get("role")
        department_key = app_metadata.get("department_key")
        department_name = app_metadata.get("department_name") or app_metadata.get("department")

        if role != "department" or not department_key:
            self.send_json({"error": "This page is only for department office accounts."}, status=403)
            return None

        return {
            "supabase_url": supabase_url,
            "supabase_service_key": supabase_service_key,
            "actor": actor,
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
        metadata = actor.get("user_metadata") or {}
        first_name = metadata.get("first_name") or ""
        last_name = metadata.get("last_name") or ""
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        self.send_json(
            {
                "user": {
                    "id": actor.get("id"),
                    "email": actor.get("email"),
                    "name": full_name or actor.get("email") or "Department user",
                    "role": "department",
                    "departmentKey": config["department_key"],
                    "departmentName": config["department_name"],
                }
            }
        )

    def format_department_assignment(self, assignment):
        application = assignment.get("business_permit_applications") or {}
        payload = application.get("application_payload") or {}
        return {
            "assignmentId": assignment.get("id"),
            "applicationId": assignment.get("application_id"),
            "referenceNumber": application.get("permit_id") or "-",
            "businessName": application.get("business_name") or "-",
            "status": assignment.get("evaluation_status") or "Pending",
            "remarks": assignment.get("remarks") or "",
            "verificationStatus": assignment.get("verification_status") or "Unverified",
            "inspectionDate": assignment.get("inspection_date") or "",
            "inspectionTime": assignment.get("inspection_time") or "",
            "inspectionRemarks": assignment.get("inspection_remarks") or "",
            "assignedAt": assignment.get("created_at") or "",
            "applicant": {
                "name": " ".join(
                    part
                    for part in [
                        payload.get("firstName"),
                        payload.get("middleName"),
                        payload.get("lastName"),
                    ]
                    if part
                ).strip(),
                "email": payload.get("email") or payload.get("businessEmail") or "",
                "contact": payload.get("contactNumber") or payload.get("businessMobile") or "",
                "address": payload.get("homeAddress") or payload.get("businessAddress") or "",
            },
            "application": {
                "type": application.get("application_type") or "",
                "submittedId": application.get("submitted_id") or "",
                "submittedAt": application.get("created_at") or "",
                "payload": payload,
            },
        }

    def get_department_assignments(self, config, application_id=None):
        select = (
            "id,application_id,department_key,evaluation_status,remarks,verification_status,"
            "inspection_date,inspection_time,inspection_remarks,created_at,updated_at,"
            "business_permit_applications(id,permit_id,business_name,status,application_type,"
            "submitted_id,application_payload,created_at,user_id)"
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

        if (actor.get("app_metadata") or {}).get("role") != "treasury":
            self.send_json({"error": "This page is only for Treasury accounts."}, status=403)
            return None

        return {
            "supabase_url": supabase_url,
            "supabase_service_key": supabase_service_key,
            "actor": actor,
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
        metadata = actor.get("user_metadata") or {}
        name = " ".join(part for part in [metadata.get("first_name"), metadata.get("last_name")] if part).strip()
        self.send_json({"user": {"id": actor.get("id"), "email": actor.get("email"), "name": name or actor.get("email") or "Treasury Staff", "role": "treasury"}})

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
