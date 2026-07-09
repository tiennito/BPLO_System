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


class PermitServiceMixin:
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

    def finalize_admin_application(self, application_id):
        config = self.admin_config_with_actor("application finalization")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return
            app = bundle["application"]
            payments = bundle.get("payments") or []
            confirmed_payment = next((payment for payment in payments if payment.get("payment_status") == "Confirmed"), None)
            if not confirmed_payment:
                self.send_json({"error": "This application cannot be finalized because payment has not been verified."}, status=400)
                return
            if bundle.get("businessPermit"):
                self.send_json({"message": "Business permit was already generated.", "permit": bundle.get("businessPermit")})
                return

            info = app.get("business_info") or {}
            permit_snapshot = app.get("permit_snapshot") or {}
            issue_date = datetime.now(timezone.utc).date()
            expiration_date = issue_date.replace(year=issue_date.year + 1)
            permit_number = self.generate_workflow_number("BP")
            verification_code = self.generate_workflow_number("VERIFY")
            permit_payload = {
                "application_id": application_id,
                "permit_number": permit_number,
                "control_number": (application_id or "")[:8],
                "business_name": self.app_business_name(info),
                "owner_name": self.app_owner_name(info),
                "business_classification": (bundle.get("classification") or {}).get("name") or info.get("business_classification") or "",
                "business_address": self.app_business_address(info),
                "permit_type": permit_snapshot.get("permitName") or permit_snapshot.get("permit_name") or "Business Permit",
                "issue_date": issue_date.isoformat(),
                "expiration_date": expiration_date.isoformat(),
                "status": "Ready for Release",
                "verification_code": verification_code,
                "qr_code_value": f"BPLO:{permit_number}:{verification_code}",
                "issued_by": config["actor"].get("id"),
            }
            rows = self.service_rest_request(config, "business_permits", method="POST", payload=permit_payload, prefer="return=representation") or []
            self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={"status": "Permit Ready for Release", "progress": "Permit Generated", "finalized_by": config["actor"].get("id"), "finalized_at": utc_now_iso(), "updated_at": utc_now_iso()},
                query=urlencode({"id": f"eq.{application_id}"}),
            )
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "permit_generated", actor=config["actor"], entity_type="business_permit", entity_id=(rows[0] if rows else {}).get("id"), details={"permitNumber": permit_number})
            self.send_json({"message": "Application finalized and business permit generated.", "permit": rows[0] if rows else permit_payload})
        except ValueError:
            self.send_json({"error": "Unable to calculate the permit expiration date."}, status=500)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to finalize application.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to finalize application."}, status=500)

    def release_admin_business_permit(self, application_id):
        config = self.admin_config_with_actor("business permit release")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return

            permit = bundle.get("businessPermit")
            if not permit:
                self.send_json({"error": "Finalize the application before releasing the business permit."}, status=400)
                return

            app = bundle["application"]
            current_status = app.get("status") or ""
            if current_status == "Released":
                self.send_json({"message": "Business permit has already been released.", "permit": permit})
                return

            now = utc_now_iso()
            self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={"status": "Released", "progress": "Permit Released", "updated_at": now},
                query=urlencode({"id": f"eq.{application_id}"}),
            )
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "permit_released_for_pickup",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"permitNumber": permit.get("permit_number"), "applicationId": application_id},
            )
            self.notify_application_owner(
                config["supabase_url"],
                config["supabase_service_key"],
                application_id,
                "Business Permit Ready for Pickup",
                "Your business permit is ready to be claimed at the BPLO office. Please bring your claim requirements upon pickup.",
                notification_type="permit",
                source_role="BPLO",
            )
            self.send_json({"message": "Business permit released successfully and applicant notified for pickup.", "permit": permit})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to release the business permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to release the business permit."}, status=500)

