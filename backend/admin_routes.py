from datetime import datetime, timedelta, timezone
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

from .config import BASE_DIR, STATIC_DIR, ENV_FILE, HOST, PORT, PAGE_ROUTES
from .utils import (
    dashboard_path_for_role,
    department_key_from_name,
    normalize_business_classification_key,
    normalize_business_classification_value,
    normalize_role,
    profile_status,
    slugify_key,
    utc_now_iso,
)


class AdminRoutesMixin:
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

    def stream_application_document_file(self, document_id, mode):
        config = self.ensure_authenticated_request()
        if not config:
            return
        supabase_url, service_key, actor = config
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "application_documents",
                {
                    "select": "id,application_id,file_url,file_name,upload_status,applications(id,applicant_id)",
                    "id": f"eq.{document_id}",
                    "limit": 1,
                },
            ) or []
            if not rows:
                self.send_json({"error": "Document not found."}, status=404)
                return
            document = rows[0]
            application = document.get("applications") or {}
            profile = self.get_profile_by_auth_user_id(supabase_url, service_key, actor.get("id")) or {}
            role = normalize_role(profile.get("role") or (actor.get("app_metadata") or {}).get("role"))
            application_id = document.get("application_id")
            allowed = role in {"super_admin", "bplo_admin"}
            if role == "applicant":
                allowed = application.get("applicant_id") == actor.get("id")
            elif role == "department_office":
                department = self.load_department_by_id(supabase_url, service_key, profile.get("department_id"))
                department_key = profile.get("department_key") or department_key_from_name((department or {}).get("name") or profile.get("department_name"))
                allowed = bool(department_key and self.supabase_rest_request(
                    supabase_url,
                    service_key,
                    "application_department_reviews",
                    {
                        "select": "id",
                        "application_id": f"eq.{application_id}",
                        "department_key": f"eq.{department_key}",
                        "limit": 1,
                    },
                ))
            elif role == "treasury":
                allowed = bool(self.supabase_rest_request(
                    supabase_url,
                    service_key,
                    "treasury_payment_queue",
                    {"select": "id", "application_id": f"eq.{application_id}", "limit": 1},
                ))

            if not allowed:
                self.send_json({"error": "You are not allowed to access this document."}, status=403)
                return
            file_path = document.get("file_url") or ""
            if not file_path:
                self.send_json({"error": "No file is attached to this document."}, status=404)
                return
            file_name = document.get("file_name") or Path(file_path).name or "application-document"
            file_bytes = self.download_storage_file(supabase_url, service_key, "application-documents", file_path)
            self.send_file_bytes(
                file_bytes,
                file_name,
                self.content_type_for_filename(file_name),
                "attachment" if mode == "download" else "inline",
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load document.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load document."}, status=500)

    def stream_admin_department_evidence_file(self, evidence_id, mode):
        config = self.ensure_admin_request("department evidence access")
        if not config:
            return
        supabase_url, service_key = config
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "department_evidence",
                {
                    "select": "*",
                    "id": f"eq.{evidence_id}",
                    "deleted_at": "is.null",
                    "limit": 1,
                },
            ) or []
            if not rows:
                self.send_json({"error": "Evidence not found."}, status=404)
                return
            evidence = rows[0]
            file_name = evidence.get("file_name") or Path(evidence.get("file_url") or "").name or "department-evidence"
            file_bytes = self.download_storage_file(supabase_url, service_key, "department-evidence", evidence.get("file_url") or "")
            self.send_file_bytes(
                file_bytes,
                file_name,
                self.content_type_for_filename(file_name),
                "attachment" if mode == "download" else "inline",
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load evidence.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load evidence."}, status=500)

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

    def export_admin_reports(self):
        config = self.admin_config_with_actor("report export")
        if not config:
            return
        try:
            params = self.get_query_params()
            report_type = self.first_query_value(params, "type", "applications").lower()
            title = "BPLO Applications Report"
            headers = ["Application ID", "Business Name", "Owner Name", "Permit Type", "Status", "Payment Status", "Date Submitted", "Date Finalized"]
            data = []

            if report_type in {"payments", "payment"}:
                title = "BPLO Payment Report"
                headers = ["Application ID", "Business Name", "Owner Name", "Amount Paid", "Payment Status", "OR Number", "Date Paid"]
                rows = self.service_rest_request(
                    config,
                    "payments",
                    query=urlencode({"select": "*,applications(id,business_info)", "order": "paid_at.desc", "limit": "1000"}),
                ) or []
                data = [
                    [
                        row.get("application_id"),
                        self.app_business_name((row.get("applications") or {}).get("business_info") or {}),
                        self.app_owner_name((row.get("applications") or {}).get("business_info") or {}),
                        self.money(row.get("amount_paid")),
                        row.get("payment_status"),
                        row.get("official_receipt_number"),
                        row.get("paid_at"),
                    ]
                    for row in rows
                ]
            elif report_type in {"assessment", "assessments"}:
                title = "BPLO Assessment Summary Report"
                headers = ["Application ID", "Assessment No.", "Status", "Subtotal", "Penalty", "Discount", "Grand Total"]
                rows = self.service_rest_request(
                    config,
                    "assessments",
                    query=urlencode({"select": "*", "order": "created_at.desc", "limit": "1000"}),
                ) or []
                data = [
                    [
                        row.get("application_id"),
                        row.get("assessment_number"),
                        row.get("status"),
                        self.money(row.get("subtotal")),
                        self.money(row.get("penalty_total")),
                        self.money(row.get("discount_total")),
                        self.money(row.get("grand_total")),
                    ]
                    for row in rows
                ]
            elif report_type in {"permits", "permit-release", "permit_release"}:
                title = "BPLO Permit Release Report"
                headers = ["Application ID", "Permit Number", "Business Name", "Owner Name", "Status", "Issue Date", "Release Date"]
                rows = self.service_rest_request(
                    config,
                    "business_permits",
                    query=urlencode({"select": "*", "order": "created_at.desc", "limit": "1000"}),
                ) or []
                data = [
                    [
                        row.get("application_id"),
                        row.get("permit_number"),
                        row.get("business_name"),
                        row.get("owner_name"),
                        row.get("status"),
                        row.get("issue_date"),
                        row.get("released_at"),
                    ]
                    for row in rows
                ]
            else:
                rows = self.service_rest_request(
                    config,
                    "applications",
                    query=urlencode({"select": "id,status,payment_status,business_info,permit_snapshot,submitted_at,finalized_at,created_at", "order": "created_at.desc", "limit": "1000"}),
                ) or []
                data = [
                    [
                        row.get("id"),
                        self.app_business_name(row.get("business_info") or {}),
                        self.app_owner_name(row.get("business_info") or {}),
                        (row.get("permit_snapshot") or {}).get("permitName") or (row.get("permit_snapshot") or {}).get("permit_name") or "Business Permit",
                        row.get("status"),
                        row.get("payment_status"),
                        row.get("submitted_at") or row.get("created_at"),
                        row.get("finalized_at"),
                    ]
                    for row in rows
                ]

            search = self.first_query_value(params, "search", "").lower()
            status_filter = self.first_query_value(params, "status", "")
            date_from = self.first_query_value(params, "dateFrom", "")
            date_to = self.first_query_value(params, "dateTo", "")
            range_filter = self.first_query_value(params, "range", "").lower()
            today = datetime.now(timezone.utc).date()
            if range_filter == "today":
                date_from = date_to = today.isoformat()
            elif range_filter == "week":
                date_from = (today - timedelta(days=6)).isoformat()
                date_to = today.isoformat()
            elif range_filter == "monthly":
                date_from = today.replace(day=1).isoformat()
                date_to = today.isoformat()
            elif range_filter == "yearly":
                date_from = today.replace(month=1, day=1).isoformat()
                date_to = today.isoformat()

            status_index = headers.index("Status") if "Status" in headers else -1
            date_index = next((index for index, header in enumerate(headers) if header.lower().startswith("date ")), -1)
            if search or status_filter or date_from or date_to:
                filtered = []
                for row in data:
                    haystack = " ".join(str(value or "") for value in row).lower()
                    row_date = str(row[date_index] or "")[:10] if date_index >= 0 else ""
                    if search and search not in haystack:
                        continue
                    if status_filter and (status_index < 0 or row[status_index] != status_filter):
                        continue
                    if date_from and row_date < date_from:
                        continue
                    if date_to and row_date > date_to:
                        continue
                    filtered.append(row)
                data = filtered

            status_counts = {}
            if status_index >= 0:
                for row in data:
                    status_counts[row[status_index] or "-"] = status_counts.get(row[status_index] or "-", 0) + 1
            summary = {"Total Records": len(data), **status_counts}
            if not data:
                self.send_json({"error": "No records available for export."}, status=404)
                return
            self.send_binary_download(self.pdf_report(title, headers, data, summary), f"{report_type}-report.pdf", "application/pdf")
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to export report."}, status=500)
        except ValueError as error:
            self.send_json({"error": str(error) or "No records available for export."}, status=404)

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

    def load_application_core(self, supabase_url, service_key, application_id):
        rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "applications",
            {
                "select": "id,permit_id,applicant_id,status,progress,payment_status,assessment_status,business_info,permit_snapshot,business_classification_id,submitted_at,reviewed_at,initial_reviewed_by,initial_reviewed_at,finalized_by,finalized_at,created_at,updated_at,application_type,permit_year,source_permit_id,renewal_due_date,original_renewal_due_date,effective_renewal_due_date,filed_at,payment_completed_at,is_late",
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
        renewal_change_rows = []
        previous_permit_rows = []
        previous_receipt_rows = []
        if application.get("application_type") == "renewal":
            renewal_change_rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "renewal_change_logs",
                {"select": "*", "renewal_application_id": f"eq.{application_id}", "order": "changed_at.desc"},
            ) or []
            previous_permit_id = application.get("source_permit_id") or application.get("previous_permit_id")
            if previous_permit_id:
                previous_permit_rows = self.supabase_rest_request(
                    supabase_url,
                    service_key,
                    "business_permits",
                    {"select": "*", "id": f"eq.{previous_permit_id}", "limit": 1},
                ) or []
            if application.get("previous_application_id"):
                previous_receipt_rows = self.supabase_rest_request(
                    supabase_url,
                    service_key,
                    "official_receipts",
                    {"select": "*", "application_id": f"eq.{application.get('previous_application_id')}", "order": "issued_at.desc"},
                ) or []
        try:
            evidence_rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "department_evidence",
                {
                    "select": "*",
                    "application_id": f"eq.{application_id}",
                    "deleted_at": "is.null",
                    "order": "created_at.desc",
                },
            ) or []
        except HTTPError:
            evidence_rows = []
        try:
            structured_ocr_rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "ocr_results",
                {
                    "select": "id,application_id,document_id,document_type,extracted_fields_json,confidence_score,correction_status,corrected_by,corrected_at,created_at",
                    "application_id": f"eq.{application_id}",
                    "order": "created_at.desc",
                },
            ) or []
        except HTTPError:
            structured_ocr_rows = []
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
            "renewalChanges": renewal_change_rows,
            "previousPermit": previous_permit_rows[0] if previous_permit_rows else None,
            "previousReceipts": previous_receipt_rows,
            "departmentEvidence": evidence_rows,
            "ocrResults": structured_ocr_rows,
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
            "applicationType": "Renewal" if app.get("application_type") == "renewal" else (info.get("application_type") or info.get("applicationType") or "New Application"),
            "renewal": {
                "isRenewal": app.get("application_type") == "renewal",
                "renewalYear": app.get("permit_year"),
                "renewalNumber": app.get("renewal_application_number"),
                "previousApplicationId": app.get("previous_application_id"),
                "previousApplicationReference": (app.get("previous_application_id") or "")[:8],
                "previousPermit": bundle.get("previousPermit"),
                "previousReceipts": bundle.get("previousReceipts") or [],
                "changes": bundle.get("renewalChanges") or [],
                "baseline": app.get("renewal_baseline") or {},
            },
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
            "ocrResults": bundle.get("ocrResults") or [],
            "documentReviews": bundle.get("documentReviews") or [],
            "departmentReviews": bundle.get("departmentReviews") or [],
            "departmentEvidence": [
                {
                    "id": evidence.get("id"),
                    "departmentKey": evidence.get("department_key") or "",
                    "fileName": evidence.get("file_name") or "Department evidence",
                    "remarks": evidence.get("remarks") or "",
                    "uploadedByName": (evidence.get("profiles") or {}).get("full_name") or (evidence.get("profiles") or {}).get("email") or evidence.get("uploaded_by") or "Department staff",
                    "createdAt": evidence.get("created_at") or "",
                    "viewUrl": f"/admin/department-evidence/{evidence.get('id')}/view",
                    "downloadUrl": f"/admin/department-evidence/{evidence.get('id')}/download",
                }
                for evidence in (bundle.get("departmentEvidence") or [])
            ],
            "assessment": assessment,
            "assessmentItems": items,
            "departmentTotals": department_totals,
            "treasuryQueue": bundle.get("treasuryQueue"),
            "payments": bundle.get("payments") or [],
            "receipts": bundle.get("receipts") or [],
            "businessPermit": bundle.get("businessPermit"),
        }

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
                "Your application is now under BPLO review and has been forwarded to the required offices for department evaluation.",
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
                f"Your application needs revision. Please review this BPLO note: {remarks}" if status == "For Revision" else f"Your application was rejected by BPLO. Reason: {remarks}" if status == "Rejected" else remarks or f"Your application status is now {status}.",
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

