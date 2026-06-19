from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit
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

        if request_path.startswith("/admin/api/departments/"):
            department_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_department(department_id)
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def do_DELETE(self):
        request_path = urlsplit(self.path).path

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

        with urlopen(request, timeout=10):
            return

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

            self.create_service_audit_log(
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
            "email": user.get("email") or "",
            "role": role,
            "department": department,
            "status": status,
            "createdAt": user.get("created_at") or "",
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
