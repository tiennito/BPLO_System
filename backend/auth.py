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


class AuthMixin:
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
        except (URLError, TimeoutError) as error:
            print(
                "[auth] profile service unavailable",
                json.dumps({"errorType": type(error).__name__, "reason": str(getattr(error, "reason", error))}),
            )
            self.send_json(
                {"error": "The account service is temporarily unavailable. Please try again in a moment."},
                status=503,
            )
        except json.JSONDecodeError as error:
            print("[auth] invalid profile service response", json.dumps({"reason": str(error)}))
            self.send_json(
                {"error": "The account service returned an invalid response. Please try again."},
                status=502,
            )

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
        except (URLError, TimeoutError) as error:
            print(
                "[auth] session verification unavailable",
                json.dumps({"errorType": type(error).__name__, "reason": str(getattr(error, "reason", error))}),
            )
            self.send_json(
                {"error": "The account service is temporarily unavailable. Please try again in a moment."},
                status=503,
            )
            return None
        except json.JSONDecodeError as error:
            print("[auth] invalid session response", json.dumps({"reason": str(error)}))
            self.send_json({"error": "The account service returned an invalid response. Please try again."}, status=502)
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

    def get_request_actor(self, supabase_url):
        auth_header = self.headers.get("Authorization", "")
        access_token = auth_header.removeprefix("Bearer ").strip()
        supabase_client_key = (
            os.getenv("SUPABASE_ANON_KEY", "").strip()
            or os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
        )
        return self.get_session_user(access_token, supabase_url, supabase_client_key)

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

