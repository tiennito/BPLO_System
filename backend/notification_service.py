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


class NotificationServiceMixin:
    def create_notification(
        self,
        supabase_url,
        service_key,
        user_id,
        title,
        message,
        notification_type="system",
        source_role="System",
        application_id=None,
        related_permit_id=None,
        action_url=None,
    ):
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
                    "related_permit_id": related_permit_id,
                    "action_url": action_url,
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
            "relatedPermitId": notification.get("related_permit_id"),
            "actionUrl": notification.get("action_url") or "",
            "title": notification.get("title") or "",
            "message": notification.get("message") or "",
            "type": notification.get("type") or "system",
            "sourceRole": notification.get("source_role") or "System",
            "isRead": bool(notification.get("is_read")),
            "createdAt": notification.get("created_at") or "",
            "readAt": notification.get("read_at") or "",
        }

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

