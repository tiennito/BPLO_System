from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import hashlib
import json
import os
import re
import secrets
import tempfile
import uuid

from .config import BASE_DIR, STATIC_DIR, ENV_FILE, HOST, PORT, PAGE_ROUTES
from .permit_document import permit_storage_path, render_permit_pdf, render_permit_svg
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
from .renewal_service import calendar_permit_validity, manila_now


class PermitServiceMixin:
    PUBLISHED_PERMIT_STATUSES = {"Published", "Active"}
    EDITABLE_PERMIT_STATUSES = {"Draft"}

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
        permit_code = permit.get("permit_code") or ""
        if (permit.get("status") or "") == "Draft" and permit_code.startswith("DRAFT-"):
            permit_code = ""
        status = self.normalize_status_value(permit.get("status") or "Draft")

        return {
            "id": permit.get("id"),
            "permitName": permit.get("permit_name") or "",
            "permitCode": permit_code,
            "category": permit.get("category") or "",
            "description": permit.get("description") or "",
            "status": status,
            "processingFee": permit.get("processing_fee"),
            "applicantNotes": permit.get("applicant_notes") or "",
            "createdAt": permit.get("created_at") or "",
            "updatedAt": permit.get("updated_at") or "",
            "lastSavedAt": permit.get("last_saved_at") or permit.get("updated_at") or "",
            "documents": documents if documents is not None else [],
            "requiredOffices": offices if offices is not None else [],
        }

    def normalize_status_value(self, status):
        status = (status or "Draft").strip()
        aliases = {
            "Active": "Published",
            "Inactive": "Archived",
        }
        return aliases.get(status, status)

    def database_status_value(self, status):
        status = self.normalize_status_value(status)
        legacy_aliases = {
            "Published": "Active",
            "Archived": "Inactive",
        }
        return legacy_aliases.get(status, status)

    def validate_permit_document_values(self, document_name, accepted_file_types, max_file_size):
        if not document_name:
            raise ValueError("Every document requirement needs a document name.")
        if not accepted_file_types:
            raise ValueError(f"Accepted file types are required for {document_name}.")

        file_types = [item.strip().lower().lstrip(".") for item in accepted_file_types.split(",") if item.strip()]
        if not file_types:
            raise ValueError(f"Accepted file types are required for {document_name}.")
        invalid_types = [item for item in file_types if not re.fullmatch(r"[a-z0-9]+", item)]
        if invalid_types:
            raise ValueError(f"Accepted file types for {document_name} must be comma-separated values like PDF, JPG, PNG.")

        if max_file_size and not re.fullmatch(r"\d+(?:\.\d+)?\s*(?:KB|MB|GB)", max_file_size.strip(), re.IGNORECASE):
            raise ValueError(f"Max file size for {document_name} must look like 5 MB, 500 KB, or 1 GB.")

    def normalize_permit_payload(self, payload, publish=False, allow_blank_draft=False):
        permit_name = (payload.get("permitName") or "").strip()
        permit_code = (payload.get("permitCode") or "").strip()
        category = (payload.get("category") or "").strip()
        description = (payload.get("description") or "").strip()
        status = self.normalize_status_value(payload.get("status") or ("Published" if publish else "Draft"))
        applicant_notes = (payload.get("applicantNotes") or "").strip()
        processing_fee_raw = payload.get("processingFee")

        if publish and not permit_name:
            raise ValueError("Permit name is required.")
        if publish and not category:
            raise ValueError("Permit category is required.")
        if status not in {"Draft", "Published", "Archived"}:
            raise ValueError("Permit status must be Draft, Published, or Archived.")

        if not permit_code:
            permit_code = f"DRAFT-{uuid.uuid4().hex[:12].upper()}"

        processing_fee = None
        if processing_fee_raw not in (None, ""):
            processing_fee = float(processing_fee_raw)
            if processing_fee < 0:
                raise ValueError("Processing fee cannot be negative.")

        documents = payload.get("documents") or []
        normalized_documents = []
        seen_document_names = set()
        for document in documents:
            document_name = (document.get("documentName") or document.get("name") or "").strip()
            upload_required = bool(document.get("uploadRequired", document.get("upload_required", True)))
            requirement_type = "Required" if upload_required else "Optional"
            accepted_file_types = (
                document.get("acceptedFileTypes") or document.get("fileTypes") or ""
            ).strip()
            max_file_size = (document.get("maxFileSize") or document.get("maxSize") or "").strip()
            self.validate_permit_document_values(document_name, accepted_file_types, max_file_size)

            document_key = document_name.lower()
            if document_key in seen_document_names:
                raise ValueError(f"Duplicate document requirement: {document_name}.")
            seen_document_names.add(document_key)

            document_id = (document.get("id") or "").strip()
            if document_id:
                try:
                    uuid.UUID(document_id)
                except ValueError:
                    document_id = ""

            normalized_document = {
                "document_name": document_name,
                "short_description": (document.get("shortDescription") or document.get("description") or "").strip(),
                "requirement_type": requirement_type,
                "accepted_file_types": accepted_file_types,
                "max_file_size": max_file_size,
                "upload_required": upload_required,
                "notes": (document.get("notes") or "").strip(),
            }
            if document_id:
                normalized_document["id"] = document_id

            normalized_documents.append(normalized_document)

        if publish and not normalized_documents:
            raise ValueError("Add at least one document requirement before publishing a permit.")
        if publish and not any(doc["upload_required"] for doc in normalized_documents):
            raise ValueError("Mark at least one document as applicant upload required before publishing a permit.")

        required_office_ids = []
        for office_id in payload.get("requiredOfficeIds") or []:
            office_id = str(office_id).strip()
            if office_id and office_id not in required_office_ids:
                required_office_ids.append(office_id)
        if publish and not required_office_ids:
            raise ValueError("Select at least one required office before publishing a permit.")

        return {
            "permit": {
                "permit_name": permit_name,
                "permit_code": permit_code,
                "category": category or "Business Permits",
                "description": description,
                "status": self.database_status_value(status),
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
            permit_query["status"] = "in.(Published,Active)"

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
            payload = self.read_json_body()
            actor = self.get_request_actor(supabase_url)
            if payload.get("createBlank") or not payload:
                normalized = {
                    "permit": {
                        "permit_name": "",
                        "permit_code": f"DRAFT-{uuid.uuid4().hex[:12].upper()}",
                        "category": "Business Permits",
                        "description": "",
                        "status": "Draft",
                        "processing_fee": None,
                        "applicant_notes": "",
                    },
                    "documents": [],
                    "requiredOfficeIds": [],
                }
            else:
                normalized = self.normalize_permit_payload(payload, allow_blank_draft=True)
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

            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "permit_draft_created" if permit.get("status") == "Draft" else "permit_created",
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
            payload = self.read_json_body()
            publish = bool(payload.get("publish")) or self.normalize_status_value(payload.get("status")) == "Published"
            normalized = self.normalize_permit_payload(payload, publish=publish, allow_blank_draft=not publish)
            existing = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permits",
                {"select": "id,status,permit_name", "id": f"eq.{permit_id}", "limit": 1},
            )
            if not existing:
                self.send_json({"error": "Permit not found."}, status=404)
                return
            existing_status = existing[0].get("status") or "Draft"
            if existing_status in self.PUBLISHED_PERMIT_STATUSES and not publish:
                self.send_json({"error": "Published permits cannot be edited from the Create Permit page."}, status=409)
                return
            actor = self.get_request_actor(supabase_url)

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

            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "permit_published" if publish else "permit_autosaved",
                actor=actor,
                entity_type="permit",
                entity_id=permit_id,
                details={"permitName": updated[0].get("permit_name"), "status": updated[0].get("status")},
            )
            self.send_json({"message": "Permit published successfully." if publish else "Permit saved automatically.", "permit": self.get_permit_bundle(supabase_url, supabase_service_key, permit_id)})
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
            existing = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "permits",
                {"select": "id,status,permit_name", "id": f"eq.{permit_id}", "limit": 1},
            )
            if not existing:
                self.send_json({"error": "Permit not found."}, status=404)
                return
            existing_permit = existing[0]
            if (existing_permit.get("status") or "Draft") != "Draft":
                actor = self.get_request_actor(supabase_url)
                archive_payload = {"status": self.database_status_value("Archived")}
                archived = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "permits",
                    {"id": f"eq.{permit_id}"},
                    method="PATCH",
                    payload=archive_payload,
                    prefer="return=representation",
                )
                archived_permit = archived[0] if archived else existing_permit
                self.create_service_audit_log(
                    supabase_url,
                    supabase_service_key,
                    "permit_archived",
                    actor=actor,
                    entity_type="permit",
                    entity_id=permit_id,
                    details={"permitName": archived_permit.get("permit_name")},
                )
                self.send_json({"message": "Permit archived successfully.", "permit": self.format_permit(archived_permit)})
                return

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
                    "status": "in.(Published,Active)",
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

    def active_permit_issuance_settings(self, config, release_date):
        try:
            rows = self.service_rest_request(
                config,
                "permit_issuance_settings",
                query=urlencode(
                    {
                        "select": "*",
                        "is_active": "eq.true",
                        "effective_from": f"lte.{release_date.isoformat()}",
                        "or": f"(effective_until.is.null,effective_until.gte.{release_date.isoformat()})",
                        "order": "effective_from.desc,created_at.desc",
                        "limit": "1",
                    }
                ),
            ) or []
        except HTTPError:
            rows = []
        return rows[0] if rows else None

    def public_permit_base_url(self):
        configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if configured:
            return configured
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or f"{HOST}:{PORT}").strip()
        scheme = (self.headers.get("X-Forwarded-Proto") or "http").strip()
        return f"{scheme}://{host}".rstrip("/")

    def confirmed_payment_for_permit(self, bundle):
        payments = bundle.get("payments") or []
        return next((payment for payment in payments if payment.get("payment_status") == "Confirmed"), None)

    def official_receipt_for_payment(self, bundle, payment):
        receipts = [receipt for receipt in (bundle.get("receipts") or []) if receipt.get("status") != "Voided"]
        if payment and payment.get("id"):
            matched = next((receipt for receipt in receipts if receipt.get("payment_id") == payment.get("id")), None)
            if matched:
                return matched
        return receipts[0] if receipts else None

    def permit_generation_eligibility(self, config, bundle):
        app = bundle.get("application") or {}
        assessment = bundle.get("assessment") or {}
        payment = self.confirmed_payment_for_permit(bundle)
        receipt = self.official_receipt_for_payment(bundle, payment)
        current_permit = bundle.get("businessPermit") or {}
        missing = []
        warnings = []

        if not (app.get("initial_reviewed_at") or app.get("reviewed_at")):
            missing.append("Initial BPLO review must be approved.")

        reviews_by_key = {
            (review.get("department_key") or "").strip(): review
            for review in (bundle.get("departmentReviews") or [])
            if review.get("department_key")
        }
        required_offices = bundle.get("requiredOffices") or []
        for office in required_offices:
            department = office.get("department") or {}
            key = office.get("department_key") or department_key_from_name(department.get("name"))
            label = department.get("name") or key.replace("_", " ").title() or "Required office"
            review = reviews_by_key.get(key)
            if not review:
                missing.append(f"{label} evaluation has not been assigned.")
                continue
            if review.get("status") not in {"Approved", "Completed"}:
                missing.append(f"{label} evaluation must be approved.")
            if office.get("inspection_required"):
                inspections = [
                    item for item in (bundle.get("departmentInspections") or [])
                    if (item.get("department_key") or "") == key and item.get("status") == "Completed"
                ]
                if not inspections:
                    missing.append(f"{label} inspection must be completed.")

        if not required_offices and not (bundle.get("departmentReviews") or []):
            warnings.append("No required department offices are configured for this permit type.")

        if assessment.get("status") not in {"Completed", "For Payment", "Paid"}:
            missing.append("The assessment must be completed and locked.")
        if not (assessment.get("completed_at") or assessment.get("locked_at")):
            missing.append("The assessment record must have a completion timestamp.")

        if not payment:
            missing.append("Treasury payment must be confirmed.")
        elif not payment.get("paid_at"):
            missing.append("Confirmed payment must include the paid date and time.")

        if not (receipt or (payment or {}).get("official_receipt_number")):
            missing.append("An official receipt number is required.")

        info = app.get("business_info") or {}
        for label, value in {
            "Owner name": self.app_owner_name(info),
            "Business name": self.app_business_name(info),
            "Business address": self.app_business_address(info),
        }.items():
            if not value or value == "-":
                missing.append(f"{label} is required for the official permit.")

        release_date = manila_now().date()
        settings = self.active_permit_issuance_settings(config, release_date)
        if not settings:
            missing.append("Active permit issuance settings are not configured.")

        if current_permit.get("status") == "Released":
            missing.append("This application already has a released permit. Use the reissue workflow for corrections.")

        return {
            "eligible": not missing,
            "missingRequirements": missing,
            "warnings": warnings,
            "settingsConfigured": bool(settings),
        }

    def source_permit_snapshot(self, bundle, payment, receipt, release_date):
        app = bundle.get("application") or {}
        info = app.get("business_info") or {}
        permit_snapshot = app.get("permit_snapshot") or {}
        classification = bundle.get("classification") or {}
        validity = calendar_permit_validity(release_date)
        receipt_number = (receipt or {}).get("receipt_number") or (payment or {}).get("official_receipt_number") or ""
        payment_date = (payment or {}).get("paid_at") or (receipt or {}).get("issued_at") or ""
        payment_amount = (payment or {}).get("amount_paid") or (bundle.get("assessment") or {}).get("grand_total") or 0
        return {
            "application_id": app.get("id"),
            "applicant_id": app.get("applicant_id"),
            "owner_name": self.app_owner_name(info),
            "business_name": self.app_business_name(info),
            "business_classification": classification.get("name") or info.get("business_classification") or "",
            "business_address": self.app_business_address(info),
            "permit_type": permit_snapshot.get("permitName") or permit_snapshot.get("permit_name") or "Business Permit",
            "release_date": validity["issued_date"],
            "expiration_date": validity["valid_until"],
            "permit_year": validity["permit_year"],
            "renewal_year": validity["renewal_year"],
            "official_receipt_number": receipt_number,
            "payment_date_time": payment_date,
            "payment_amount": str(payment_amount),
            "sp_number": (bundle.get("assessment") or {}).get("assessment_number") or "",
            "application_type": app.get("application_type") or "new",
        }

    def permit_document_data_from_permit(self, permit):
        snapshot = permit.get("snapshot_data") or {}
        return {
            "permit_number": permit.get("permit_number") or snapshot.get("permit_number"),
            "owner_name": permit.get("owner_name") or snapshot.get("owner_name"),
            "business_name": permit.get("business_name") or snapshot.get("business_name"),
            "business_address": permit.get("business_address") or snapshot.get("business_address"),
            "release_date": permit.get("release_date") or permit.get("issued_date") or permit.get("issue_date") or snapshot.get("release_date"),
            "expiration_date": permit.get("expiration_date") or permit.get("valid_until") or snapshot.get("expiration_date"),
            "official_receipt_number": permit.get("official_receipt_number") or snapshot.get("official_receipt_number"),
            "payment_date_time": permit.get("payment_date") or snapshot.get("payment_date_time"),
            "payment_amount": permit.get("payment_amount") or snapshot.get("payment_amount"),
            "sp_number": permit.get("sp_number") or snapshot.get("sp_number") or permit.get("permit_number"),
            "authorized_official_name": permit.get("authorized_official_name") or snapshot.get("authorized_official_name"),
            "authorized_official_position": permit.get("authorized_official_position") or snapshot.get("authorized_official_position"),
            "qr_verification_url": permit.get("qr_verification_url") or snapshot.get("qr_verification_url"),
        }

    def get_admin_permit_eligibility(self, application_id):
        config = self.admin_config_with_actor("permit generation eligibility")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return
            self.send_json({"eligibility": self.permit_generation_eligibility(config, bundle)})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to check permit eligibility.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to check permit eligibility."}, status=500)

    def finalize_admin_application(self, application_id):
        config = self.admin_config_with_actor("application finalization")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return
            eligibility = self.permit_generation_eligibility(config, bundle)
            if not eligibility["eligible"]:
                self.send_json(
                    {
                        "error": "This application is not ready for official permit generation.",
                        "eligibility": eligibility,
                    },
                    status=400,
                )
                return
            if (bundle.get("businessPermit") or {}).get("status") in {"Generated", "Ready for Release"}:
                permit = bundle.get("businessPermit")
                self.send_json(
                    {
                        "message": "Official business permit is already generated.",
                        "permit": permit,
                        "previewUrl": f"/admin/staff-administrator/applications/{application_id}/permit-preview",
                    }
                )
                return

            issue_date = manila_now().date()
            validity = calendar_permit_validity(issue_date)
            payment = self.confirmed_payment_for_permit(bundle)
            receipt = self.official_receipt_for_payment(bundle, payment)
            qr_token = secrets.token_urlsafe(32)
            qr_url = f"{self.public_permit_base_url()}/verify/permit/{qr_token}"
            snapshot = self.source_permit_snapshot(bundle, payment, receipt, issue_date)
            snapshot["qr_token"] = qr_token
            snapshot["qr_verification_url"] = qr_url
            snapshot["authorized_official_name"] = (self.active_permit_issuance_settings(config, issue_date) or {}).get("authorized_official_name")
            snapshot["authorized_official_position"] = (self.active_permit_issuance_settings(config, issue_date) or {}).get("authorized_official_position")

            rows = self.service_rest_request(
                config,
                "rpc/reserve_official_business_permit",
                method="POST",
                payload={
                    "p_application_id": application_id,
                    "p_assessment_id": (bundle.get("assessment") or {}).get("id"),
                    "p_payment_id": (payment or {}).get("id"),
                    "p_official_receipt_id": (receipt or {}).get("id"),
                    "p_actor_id": config["actor"].get("id"),
                    "p_permit_year": validity["permit_year"],
                    "p_release_date": validity["issued_date"],
                    "p_expiration_date": validity["valid_until"],
                    "p_qr_token": qr_token,
                    "p_qr_verification_url": qr_url,
                    "p_snapshot_data": snapshot,
                    "p_reissue_reason": None,
                },
            ) or []
            permit = rows[0] if rows else {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "official_permit_generated",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"permitNumber": permit.get("permit_number"), **validity, "applicationId": application_id},
            )
            self.send_json(
                {
                    "message": "Official business permit generated. Review the preview before release.",
                    "permit": permit,
                    "eligibility": eligibility,
                    "previewUrl": f"/admin/staff-administrator/applications/{application_id}/permit-preview",
                }
            )
        except ValueError:
            self.send_json({"error": "Unable to prepare the official business permit document."}, status=500)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to generate the official business permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to generate the official business permit."}, status=500)

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
                self.send_json({"error": "Generate the official business permit before release."}, status=400)
                return
            if permit.get("status") == "Released":
                self.send_json({"message": "Business permit has already been released.", "permit": permit})
                return
            release_date = manila_now().date()
            validity = calendar_permit_validity(release_date)
            snapshot = {
                **(permit.get("snapshot_data") or {}),
                "release_date": validity["issued_date"],
                "expiration_date": validity["valid_until"],
            }
            pdf_data = self.permit_document_data_from_permit({**permit, "snapshot_data": snapshot, "release_date": validity["issued_date"], "expiration_date": validity["valid_until"]})
            pdf_bytes = render_permit_pdf(pdf_data)
            pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
            storage_path = permit_storage_path(permit.get("permit_number") or "business-permit", permit.get("version_number") or 1)
            self.upload_storage_file(
                config["supabase_url"],
                config["supabase_service_key"],
                "business-permits",
                storage_path,
                pdf_bytes,
                "application/pdf",
            )
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "official_permit_pdf_uploaded",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"permitNumber": permit.get("permit_number"), "storagePath": storage_path, "sha256": pdf_hash},
            )

            released_permits = self.service_rest_request(
                config,
                "rpc/finalize_official_business_permit_release",
                method="POST",
                payload={
                    "p_permit_id": permit.get("id"),
                    "p_actor_id": config["actor"].get("id"),
                    "p_release_date": validity["issued_date"],
                    "p_expiration_date": validity["valid_until"],
                    "p_pdf_storage_path": storage_path,
                    "p_pdf_sha256": pdf_hash,
                    "p_snapshot_data": snapshot,
                },
            ) or []
            permit = released_permits[0] if released_permits else {**permit, "status": "Released"}
            app = bundle["application"]
            now = utc_now_iso()
            if (app.get("application_type") or "new") == "renewal" and app.get("source_permit_id"):
                self.service_rest_request(
                    config,
                    "business_permits",
                    method="PATCH",
                    payload={"renewal_status": "renewed", "renewed_at": now, "updated_at": now},
                    query=urlencode({"id": f"eq.{app.get('source_permit_id')}"}),
                    prefer="return=minimal",
                )
                self.create_service_audit_log(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    "renewed_permit_released",
                    actor=config["actor"],
                    entity_type="business_permit",
                    entity_id=app.get("source_permit_id"),
                    details={"renewalApplicationId": application_id, "newPermitId": permit.get("id"), "permitNumber": permit.get("permit_number")},
                )
            try:
                self.process_daily_renewals(config, only_permit_id=permit.get("id"))
            except Exception:
                pass
            self.send_json({"message": "Official business permit released and applicant notified for pickup.", "permit": permit})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to release the business permit.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to release the business permit."}, status=500)

    def get_admin_business_permit_preview(self, application_id):
        config = self.admin_config_with_actor("business permit preview")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return
            permit = bundle.get("businessPermit")
            eligibility = self.permit_generation_eligibility(config, bundle)
            if not permit:
                self.send_json({"permit": None, "eligibility": eligibility, "svg": ""})
                return
            svg = render_permit_svg(self.permit_document_data_from_permit(permit))
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "official_permit_previewed",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"permitNumber": permit.get("permit_number"), "applicationId": application_id},
            )
            self.send_json({"permit": permit, "eligibility": eligibility, "svg": svg})
        except (ValueError, HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            status = error.code if isinstance(error, HTTPError) else 500
            message = self.handle_rest_error(error, "Unable to load permit preview.") if isinstance(error, HTTPError) else str(error)
            self.send_json({"error": message or "Unable to load permit preview."}, status=status)

    def download_admin_business_permit_pdf(self, application_id):
        config = self.admin_config_with_actor("business permit PDF download")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            permit = (bundle or {}).get("businessPermit")
            if not permit:
                self.send_json({"error": "Business permit has not been generated."}, status=404)
                return
            if permit.get("status") == "Released" and permit.get("permit_file_url"):
                pdf_bytes = self.download_storage_file(config["supabase_url"], config["supabase_service_key"], "business-permits", permit.get("permit_file_url"))
            else:
                pdf_bytes = render_permit_pdf(self.permit_document_data_from_permit(permit))
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "official_permit_downloaded",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"permitNumber": permit.get("permit_number"), "applicationId": application_id},
            )
            self.send_file_bytes(pdf_bytes, f"{permit.get('permit_number') or 'business-permit'}.pdf", "application/pdf", "attachment")
        except (ValueError, HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            status = error.code if isinstance(error, HTTPError) else 500
            message = self.handle_rest_error(error, "Unable to download permit PDF.") if isinstance(error, HTTPError) else str(error)
            self.send_json({"error": message or "Unable to download permit PDF."}, status=status)

    def record_admin_business_permit_print(self, application_id):
        config = self.admin_config_with_actor("business permit print audit")
        if not config:
            return
        try:
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            permit = (bundle or {}).get("businessPermit") or {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "official_permit_printed",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"permitNumber": permit.get("permit_number"), "applicationId": application_id},
            )
            self.send_json({"message": "Permit print event recorded."})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            status = error.code if isinstance(error, HTTPError) else 500
            message = self.handle_rest_error(error, "Unable to record print event.") if isinstance(error, HTTPError) else str(error)
            self.send_json({"error": message or "Unable to record print event."}, status=status)

    def reissue_admin_business_permit(self, application_id):
        config = self.admin_config_with_actor("business permit reissue")
        if not config:
            return
        try:
            payload = self.read_json_body()
            reason = (payload.get("reason") or payload.get("remarks") or "").strip()
            if not reason:
                self.send_json({"error": "A reissue reason is required."}, status=400)
                return
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            if not bundle:
                self.send_json({"error": "Application not found."}, status=404)
                return
            current = bundle.get("businessPermit") or {}
            if current.get("status") != "Released":
                self.send_json({"error": "Only a released current permit can be reissued."}, status=400)
                return
            eligibility = self.permit_generation_eligibility(config, bundle)
            eligibility["missingRequirements"] = [
                item for item in eligibility.get("missingRequirements", [])
                if "already has a released permit" not in item
            ]
            eligibility["eligible"] = not eligibility["missingRequirements"]
            if not eligibility["eligible"]:
                self.send_json({"error": "This permit cannot be reissued until source records are complete.", "eligibility": eligibility}, status=400)
                return

            release_date = manila_now().date()
            validity = calendar_permit_validity(release_date)
            payment = self.confirmed_payment_for_permit(bundle)
            receipt = self.official_receipt_for_payment(bundle, payment)
            qr_token = secrets.token_urlsafe(32)
            qr_url = f"{self.public_permit_base_url()}/verify/permit/{qr_token}"
            settings = self.active_permit_issuance_settings(config, release_date) or {}
            snapshot = self.source_permit_snapshot(bundle, payment, receipt, release_date)
            snapshot.update(
                {
                    "qr_token": qr_token,
                    "qr_verification_url": qr_url,
                    "authorized_official_name": settings.get("authorized_official_name"),
                    "authorized_official_position": settings.get("authorized_official_position"),
                    "reissue_reason": reason,
                    "previous_permit_id": current.get("id"),
                    "previous_permit_number": current.get("permit_number"),
                }
            )
            rows = self.service_rest_request(
                config,
                "rpc/reserve_official_business_permit",
                method="POST",
                payload={
                    "p_application_id": application_id,
                    "p_assessment_id": (bundle.get("assessment") or {}).get("id"),
                    "p_payment_id": (payment or {}).get("id"),
                    "p_official_receipt_id": (receipt or {}).get("id"),
                    "p_actor_id": config["actor"].get("id"),
                    "p_permit_year": validity["permit_year"],
                    "p_release_date": validity["issued_date"],
                    "p_expiration_date": validity["valid_until"],
                    "p_qr_token": qr_token,
                    "p_qr_verification_url": qr_url,
                    "p_snapshot_data": snapshot,
                    "p_reissue_reason": reason,
                },
            ) or []
            permit = rows[0] if rows else {}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "official_permit_reissued",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"previousPermitId": current.get("id"), "reason": reason, "permitNumber": permit.get("permit_number")},
            )
            self.send_json(
                {
                    "message": "Replacement permit generated. Review and release the new version.",
                    "permit": permit,
                    "previewUrl": f"/admin/staff-administrator/applications/{application_id}/permit-preview",
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            status = error.code if isinstance(error, HTTPError) else 500
            message = self.handle_rest_error(error, "Unable to reissue permit.") if isinstance(error, HTTPError) else str(error)
            self.send_json({"error": message or "Unable to reissue permit."}, status=status)

    def revoke_admin_business_permit(self, application_id):
        config = self.admin_config_with_actor("business permit revocation")
        if not config:
            return
        try:
            payload = self.read_json_body()
            reason = (payload.get("reason") or payload.get("remarks") or "").strip()
            if not reason:
                self.send_json({"error": "A revocation reason is required."}, status=400)
                return
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            permit = (bundle or {}).get("businessPermit") or {}
            if not permit:
                self.send_json({"error": "Business permit not found."}, status=404)
                return
            if permit.get("status") != "Released":
                self.send_json({"error": "Only a released permit can be revoked."}, status=400)
                return
            now = utc_now_iso()
            rows = self.service_rest_request(
                config,
                "business_permits",
                method="PATCH",
                payload={
                    "status": "Revoked",
                    "revoked_at": now,
                    "revoked_by": config["actor"].get("id"),
                    "revocation_reason": reason,
                    "updated_at": now,
                },
                query=urlencode({"id": f"eq.{permit.get('id')}"}),
                prefer="return=representation",
            ) or []
            self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={"status": "Permit Revoked", "progress": "Permit Revoked", "updated_at": now},
                query=urlencode({"id": f"eq.{application_id}"}),
            )
            revoked = rows[0] if rows else {**permit, "status": "Revoked", "revocation_reason": reason}
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "official_permit_revoked",
                actor=config["actor"],
                entity_type="business_permit",
                entity_id=permit.get("id"),
                details={"permitNumber": permit.get("permit_number"), "reason": reason},
            )
            self.send_json({"message": "Business permit revoked.", "permit": revoked})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            status = error.code if isinstance(error, HTTPError) else 500
            message = self.handle_rest_error(error, "Unable to revoke permit.") if isinstance(error, HTTPError) else str(error)
            self.send_json({"error": message or "Unable to revoke permit."}, status=status)

    def verify_public_business_permit(self, token):
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not supabase_url or not service_key:
            self.send_json({"error": "Permit verification is not configured."}, status=500)
            return
        token = (token or "").strip()
        if not token:
            self.send_json({"error": "Verification token is required."}, status=400)
            return
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "business_permits",
                {
                    "select": "permit_number,business_name,owner_name,status,release_date,expiration_date,valid_until,qr_token,version_number,is_current_version,revoked_at,revocation_reason,superseded_at",
                    "qr_token": f"eq.{token}",
                    "limit": 1,
                },
            ) or []
            if not rows:
                self.send_json({"valid": False, "error": "Permit verification record was not found."}, status=404)
                return
            permit = rows[0]
            expiry = permit.get("expiration_date") or permit.get("valid_until")
            status = permit.get("status") or "Unknown"
            if status == "Released" and expiry and str(expiry)[:10] < manila_now().date().isoformat():
                status = "Expired"
            self.send_json(
                {
                    "valid": permit.get("status") == "Released" and permit.get("is_current_version") and status != "Expired",
                    "permit": {
                        "permitNumber": permit.get("permit_number"),
                        "businessName": permit.get("business_name"),
                        "ownerName": permit.get("owner_name"),
                        "status": status,
                        "releaseDate": permit.get("release_date"),
                        "expirationDate": expiry,
                        "version": permit.get("version_number"),
                        "isCurrentVersion": permit.get("is_current_version"),
                        "revokedAt": permit.get("revoked_at"),
                        "revocationReason": permit.get("revocation_reason"),
                    },
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            status = error.code if isinstance(error, HTTPError) else 500
            message = self.handle_rest_error(error, "Unable to verify permit.") if isinstance(error, HTTPError) else str(error)
            self.send_json({"error": message or "Unable to verify permit."}, status=status)

