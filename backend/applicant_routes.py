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


class ApplicantRoutesMixin:
    APPLICANT_DRAFT_STATUSES = {"Draft"}
    APPLICANT_UNFINISHED_STATUSES = {
        "Draft",
        "Submitted",
        "Under Review",
        "For Revision",
        "Under Office Evaluation",
        "Under Department Evaluation",
        "Assessment Finalized",
        "For Payment",
        "Payment Verified",
        "Paid",
        "Finalized",
        "Ready for Pickup",
        "Permit Ready for Release",
    }

    def format_applicant_application_summary(self, application):
        business_info = application.get("business_info") or {}
        permit_snapshot = application.get("permit_snapshot") or {}
        return {
            "id": application.get("id"),
            "permitId": application.get("permit_id"),
            "permitName": permit_snapshot.get("permitName") or permit_snapshot.get("permit_name") or "Business Permit",
            "permitCode": permit_snapshot.get("permitCode") or permit_snapshot.get("permit_code") or "",
            "status": application.get("status") or "Draft",
            "progress": application.get("progress") or "Draft",
            "businessName": business_info.get("business_name") or business_info.get("businessName") or "",
            "ownerName": self.app_owner_name(business_info),
            "updatedAt": application.get("updated_at") or application.get("created_at") or "",
            "createdAt": application.get("created_at") or "",
            "submittedAt": application.get("submitted_at") or "",
            "currentStep": business_info.get("_current_step") or application.get("progress") or "Business Information",
        }

    def format_applicant_document_summary(self, document):
        snapshot = document.get("document_snapshot") or {}
        return {
            "id": document.get("id"),
            "permitDocumentId": document.get("permit_document_id"),
            "documentName": snapshot.get("documentName") or snapshot.get("document_name") or "Document",
            "fileName": document.get("file_name") or "",
            "uploadStatus": document.get("upload_status") or "Pending",
            "ocrStatus": document.get("ocr_status") or "",
            "uploadedAt": document.get("uploaded_at") or "",
            "hasFile": bool(document.get("file_url")),
        }

    def load_owned_applicant_application(self, supabase_url, service_key, user_id, application_id, select="*"):
        rows = self.supabase_rest_request(
            supabase_url,
            service_key,
            "applications",
            {
                "select": select,
                "id": f"eq.{application_id}",
                "applicant_id": f"eq.{user_id}",
                "limit": 1,
            },
        )
        return rows[0] if rows else None

    def list_applicant_drafts(self):
        config = self.ensure_applicant_request("draft listing")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {
                    "select": "id,permit_id,status,progress,business_info,permit_snapshot,created_at,updated_at,submitted_at",
                    "applicant_id": f"eq.{user.get('id')}",
                    "status": "eq.Draft",
                    "order": "updated_at.desc.nullslast,created_at.desc",
                    "limit": 20,
                },
            ) or []
            self.send_json({"drafts": [self.format_applicant_application_summary(row) for row in rows]})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load drafts.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load drafts."}, status=500)

    def get_applicant_draft(self, application_id):
        config = self.ensure_applicant_request("draft loading")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            application = self.load_owned_applicant_application(
                supabase_url,
                supabase_service_key,
                user.get("id"),
                application_id,
                select="id,permit_id,status,progress,business_info,permit_snapshot,created_at,updated_at,submitted_at",
            )
            if not application:
                self.send_json({"error": "Draft application not found."}, status=404)
                return
            if application.get("status") not in self.APPLICANT_DRAFT_STATUSES:
                self.send_json({"error": "This application has already been submitted and can no longer be edited as a draft."}, status=409)
                return

            documents = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "id,permit_document_id,document_snapshot,file_name,file_url,upload_status,ocr_status,uploaded_at",
                    "application_id": f"eq.{application_id}",
                    "order": "created_at.asc",
                },
            ) or []

            self.send_json(
                {
                    "draft": self.format_applicant_application_summary(application),
                    "businessInfo": application.get("business_info") or {},
                    "documents": [self.format_applicant_document_summary(document) for document in documents],
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load draft.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load draft."}, status=500)

    def save_applicant_draft(self, application_id):
        config = self.ensure_applicant_request("draft auto-save")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            payload = self.read_json_body()
            business_info = payload.get("business_info") or payload.get("businessInfo") or {}
            current_step = (payload.get("current_step") or payload.get("currentStep") or "Business Information").strip()
            if not isinstance(business_info, dict):
                self.send_json({"error": "Business information must be an object."}, status=400)
                return

            application = self.load_owned_applicant_application(
                supabase_url,
                supabase_service_key,
                user.get("id"),
                application_id,
                select="id,status,business_info",
            )
            if not application:
                self.send_json({"error": "Draft application not found."}, status=404)
                return
            if application.get("status") not in self.APPLICANT_DRAFT_STATUSES:
                self.send_json({"error": "Submitted applications cannot be overwritten by auto-save."}, status=409)
                return

            merged_info = dict(application.get("business_info") or {})
            merged_info.update(business_info)
            merged_info["_current_step"] = current_step
            updated = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {"id": f"eq.{application_id}", "applicant_id": f"eq.{user.get('id')}"},
                method="PATCH",
                payload={
                    "business_info": merged_info,
                    "progress": current_step or "Draft",
                    "updated_at": utc_now_iso(),
                },
                prefer="return=representation",
            )
            self.send_json(
                {
                    "message": "Draft auto-saved.",
                    "savedAt": utc_now_iso(),
                    "draft": self.format_applicant_application_summary(updated[0] if updated else {"id": application_id, "business_info": merged_info}),
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to auto-save draft.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to auto-save draft."}, status=500)

    def applicant_progress_step(self, key, label, state="Not Yet Available", remarks="", completed_at=""):
        return {
            "key": key,
            "label": label,
            "state": state,
            "remarks": remarks or "",
            "completedAt": completed_at or "",
        }

    def build_applicant_progress(self, config, application):
        application_id = application.get("id")
        status = application.get("status") or "Draft"
        progress = application.get("progress") or ""
        submitted_at = application.get("submitted_at") or ""
        payment_status = application.get("payment_status") or ""
        assessment_status = application.get("assessment_status") or ""

        submitted_state = "Completed" if submitted_at or status not in {"Draft"} else "Pending"
        bplo_state = "Pending"
        department_state = "Locked"
        assessment_state = "Locked"
        payment_state = "Locked"
        finalization_state = "Locked"
        release_state = "Locked"

        if status in {"Under Review"}:
            bplo_state = "In Progress"
        elif status in {"Submitted"}:
            bplo_state = "Pending"
        elif status in {"For Revision"}:
            bplo_state = "For Revision"
        elif status not in {"Draft", "Submitted"}:
            bplo_state = "Completed"

        if status in {"Under Office Evaluation", "Under Department Evaluation"}:
            department_state = "In Progress"
        elif status in {"For Revision", "Rejected"}:
            department_state = "For Revision" if status == "For Revision" else "Rejected"
        elif status in {"Assessment Finalized", "For Payment", "Payment Verified", "Paid", "Finalized", "Permit Ready for Release", "Ready for Pickup", "Permit Released", "Released"}:
            department_state = "Completed"

        if assessment_status == "Completed" or status in {"Assessment Finalized", "For Payment", "Payment Verified", "Paid", "Finalized", "Permit Ready for Release", "Ready for Pickup", "Permit Released", "Released"}:
            assessment_state = "Completed"
        elif department_state == "Completed":
            assessment_state = "In Progress"

        if payment_status in {"Payment Verified", "Paid"} or status in {"Payment Verified", "Paid", "Finalized", "Permit Ready for Release", "Ready for Pickup", "Permit Released", "Released"}:
            payment_state = "Completed"
        elif status in {"For Payment", "Assessment Finalized"}:
            payment_state = "In Progress"

        if status in {"Finalized", "Permit Ready for Release", "Ready for Pickup", "Permit Released", "Released"}:
            finalization_state = "Completed"
        elif payment_state == "Completed":
            finalization_state = "In Progress"

        if status in {"Permit Ready for Release", "Ready for Pickup"}:
            release_state = "In Progress"
        elif status in {"Permit Released", "Released"}:
            release_state = "Completed"
        elif finalization_state == "Completed":
            release_state = "Pending"

        department_rows = self.service_rest_request(
            config,
            "application_department_reviews",
            query=urlencode(
                {
                    "select": "department_id,department_key,status,remarks,completed_at,updated_at",
                    "application_id": f"eq.{application_id}",
                    "order": "department_key.asc",
                }
            ),
        ) or []
        if not department_rows:
            department_rows = self.service_rest_request(
                config,
                "department_application_assignments",
                query=urlencode(
                    {
                        "select": "department_key,evaluation_status,remarks,updated_at",
                        "application_id": f"eq.{application_id}",
                        "deleted_at": "is.null",
                        "order": "department_key.asc",
                    }
                ),
            ) or []

        departments = []
        for row in department_rows:
            raw_state = row.get("status") or row.get("evaluation_status") or "Pending"
            state = {
                "Approved": "Completed",
                "Pending": "Pending",
                "In Progress": "In Progress",
                "For Revision": "For Revision",
                "Correction Needed": "For Revision",
                "Rejected": "Rejected",
            }.get(raw_state, raw_state)
            department_key = row.get("department_key") or ""
            departments.append(
                {
                    "departmentKey": department_key,
                    "departmentName": department_key.replace("_", " ").title() if department_key else "Department",
                    "state": state,
                    "remarks": row.get("remarks") or "",
                    "completedAt": row.get("completed_at") or (row.get("updated_at") if state == "Completed" else ""),
                }
            )

        if departments:
            if any(item["state"] in {"Rejected", "For Revision"} for item in departments):
                department_state = next(item["state"] for item in departments if item["state"] in {"Rejected", "For Revision"})
            elif all(item["state"] == "Completed" for item in departments):
                department_state = "Completed"
            else:
                department_state = "In Progress"

        return {
            "application": self.format_applicant_application_summary(application),
            "steps": [
                self.applicant_progress_step("submitted", "Submitted", submitted_state, completed_at=submitted_at),
                self.applicant_progress_step("bplo_review", "BPLO Review", bplo_state),
                self.applicant_progress_step("department_review", "Department Review", department_state),
                self.applicant_progress_step("assessment", "Assessment", assessment_state),
                self.applicant_progress_step("payment", "Payment", payment_state),
                self.applicant_progress_step("finalization", "Finalization", finalization_state),
                self.applicant_progress_step("for_release", "For Release", release_state),
            ],
            "departments": departments,
            "status": status,
            "progress": progress,
        }

    def get_applicant_application_progress(self, application_id):
        config = self.ensure_applicant_request("application progress")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            application = self.load_owned_applicant_application(
                supabase_url,
                supabase_service_key,
                user.get("id"),
                application_id,
                select="id,permit_id,status,progress,business_info,permit_snapshot,created_at,updated_at,submitted_at,payment_status,assessment_status",
            )
            if not application:
                self.send_json({"error": "Application not found."}, status=404)
                return
            self.send_json(self.build_applicant_progress(
                {
                    "supabase_url": supabase_url,
                    "supabase_service_key": supabase_service_key,
                    "actor": user,
                },
                application,
            ))
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load progress.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load progress."}, status=500)

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

            existing_drafts = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {
                    "select": "id,permit_id,status,progress,business_info,permit_snapshot,created_at,updated_at,submitted_at",
                    "permit_id": f"eq.{permit_id}",
                    "applicant_id": f"eq.{user.get('id')}",
                    "status": "eq.Draft",
                    "order": "updated_at.desc.nullslast,created_at.desc",
                    "limit": 1,
                },
            ) or []
            if existing_drafts:
                existing = existing_drafts[0]
                self.send_json(
                    {
                        "message": "You already have an unfinished application for this permit.",
                        "application": existing,
                        "permit": permit,
                        "reusedDraft": True,
                    },
                    status=200,
                )
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
                "Your business permit application draft has been created. You can continue it from your applicant dashboard.",
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
                "Your application has been submitted successfully and is now waiting for BPLO review.",
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

