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

