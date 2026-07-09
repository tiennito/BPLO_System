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


class SupabaseClientMixin:
    def upload_storage_file(self, supabase_url, service_key, bucket, file_path, file_bytes, content_type="application/octet-stream"):
        encoded_path = quote(file_path, safe="/")
        request = Request(
            f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{encoded_path}",
            data=file_bytes,
            method="POST",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": content_type or "application/octet-stream",
                "x-upsert": "true",
            },
        )

        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body or "{}")

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

