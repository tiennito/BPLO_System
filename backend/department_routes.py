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


class DepartmentRoutesMixin:
    def parse_multipart_form(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if "multipart/form-data" not in content_type or content_length <= 0:
            return {}, {}

        from email.parser import BytesParser
        from email.policy import default

        body = self.rfile.read(content_length)
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        fields = {}
        files = {}
        for part in message.iter_parts():
            disposition = part.get_content_disposition()
            if disposition != "form-data":
                continue
            name = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename:
                files[name] = {
                    "filename": Path(filename).name,
                    "content_type": part.get_content_type() or "application/octet-stream",
                    "content": payload,
                }
            elif name:
                fields[name] = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return fields, files

    def format_department_evidence(self, record, allow_delete=False):
        profile = record.get("profiles") or {}
        return {
            "id": record.get("id"),
            "applicationId": record.get("application_id"),
            "departmentId": record.get("department_id"),
            "departmentKey": record.get("department_key") or "",
            "uploadedBy": record.get("uploaded_by"),
            "uploadedByName": profile.get("full_name") or profile.get("email") or record.get("uploaded_by") or "Department staff",
            "fileName": record.get("file_name") or "Evidence attachment",
            "fileUrl": record.get("file_url") or "",
            "remarks": record.get("remarks") or "",
            "createdAt": record.get("created_at") or "",
            "allowDelete": allow_delete,
            "viewUrl": f"/department/evidence/{record.get('id')}/view",
            "downloadUrl": f"/department/evidence/{record.get('id')}/download",
        }

    def department_evidence_query(self, config, application_id=None, evidence_id=None, admin=False):
        params = {
            "select": "*",
            "deleted_at": "is.null",
            "order": "created_at.desc",
        }
        if application_id:
            params["application_id"] = f"eq.{application_id}"
        if evidence_id:
            params["id"] = f"eq.{evidence_id}"
            params["limit"] = "1"
        if not admin:
            params["department_key"] = f"eq.{config['department_key']}"
        return urlencode(params)

    def list_department_evidence(self, application_id):
        config = self.ensure_department_request()
        if not config:
            return
        try:
            if not self.get_department_assignments(config, application_id=application_id):
                self.send_json({"error": "Application not found for this department."}, status=404)
                return
            rows = self.service_rest_request(
                config,
                "department_evidence",
                query=self.department_evidence_query(config, application_id=application_id),
            ) or []
            evidence = [
                self.format_department_evidence(row, allow_delete=row.get("uploaded_by") == config["actor"].get("id"))
                for row in rows
            ]
            self.send_json({"evidence": evidence})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to load department evidence.")

    def create_department_evidence(self, application_id):
        config = self.ensure_department_request()
        if not config:
            return
        try:
            if not self.get_department_assignments(config, application_id=application_id):
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            fields, files = self.parse_multipart_form()
            upload = files.get("file") or files.get("evidence")
            if not upload or not upload.get("content"):
                self.send_json({"error": "Evidence file is required."}, status=400)
                return
            if len(upload["content"]) > 10 * 1024 * 1024:
                self.send_json({"error": "Evidence file must be 10 MB or smaller."}, status=400)
                return

            file_name = upload["filename"] or "department-evidence"
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name).strip("._") or "department-evidence"
            storage_path = f"{application_id}/{config['department_key']}/{uuid.uuid4().hex}_{safe_name}"
            self.upload_storage_file(
                config["supabase_url"],
                config["supabase_service_key"],
                "department-evidence",
                storage_path,
                upload["content"],
                upload["content_type"],
            )

            record = {
                "application_id": application_id,
                "department_id": config.get("department_id"),
                "department_key": config["department_key"],
                "uploaded_by": config["actor"].get("id"),
                "file_name": file_name,
                "file_url": storage_path,
                "remarks": (fields.get("remarks") or "").strip(),
            }
            rows = self.service_rest_request(
                config,
                "department_evidence",
                method="POST",
                payload=record,
                prefer="return=representation",
            ) or []
            created = rows[0] if rows else record
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "department_evidence_uploaded",
                actor=config["actor"],
                entity_type="department_evidence",
                entity_id=created.get("id"),
                details={"department": config["department_key"], "applicationId": application_id, "fileName": file_name},
            )
            admin_user_ids = self.get_bplo_notification_users(config)
            self.create_notifications(
                config["supabase_url"],
                config["supabase_service_key"],
                [
                    {
                        "user_id": user_id,
                        "application_id": application_id,
                        "title": "Department Evidence Uploaded",
                        "message": f"{config['department_name']} uploaded evidence for an assigned application.",
                        "type": "document",
                        "source_role": config["department_name"],
                    }
                    for user_id in admin_user_ids
                ],
            )
            self.send_json({"message": "Evidence uploaded.", "evidence": self.format_department_evidence(created, allow_delete=True)}, status=201)
        except HTTPError as error:
            self.department_error(error, "Unable to upload evidence.")
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to upload evidence.")

    def load_department_evidence_record(self, config, evidence_id, admin=False):
        rows = self.service_rest_request(
            config,
            "department_evidence",
            query=self.department_evidence_query(config, evidence_id=evidence_id, admin=admin),
        ) or []
        return rows[0] if rows else None

    def stream_department_evidence_file(self, evidence_id, mode):
        config = self.ensure_department_request()
        if not config:
            return
        try:
            evidence = self.load_department_evidence_record(config, evidence_id)
            if not evidence:
                self.send_json({"error": "Evidence not found for this department."}, status=404)
                return
            file_bytes = self.download_storage_file(config["supabase_url"], config["supabase_service_key"], "department-evidence", evidence.get("file_url") or "")
            self.send_file_bytes(
                file_bytes,
                evidence.get("file_name") or "department-evidence",
                self.content_type_for_filename(evidence.get("file_name")),
                "attachment" if mode == "download" else "inline",
            )
        except HTTPError as error:
            self.department_error(error, "Unable to load evidence file.")
        except (URLError, TimeoutError) as error:
            self.department_error(error, "Unable to load evidence file.")

    def delete_department_evidence(self, evidence_id):
        config = self.ensure_department_request()
        if not config:
            return
        try:
            evidence = self.load_department_evidence_record(config, evidence_id)
            if not evidence:
                self.send_json({"error": "Evidence not found for this department."}, status=404)
                return
            if evidence.get("uploaded_by") != config["actor"].get("id"):
                self.send_json({"error": "Only the uploader can delete this evidence."}, status=403)
                return
            rows = self.service_rest_request(
                config,
                "department_evidence",
                method="PATCH",
                payload={"deleted_at": utc_now_iso()},
                query=urlencode({"id": f"eq.{evidence_id}", "department_key": f"eq.{config['department_key']}"}),
                prefer="return=representation",
            ) or []
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "department_evidence_deleted",
                actor=config["actor"],
                entity_type="department_evidence",
                entity_id=evidence_id,
                details={"department": config["department_key"], "softDelete": True},
            )
            self.send_json({"message": "Evidence deleted.", "evidence": rows[0] if rows else evidence})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to delete evidence.")

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
            evidence_rows = self.service_rest_request(
                config,
                "department_evidence",
                query=self.department_evidence_query(config, application_id=application_id),
            ) or []
            evidence = [
                self.format_department_evidence(row, allow_delete=row.get("uploaded_by") == config["actor"].get("id"))
                for row in evidence_rows
            ]
            self.send_json({"assessment": assessment, "assessmentItem": item, "assessmentItems": items, "inspection": inspection, "evidence": evidence})
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
                notification_message = f"Your application has been approved by the {department_name}."
            elif status == "Rejected":
                details = f" Reason: {remarks}" if remarks else ""
                notification_message = f"Your application needs revision from the {department_name}.{details} Please review the required changes."
            else:
                details = f" Remarks: {remarks}" if remarks else ""
                notification_message = f"The {department_name} updated your application review status to {status}.{details}"
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

    def export_department_reports(self):
        config = self.ensure_department_request()
        if not config:
            return
        try:
            params = self.get_query_params()
            fmt = self.first_query_value(params, "format", "csv").lower()
            rows = self.service_rest_request(
                config,
                "department_reports",
                query=urlencode(
                    {
                        "select": "*",
                        "department_key": f"eq.{config['department_key']}",
                        "deleted_at": "is.null",
                        "order": "report_date.desc,created_at.desc",
                    }
                ),
            ) or []
            headers = ["Report ID", "Applicant", "Business Name", "Report Type", "Report Date", "Status", "Remarks"]
            data = [
                [
                    row.get("id"),
                    row.get("applicant_name"),
                    row.get("business_name"),
                    row.get("report_type"),
                    row.get("report_date"),
                    row.get("status"),
                    row.get("remarks"),
                ]
                for row in rows
            ]
            if fmt == "pdf":
                self.send_text_download(
                    self.html_report(
                        f"{config['department_name']} Department Report",
                        headers,
                        data,
                        {"Total Reports": len(data), "Department": config["department_name"]},
                    ),
                    "department-report.html",
                    "text/html; charset=utf-8",
                )
                return
            self.send_text_download(self.csv_report(headers, data), "department-report.csv", "text/csv; charset=utf-8")
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to export department report.")

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
            silent = payload.get("silent") is True

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
            if not silent:
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

