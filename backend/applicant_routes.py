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
from .renewal_service import renewal_window
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
    APPLICANT_DRAFT_STATUSES = {"Draft", "For Revision"}
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

    def normalize_applicant_record_status(self, *values):
        for value in values:
            status = (value or "").strip()
            if status:
                aliases = {
                    "Assessment Finalized": "For Payment",
                    "Payment Verified": "Paid",
                    "Permit Ready for Release": "Ready for Release",
                    "Ready for Pickup": "Ready for Release",
                    "Permit Released": "Released",
                    "Under Office Evaluation": "Under Department Evaluation",
                }
                return aliases.get(status, status)
        return "Draft"

    def applicant_application_reference(self, application):
        return (
            application.get("application_reference_number")
            or application.get("reference_number")
            or application.get("reference_no")
            or (f"APP-{str(application.get('id') or '')[:8].upper()}" if application.get("id") else "")
        )

    def format_applicant_owned_permit(self, application, business_permit=None, renewal_application=None, renewal_assessment=None, renewal_window_data=None):
        business_permit = business_permit or {}
        info = application.get("business_info") or {}
        snapshot = application.get("permit_snapshot") or {}
        app_status = self.normalize_applicant_record_status(application.get("status"))
        permit_status = self.normalize_applicant_record_status(business_permit.get("status"), app_status)
        expiration_date = business_permit.get("expiration_date") or business_permit.get("expires_at") or ""
        issued_date = business_permit.get("issued_date") or business_permit.get("issue_date") or ""
        permit_year = business_permit.get("permit_year") or (issued_date[:4] if issued_date else None)
        renewal_year = business_permit.get("renewal_year") or (int(permit_year) + 1 if permit_year else None)
        window = renewal_window_data or {}
        renewal_status = business_permit.get("renewal_status") or "not_open"
        is_released = permit_status == "Released"
        is_ready = permit_status == "Ready for Release"
        return {
            "id": business_permit.get("id") or application.get("id"),
            "applicationId": application.get("id"),
            "permitId": application.get("permit_id"),
            "permitNumber": business_permit.get("permit_number") or business_permit.get("permit_no") or "",
            "applicationReferenceNumber": self.applicant_application_reference(application),
            "permitType": business_permit.get("permit_type") or snapshot.get("permitName") or snapshot.get("permit_name") or "Business Permit",
            "businessName": business_permit.get("business_name") or self.app_business_name(info),
            "businessOwner": business_permit.get("owner_name") or self.app_owner_name(info),
            "applicationType": application.get("application_type") or info.get("application_type") or info.get("applicationType") or "New",
            "dateSubmitted": application.get("submitted_at") or "",
            "dateApproved": application.get("approved_at") or application.get("finalized_at") or business_permit.get("issue_date") or "",
            "validityStartDate": business_permit.get("issue_date") or business_permit.get("validity_start_date") or "",
            "expirationDate": expiration_date,
            "issuedDate": issued_date,
            "permitYear": permit_year,
            "validUntil": business_permit.get("valid_until") or expiration_date,
            "renewalYear": renewal_year,
            "renewalStatus": renewal_status,
            "renewalStartDate": str(window.get("start_date") or ""),
            "renewalDueDate": str(window.get("effective_due_date") or ""),
            "originalRenewalDueDate": str(window.get("original_due_date") or ""),
            "renewalApplicationId": (renewal_application or {}).get("id"),
            "renewalFiledAt": (renewal_application or {}).get("filed_at") or "",
            "renewalIsLate": bool((renewal_application or {}).get("is_late")),
            "officialPayableTotal": (
                (renewal_assessment or {}).get("total_amount")
                if (renewal_assessment or {}).get("status") in {"finalized", "paid"}
                else None
            ),
            "applicationStatus": app_status,
            "permitStatus": "Expired" if self.is_date_in_past(expiration_date) and permit_status == "Released" else permit_status,
            "releaseStatus": "Released" if is_released else ("Ready for Pickup" if is_ready else "Not Ready"),
            "paymentStatus": application.get("payment_status") or ("Paid" if app_status in {"Paid", "For Finalization", "Ready for Release", "Released"} else "Unpaid"),
            "dateReleased": business_permit.get("released_at") or "",
            "createdDate": application.get("created_at") or business_permit.get("created_at") or "",
            "lastUpdatedDate": application.get("updated_at") or business_permit.get("updated_at") or "",
            "canPrint": False,
            "canDownload": False,
            "renewalEligible": self.is_renewal_eligible(expiration_date, permit_status, renewal_status),
        }

    def is_date_in_past(self, value):
        if not value:
            return False
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date() < datetime.now(timezone.utc).date()
        except ValueError:
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").date() < datetime.now(timezone.utc).date()
            except ValueError:
                return False

    def is_renewal_eligible(self, expiration_date, status, renewal_status=None):
        if status not in {"Released", "Expired"}:
            return False
        if renewal_status:
            return renewal_status not in {"not_open", "renewed", "closed"}
        if not expiration_date:
            return status == "Expired"
        try:
            expiry = datetime.fromisoformat(expiration_date.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                expiry = datetime.strptime(expiration_date[:10], "%Y-%m-%d").date()
            except ValueError:
                return False
        days_until_expiry = (expiry - datetime.now().astimezone().date()).days
        return days_until_expiry <= 60

    def require_applicant_role_for_self_service(self, supabase_url, service_key, user):
        profile = self.get_profile_by_auth_user_id(supabase_url, service_key, user.get("id")) or {}
        role = normalize_role(profile.get("role") or (user.get("app_metadata") or {}).get("role"))
        if role != "applicant":
            self.send_json({"error": "This action is only available to applicant accounts."}, status=403)
            return False
        if profile_status(profile.get("status")) != "active":
            self.send_json({"error": "This applicant account is not active."}, status=403)
            return False
        return True

    def list_applicant_owned_permits(self):
        config = self.ensure_applicant_request("permit record listing")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        if not self.require_applicant_role_for_self_service(supabase_url, supabase_service_key, user):
            return
        try:
            applications = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {
                    "select": "id,permit_id,applicant_id,status,progress,payment_status,assessment_status,business_info,permit_snapshot,submitted_at,finalized_at,created_at,updated_at,application_type,permit_year,source_permit_id,renewal_due_date,filed_at,payment_completed_at,is_late",
                    "applicant_id": f"eq.{user.get('id')}",
                    "order": "created_at.desc",
                    "limit": 1000,
                },
            ) or []

            application_ids = [row.get("id") for row in applications if row.get("id")]
            permits_by_application = {}
            if application_ids:
                try:
                    business_permits = self.supabase_rest_request(
                        supabase_url,
                        supabase_service_key,
                        "business_permits",
                        {
                            "select": "*",
                            "application_id": f"in.({','.join(application_ids)})",
                            "order": "created_at.desc",
                        },
                    ) or []
                    permits_by_application = {row.get("application_id"): row for row in business_permits if row.get("application_id")}
                except HTTPError:
                    permits_by_application = {}

            renewal_apps = {
                row.get("source_permit_id"): row
                for row in applications
                if row.get("application_type") == "renewal" and row.get("source_permit_id")
            }
            renewal_app_ids = [row.get("id") for row in renewal_apps.values() if row.get("id")]
            assessments_by_application = {}
            if renewal_app_ids:
                assessment_rows = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "renewal_fee_assessments",
                    {
                        "select": "application_id,total_amount,status",
                        "application_id": f"in.({','.join(renewal_app_ids)})",
                        "status": "neq.voided",
                    },
                ) or []
                assessments_by_application = {row.get("application_id"): row for row in assessment_rows}
            settings_rows = self.supabase_rest_request(
                supabase_url, supabase_service_key, "renewal_settings",
                {"select": "*", "order": "updated_at.desc", "limit": 1},
            ) or []
            settings = settings_rows[0] if settings_rows else {}
            extension_rows = self.supabase_rest_request(
                supabase_url, supabase_service_key, "renewal_deadline_extensions",
                {"select": "*", "is_active": "eq.true", "limit": 100},
            ) or []
            extensions_by_year = {int(row.get("renewal_year")): row for row in extension_rows if row.get("renewal_year")}
            records = []
            for application in applications:
                business_permit = permits_by_application.get(application.get("id"))
                renewal_application = renewal_apps.get((business_permit or {}).get("id"))
                renewal_year = (business_permit or {}).get("renewal_year")
                window = None
                if renewal_year:
                    window = renewal_window(int(renewal_year), settings, extensions_by_year.get(int(renewal_year)))
                records.append(self.format_applicant_owned_permit(
                    application,
                    business_permit,
                    renewal_application,
                    assessments_by_application.get((renewal_application or {}).get("id")),
                    window,
                ))
            self.send_json({"permits": records, "total": len(records)})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load your permits.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load your permits."}, status=500)

    def document_category_from_snapshot(self, snapshot):
        text = " ".join(
            str(snapshot.get(key) or "")
            for key in ("documentName", "document_name", "category", "documentCategory", "notes", "shortDescription")
        ).lower()
        if "renewal" in text:
            return "Renewal documents"
        if any(token in text for token in ("barangay", "dti", "sec", "cda", "registration")):
            return "Business registration documents"
        if any(token in text for token in ("zoning", "fire", "sanitary", "engineering", "department")):
            return "Department requirements"
        if any(token in text for token in ("valid id", "government", "cedula", "photo")):
            return "Personal documents"
        if any(token in text for token in ("permit", "requirement")):
            return "Business permit requirements"
        return "Supporting documents"

    def normalize_document_verification_status(self, value):
        status = (value or "").strip()
        aliases = {
            "Pending": "Pending Review",
            "Uploaded": "Pending Review",
            "Approved": "Verified",
            "Denied": "Rejected",
            "Reupload": "Requires Re-upload",
            "Re-upload": "Requires Re-upload",
        }
        return aliases.get(status, status or "Pending Review")

    def format_applicant_owned_document(self, document, application=None, review=None):
        snapshot = document.get("document_snapshot") or {}
        review = review or {}
        file_name = document.get("file_name") or ""
        file_path = document.get("file_url") or ""
        application = application or {}
        verification_status = self.normalize_document_verification_status(
            review.get("verification_status") or review.get("status") or document.get("verification_status") or document.get("upload_status")
        )
        return {
            "id": document.get("id"),
            "documentId": document.get("id"),
            "applicantId": application.get("applicant_id"),
            "applicationId": document.get("application_id"),
            "permitId": application.get("permit_id"),
            "documentType": snapshot.get("documentName") or snapshot.get("document_name") or document.get("document_type") or "Document",
            "documentCategory": document.get("document_category") or self.document_category_from_snapshot(snapshot),
            "originalFilename": document.get("original_filename") or file_name,
            "storedFilename": Path(file_path).name if file_path else "",
            "storagePath": file_path,
            "fileUrl": f"/attachments/application-documents/{document.get('id')}/view" if file_path else "",
            "downloadUrl": f"/attachments/application-documents/{document.get('id')}/download" if file_path else "",
            "fileFormat": (Path(file_name).suffix or Path(file_path).suffix or "").lstrip(".").upper(),
            "fileSize": document.get("file_size") or document.get("size") or "",
            "uploadDate": document.get("uploaded_at") or "",
            "verificationStatus": verification_status,
            "verifiedBy": review.get("reviewed_by") or review.get("verified_by") or "",
            "verificationDate": review.get("reviewed_at") or review.get("verified_at") or "",
            "rejectionRemarks": review.get("remarks") or document.get("remarks") or "",
            "ocrProcessingStatus": document.get("ocr_status") or "Pending",
            "ocrConfidenceScore": document.get("ocr_confidence_score") or "",
            "documentExpirationDate": document.get("expiration_date") or "",
            "createdDate": document.get("created_at") or "",
            "lastUpdatedDate": document.get("updated_at") or "",
            "applicationReferenceNumber": self.applicant_application_reference(application),
            "businessName": self.app_business_name(application.get("business_info") or {}),
            "acceptedFileTypes": snapshot.get("acceptedFileTypes") or snapshot.get("accepted_file_types") or "pdf,png,jpg,jpeg",
            "maxFileSize": snapshot.get("maxFileSize") or snapshot.get("max_file_size") or "10MB",
            "canReplace": verification_status in {"Rejected", "Requires Re-upload", "Expired"},
        }

    def list_applicant_owned_documents(self):
        config = self.ensure_applicant_request("document listing")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        if not self.require_applicant_role_for_self_service(supabase_url, supabase_service_key, user):
            return
        try:
            applications = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applications",
                {
                    "select": "id,permit_id,applicant_id,business_info,permit_snapshot,created_at",
                    "applicant_id": f"eq.{user.get('id')}",
                    "order": "created_at.desc",
                    "limit": 1000,
                },
            ) or []
            application_by_id = {row.get("id"): row for row in applications if row.get("id")}
            application_ids = list(application_by_id.keys())
            if not application_ids:
                self.send_json({"documents": [], "total": 0, "applications": []})
                return

            documents = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "id,application_id,permit_document_id,document_snapshot,file_name,file_url,upload_status,ocr_status,remarks,uploaded_at,created_at,updated_at",
                    "application_id": f"in.({','.join(application_ids)})",
                    "order": "created_at.desc",
                    "limit": 1000,
                },
            ) or []

            reviews = []
            try:
                reviews = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "application_document_reviews",
                    {
                        "select": "*",
                        "application_id": f"in.({','.join(application_ids)})",
                        "is_deleted": "eq.false",
                        "order": "created_at.desc",
                    },
                ) or []
            except HTTPError:
                reviews = []
            review_by_document = {}
            for review in reviews:
                document_id = review.get("application_document_id") or review.get("document_id")
                if document_id and document_id not in review_by_document:
                    review_by_document[document_id] = review

            formatted = [
                self.format_applicant_owned_document(document, application_by_id.get(document.get("application_id")), review_by_document.get(document.get("id")))
                for document in documents
            ]
            app_options = [
                {
                    "id": app.get("id"),
                    "label": f"{self.applicant_application_reference(app)} - {self.app_business_name(app.get('business_info') or {})}",
                }
                for app in applications
            ]
            self.send_json({"documents": formatted, "total": len(formatted), "applications": app_options})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load your documents.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load your documents."}, status=500)

    def replace_applicant_document(self, document_id):
        config = self.ensure_applicant_request("document replacement")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        if not self.require_applicant_role_for_self_service(supabase_url, supabase_service_key, user):
            return
        try:
            payload = self.read_json_body()
            file_name = (payload.get("fileName") or "").strip()
            file_url = (payload.get("fileUrl") or "").strip()
            if not file_name or not file_url:
                self.send_json({"error": "Replacement file name and storage path are required."}, status=400)
                return

            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "id,application_id,document_snapshot,file_name,file_url,upload_status,applications(id,applicant_id,status,application_type)",
                    "id": f"eq.{document_id}",
                    "limit": 1,
                },
            ) or []
            if not rows:
                self.send_json({"error": "Document not found."}, status=404)
                return
            document = rows[0]
            application = document.get("applications") or {}
            if application.get("applicant_id") != user.get("id"):
                self.send_json({"error": "You are not allowed to update this document."}, status=403)
                return
            if application.get("status") not in self.APPLICANT_DRAFT_STATUSES:
                self.send_json({"error": "Documents are locked while this renewal is being processed."}, status=409)
                return

            duplicate_rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "id",
                    "application_id": f"eq.{document.get('application_id')}",
                    "file_name": f"eq.{file_name}",
                    "id": f"neq.{document_id}",
                    "limit": 1,
                },
            ) or []
            if duplicate_rows:
                self.send_json({"error": "A document with the same filename already exists for this application."}, status=400)
                return

            updated = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {"id": f"eq.{document_id}"},
                method="PATCH",
                payload={
                    "file_name": file_name,
                    "file_url": file_url,
                    "upload_status": "Uploaded",
                    "ocr_status": "Pending",
                    "remarks": None,
                    "uploaded_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                },
                prefer="return=representation",
            ) or []
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "renewal_document_replaced" if application.get("application_type") == "renewal" else "document_replaced",
                actor=user,
                entity_type="application_document",
                entity_id=document_id,
                details={
                    "applicationId": document.get("application_id"),
                    "fileName": file_name,
                    "previousStatus": document.get("upload_status") or "Pending",
                    "newStatus": "Uploaded",
                },
            )
            self.send_json({"message": "Replacement uploaded.", "document": updated[0] if updated else {}})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to replace document.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to replace document."}, status=500)

    def load_optional_applicant_profile(self, supabase_url, service_key, user_id):
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "applicants",
                {"select": "*", "user_id": f"eq.{user_id}", "limit": 1},
            ) or []
            return rows[0] if rows else {}
        except HTTPError:
            return {}

    def format_applicant_profile_settings(self, user, profile=None, applicant=None):
        profile = profile or {}
        applicant = applicant or {}
        def pick(*values):
            for value in values:
                if value is not None and str(value).strip() != "":
                    return str(value).strip()
            return ""

        return {
            "userId": user.get("id"),
            "role": normalize_role(profile.get("role") or (user.get("app_metadata") or {}).get("role")),
            "accountStatus": profile_status(profile.get("status")),
            "verifiedEmail": bool(user.get("email_confirmed_at") or user.get("confirmed_at")),
            # Applicant-facing fields deliberately come from one canonical row.
            # Falling back to auth metadata or profiles can resurrect stale values.
            "firstName": pick(applicant.get("first_name_raw"), applicant.get("first_name")),
            "middleName": pick(applicant.get("middle_name")),
            "lastName": pick(applicant.get("last_name")),
            "suffix": pick(applicant.get("suffix")),
            "email": pick(applicant.get("email")),
            "contactNumber": pick(applicant.get("contact_number")),
            "birthdate": pick(applicant.get("birthdate")),
            "sex": pick(applicant.get("sex")),
            "civilStatus": pick(applicant.get("civil_status")),
            "houseNumber": pick(applicant.get("house_number")),
            "street": pick(applicant.get("address_street")),
            "barangay": pick(applicant.get("address_barangay")),
            "municipalityCity": pick(applicant.get("address_city")),
            "province": pick(applicant.get("address_province")),
            "postalCode": pick(applicant.get("postal_code")),
            "profilePhotoUrl": pick(applicant.get("profile_photo_url")),
            "createdAt": pick(applicant.get("created_at")),
            "updatedAt": pick(applicant.get("updated_at")),
        }

    def get_applicant_profile_settings(self):
        config = self.ensure_applicant_request("profile loading")
        if not config:
            return
        supabase_url, supabase_service_key, user = config
        try:
            profile = self.get_profile_by_auth_user_id(supabase_url, supabase_service_key, user.get("id")) or {}
            if normalize_role(profile.get("role") or (user.get("app_metadata") or {}).get("role")) != "applicant":
                self.send_json({"error": "This profile page is only for applicant accounts."}, status=403)
                return
            applicant = self.load_optional_applicant_profile(supabase_url, supabase_service_key, user.get("id"))
            if not applicant.get("id"):
                self.send_json({"error": "Your applicant profile could not be found."}, status=404)
                return
            self.send_json({"profile": self.format_applicant_profile_settings(user, profile, applicant), "source": "applicants"})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load profile.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load profile."}, status=500)

    def validate_applicant_profile_payload(self, payload, current_profile=None):
        current_profile = current_profile or {}
        editable_fields = {
            "firstName", "middleName", "lastName", "suffix", "email", "contactNumber",
            "birthdate", "sex", "civilStatus", "houseNumber", "street", "barangay",
            "municipalityCity", "province", "postalCode", "profilePhotoUrl",
        }
        read_only_fields = {"userId", "role", "accountStatus", "verifiedEmail", "updatedAt"}
        unexpected = sorted(set(payload) - editable_fields - read_only_fields)
        if unexpected:
            raise ValueError("The profile request contains unsupported fields.")

        merged = {
            key: payload[key] if key in payload else current_profile.get(key, "")
            for key in editable_fields
        }
        required = {
            "firstName": "First name",
            "lastName": "Last name",
            "email": "Email address",
            "contactNumber": "Contact number",
        }
        missing = [label for key, label in required.items() if not str(merged.get(key) or "").strip()]
        if missing:
            raise ValueError(f"Please complete: {', '.join(missing)}.")

        cleaned = {key: str(value or "").strip() for key, value in merged.items()}
        length_limits = {
            "firstName": 80, "middleName": 80, "lastName": 80, "suffix": 20,
            "email": 254, "contactNumber": 20, "houseNumber": 30, "street": 160,
            "barangay": 100, "municipalityCity": 100, "province": 100,
            "postalCode": 10, "profilePhotoUrl": 1000,
        }
        too_long = [key for key, limit in length_limits.items() if len(cleaned.get(key, "")) > limit]
        if too_long:
            raise ValueError("One or more profile fields exceed the allowed length.")

        for key, label in (("firstName", "First name"), ("middleName", "Middle name"), ("lastName", "Last name")):
            value = cleaned.get(key, "")
            if value and not re.fullmatch(r"[^\d<>]{1,80}", value):
                raise ValueError(f"{label} contains unsupported characters.")

        email = cleaned["email"].lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Enter a valid email address.")

        contact = re.sub(r"[\s()-]+", "", cleaned["contactNumber"])
        if not re.fullmatch(r"(\+639|09)\d{9}", contact):
            raise ValueError("Enter a valid Philippine mobile number, for example 09XXXXXXXXX or +639XXXXXXXXX.")

        postal_code = cleaned.get("postalCode", "")
        if postal_code and not re.fullmatch(r"\d{4}", postal_code):
            raise ValueError("Postal code must contain exactly four digits.")

        birthdate = cleaned.get("birthdate", "")
        if birthdate:
            try:
                parsed_birthdate = datetime.strptime(birthdate, "%Y-%m-%d").date()
            except ValueError as error:
                raise ValueError("Enter a valid birthdate.") from error
            if parsed_birthdate >= datetime.now(timezone.utc).date():
                raise ValueError("Birthdate must be earlier than today.")

        sex = cleaned.get("sex", "")
        if sex and sex not in {"Female", "Male", "Other"}:
            raise ValueError("Select a valid sex value.")
        civil_status = cleaned.get("civilStatus", "")
        if civil_status and civil_status not in {"Single", "Married", "Widowed", "Separated"}:
            raise ValueError("Select a valid civil status.")

        return {
            "firstName": cleaned["firstName"],
            "middleName": cleaned["middleName"],
            "lastName": cleaned["lastName"],
            "suffix": cleaned["suffix"],
            "email": email,
            "contactNumber": contact,
            "birthdate": birthdate,
            "sex": sex,
            "civilStatus": civil_status,
            "houseNumber": cleaned["houseNumber"],
            "street": cleaned["street"],
            "barangay": cleaned["barangay"],
            "municipalityCity": cleaned["municipalityCity"],
            "province": cleaned["province"],
            "postalCode": postal_code,
            "profilePhotoUrl": cleaned["profilePhotoUrl"],
        }

    def update_applicant_profile_settings(self):
        config = self.ensure_applicant_request("profile update")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            request_payload = self.read_json_body()
            profile = self.get_profile_by_auth_user_id(supabase_url, supabase_service_key, user.get("id")) or {}
            if normalize_role(profile.get("role") or (user.get("app_metadata") or {}).get("role")) != "applicant":
                self.send_json({"error": "You are not authorized to update this profile."}, status=403)
                return
            if not profile.get("id"):
                self.send_json({"error": "Your applicant profile could not be found."}, status=404)
                return

            existing = self.load_optional_applicant_profile(supabase_url, supabase_service_key, user.get("id"))
            if not existing.get("id"):
                self.send_json({"error": "Your applicant profile could not be found."}, status=404)
                return

            current_settings = self.format_applicant_profile_settings(user, profile, existing)
            request_version = str(request_payload.get("updatedAt") or "").strip()
            current_version = str(current_settings.get("updatedAt") or "").strip()
            if request_version and current_version and request_version != current_version:
                self.send_json(
                    {"error": "Your profile was updated elsewhere. Refresh the latest information before saving again."},
                    status=409,
                )
                return

            payload = self.validate_applicant_profile_payload(request_payload, current_settings)
            changed_fields = [
                key for key, value in payload.items()
                if str(value or "").strip() != str(current_settings.get(key) or "").strip()
            ]
            if not changed_fields:
                self.send_json(
                    {
                        "success": True,
                        "message": "Your profile information is already up to date.",
                        "changedFields": [],
                        "emailVerificationRequired": False,
                        "profile": current_settings,
                        "source": "applicants",
                    }
                )
                return

            current_email = (current_settings.get("email") or user.get("email") or "").lower()
            if payload["email"] != current_email:
                duplicate = self.get_profile_by_email(supabase_url, supabase_service_key, payload["email"])
                if duplicate and duplicate.get("auth_user_id") != user.get("id"):
                    self.send_json({"error": "That email address is already used by another account."}, status=409)
                    return

            applicant_payload = {
                "first_name": payload["firstName"],
                "first_name_raw": payload["firstName"],
                "middle_name": payload["middleName"],
                "last_name": payload["lastName"],
                "suffix": payload["suffix"],
                "email": payload["email"],
                "contact_number": payload["contactNumber"],
                "birthdate": payload["birthdate"] or None,
                "sex": payload["sex"] or None,
                "civil_status": payload["civilStatus"] or None,
                "house_number": payload["houseNumber"] or None,
                "address_street": payload["street"] or None,
                "address_barangay": payload["barangay"] or None,
                "address_city": payload["municipalityCity"] or None,
                "address_province": payload["province"] or None,
                "postal_code": payload["postalCode"] or None,
                "profile_photo_url": payload["profilePhotoUrl"] or None,
                "updated_at": utc_now_iso(),
            }

            previous_applicant_payload = {
                "first_name": existing.get("first_name"),
                "first_name_raw": existing.get("first_name_raw"),
                "middle_name": existing.get("middle_name"),
                "last_name": existing.get("last_name"),
                "suffix": existing.get("suffix"),
                "email": existing.get("email"),
                "contact_number": existing.get("contact_number"),
                "birthdate": existing.get("birthdate"),
                "sex": existing.get("sex"),
                "civil_status": existing.get("civil_status"),
                "house_number": existing.get("house_number"),
                "address_street": existing.get("address_street"),
                "address_barangay": existing.get("address_barangay"),
                "address_city": existing.get("address_city"),
                "address_province": existing.get("address_province"),
                "postal_code": existing.get("postal_code"),
                "profile_photo_url": existing.get("profile_photo_url"),
                "updated_at": existing.get("updated_at"),
            }

            updated_applicants = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "applicants",
                {"id": f"eq.{existing.get('id')}", "user_id": f"eq.{user.get('id')}"},
                method="PATCH",
                payload=applicant_payload,
                prefer="return=representation",
            ) or []
            if len(updated_applicants) != 1:
                self.send_json({"error": "Your profile changes could not be saved. Please try again."}, status=500)
                return

            profile_payload = {
                "first_name": payload["firstName"],
                "middle_name": payload["middleName"],
                "last_name": payload["lastName"],
                "suffix": payload["suffix"],
                "email": payload["email"],
                "contact_number": payload["contactNumber"],
            }

            try:
                updated_profile = self.update_profile_record(
                    supabase_url,
                    supabase_service_key,
                    profile.get("id"),
                    profile_payload,
                )
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "applicants",
                    {"id": f"eq.{existing.get('id')}", "user_id": f"eq.{user.get('id')}"},
                    method="PATCH",
                    payload=previous_applicant_payload,
                    prefer="return=minimal",
                )
                raise

            if not updated_profile:
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "applicants",
                    {"id": f"eq.{existing.get('id')}", "user_id": f"eq.{user.get('id')}"},
                    method="PATCH",
                    payload=previous_applicant_payload,
                    prefer="return=minimal",
                )
                self.send_json({"error": "Your profile changes could not be saved. Please try again."}, status=500)
                return

            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                "APPLICANT_PROFILE_UPDATED",
                actor=user,
                entity_type="applicant_profile",
                entity_id=existing.get("id"),
                details={
                    "changedFields": changed_fields,
                    "emailChanged": payload["email"] != current_email,
                    "userRole": "applicant",
                },
            )
            if payload["email"] != current_email:
                self.create_notification(
                    supabase_url,
                    supabase_service_key,
                    user.get("id"),
                    "Email Verification Required",
                    "Your email address was changed in your profile. Please verify the new email address before using it for account recovery.",
                    notification_type="profile",
                    source_role="System",
                )

            refreshed_applicant = updated_applicants[0]
            self.send_json(
                {
                    "success": True,
                    "message": "Your profile information has been updated successfully.",
                    "changedFields": changed_fields,
                    "emailVerificationRequired": payload["email"] != current_email,
                    "profile": self.format_applicant_profile_settings(user, updated_profile, refreshed_applicant),
                    "source": "applicants",
                }
            )
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except HTTPError as error:
            print("[profile] applicant update failed", json.dumps({"status": error.code, "userId": user.get("id")}))
            self.send_json({"error": "Your profile changes could not be saved. Please try again."}, status=409 if error.code == 409 else 500)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            print("[profile] applicant update unavailable", json.dumps({"errorType": type(error).__name__, "userId": user.get("id")}))
            self.send_json({"error": "Your profile changes could not be saved. Please try again."}, status=503)

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

    def get_application_print_data(self, application_id):
        config = self.ensure_authenticated_request()
        if not config:
            return

        supabase_url, service_key, user = config
        try:
            profile = self.get_profile_by_auth_user_id(supabase_url, service_key, user.get("id")) or {}
            role = normalize_role(profile.get("role") or (user.get("app_metadata") or {}).get("role") or "applicant")
            if profile and profile_status(profile.get("status")) != "active":
                self.send_json({"error": "You are not authorized to print this application."}, status=403)
                return

            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "applications",
                {"select": "*", "id": f"eq.{application_id}", "limit": 1},
            ) or []
            if not rows:
                self.send_json({"error": "The application form could not be found."}, status=404)
                return

            application = rows[0]
            is_owner = application.get("applicant_id") == user.get("id")
            is_authorized_staff = role in {"super_admin", "bplo_admin"}
            if not is_owner and not is_authorized_staff:
                self.send_json({"error": "You are not authorized to print this application."}, status=403)
                return

            business_info = application.get("business_info") or {}
            permit_snapshot = application.get("permit_snapshot") or {}
            application_date = (
                business_info.get("date_of_application")
                or business_info.get("application_date")
                or application.get("created_at")
                or ""
            )
            reference_number = (
                application.get("application_reference_number")
                or application.get("reference_number")
                or application.get("reference_no")
                or application.get("renewal_application_number")
                or ""
            )
            permit_year = application.get("permit_year") or (str(application_date)[:4] if application_date else "")
            applicant_profile = self.load_optional_applicant_profile(supabase_url, service_key, application.get("applicant_id"))

            if self.headers.get("X-Print-Audit", "1") != "0":
                self.create_service_audit_log(
                    supabase_url,
                    service_key,
                    "APPLICATION_FORM_PRINTED",
                    actor=user,
                    entity_type="application",
                    entity_id=application_id,
                    details={
                        "applicationStatus": application.get("status") or "Draft",
                        "userRole": role,
                        "printSession": self.headers.get("X-Print-Session") or "",
                    },
                )
            self.send_json({
                "application": {
                    "status": application.get("status") or "Draft",
                    "progress": application.get("progress") or "Draft",
                    "applicationType": application.get("application_type") or business_info.get("application_type") or "new",
                    "referenceNumber": reference_number,
                    "applicationYear": permit_year,
                    "createdAt": application.get("created_at") or "",
                    "updatedAt": application.get("updated_at") or "",
                    "submittedAt": application.get("submitted_at") or "",
                    "approvedAt": application.get("approved_at") or application.get("finalized_at") or "",
                    "permitName": permit_snapshot.get("permitName") or permit_snapshot.get("permit_name") or "Business Permit",
                    "permitCode": permit_snapshot.get("permitCode") or permit_snapshot.get("permit_code") or "BPLO 01",
                    "businessInfo": business_info,
                },
                "applicantProfile": {
                    "citizenship": applicant_profile.get("citizenship") or "",
                    "civilStatus": applicant_profile.get("civil_status") or "",
                    "municipalityCity": applicant_profile.get("address_city") or applicant_profile.get("city") or "",
                    "province": applicant_profile.get("address_province") or applicant_profile.get("province") or "",
                    "postalCode": applicant_profile.get("postal_code") or "",
                },
                "lgu": {
                    "name": os.getenv("LGU_NAME", "Municipality of Victoria"),
                    "province": os.getenv("LGU_PROVINCE", "Province of Laguna"),
                    "officeName": os.getenv("LICENSING_OFFICE_NAME", "Business Permits and Licensing Office"),
                },
                "viewerRole": role,
            })
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "The latest application data could not be retrieved.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "The latest application data could not be retrieved."}, status=500)

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
                select="id,permit_id,status,progress,business_info,permit_snapshot,created_at,updated_at,submitted_at,application_type,permit_year,source_permit_id,previous_permit_id,previous_application_id,renewal_application_number,renewal_due_date,original_renewal_due_date,effective_renewal_due_date,renewal_baseline",
            )
            if not application:
                self.send_json({"error": "Draft application not found."}, status=404)
                return
            can_edit = application.get("status") in self.APPLICANT_DRAFT_STATUSES
            if not can_edit and application.get("application_type") != "renewal":
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
            renewal_changes = []
            if application.get("application_type") == "renewal":
                renewal_changes = self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "renewal_change_logs",
                    {
                        "select": "*",
                        "renewal_application_id": f"eq.{application_id}",
                        "order": "changed_at.desc",
                    },
                ) or []

            self.send_json(
                {
                    "draft": self.format_applicant_application_summary(application),
                    "canEdit": can_edit,
                    "businessInfo": application.get("business_info") or {},
                    "documents": [self.format_applicant_document_summary(document) for document in documents],
                    "renewal": {
                        "isRenewal": application.get("application_type") == "renewal",
                        "renewalYear": application.get("permit_year"),
                        "renewalApplicationNumber": application.get("renewal_application_number"),
                        "previousPermitId": application.get("source_permit_id") or application.get("previous_permit_id"),
                        "previousApplicationId": application.get("previous_application_id"),
                        "dueDate": application.get("effective_renewal_due_date") or application.get("renewal_due_date"),
                        "baseline": application.get("renewal_baseline") or {},
                        "changes": renewal_changes,
                    },
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
                select="id,status,business_info,application_type,renewal_baseline",
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
            renewal_changes = self.track_renewal_change_logs(
                {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
                application,
                merged_info,
                user,
            )
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
                    "renewalChanges": renewal_changes,
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
                    "select": "id,user_id,application_id,title,message,type,source_role,is_read,created_at,read_at,related_permit_id,action_url",
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
            issue_date = (payload.get("issueDate") or "").strip() or None
            expiration_date = (payload.get("expirationDate") or "").strip() or None
            document_year = payload.get("documentYear") or None
            mime_type = (payload.get("mimeType") or "").strip() or None
            file_size = payload.get("fileSize") or None

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
                {"select": "id,permit_id,status,application_type", "id": f"eq.{application_id}", "applicant_id": f"eq.{user.get('id')}", "limit": 1},
            )
            if not owned:
                self.send_json({"error": "Application not found."}, status=404)
                return
            application = owned[0]
            if application.get("status") not in self.APPLICANT_DRAFT_STATUSES:
                self.send_json({"error": "Documents are locked while this renewal is being processed."}, status=409)
                return

            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {
                    "select": "id,upload_status",
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
                    "original_filename": file_name or None,
                    "stored_filename": file_url.rsplit("/", 1)[-1] if file_url else None,
                    "file_url": file_url or None,
                    "mime_type": mime_type,
                    "file_size": file_size,
                    "document_year": document_year,
                    "issue_date": issue_date,
                    "expiration_date": expiration_date,
                    "removed_at": utc_now_iso() if upload_status == "Removed" else None,
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
            self.create_service_audit_log(
                supabase_url,
                supabase_service_key,
                (
                    "renewal_document_uploaded" if upload_status == "Uploaded" else "renewal_document_deleted"
                ) if application.get("application_type") == "renewal" else (
                    "document_uploaded" if upload_status == "Uploaded" else "document_deleted"
                ),
                actor=user,
                entity_type="application_document",
                entity_id=(updated[0] if updated else rows[0]).get("id"),
                details={
                    "applicationId": application_id,
                    "previousStatus": rows[0].get("upload_status") or "Pending",
                    "newStatus": upload_status,
                    "fileName": file_name,
                    "applicationType": application.get("application_type"),
                },
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
            structured_result = self.build_structured_ocr_result(raw_text, document_type)
            detected_document_type = structured_result.get("document_type") or document_type or "Unknown Document"
            structured_fields = structured_result.get("structured_fields") or {}
            extracted_fields = structured_result.get("flat_fields") or {}
            if not extracted_fields and detected_document_type != "Unknown Document":
                extracted_fields = self.extract_business_fields_from_text(raw_text, detected_document_type)
            confidence_score = structured_result.get("confidence_score") or extracted_fields.get("confidence_score") or 0
            ocr_status = "Completed" if raw_text else "Failed"
            error_message = "" if raw_text else "No readable text was found. Please upload a clearer document."

            self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "application_documents",
                {"id": f"eq.{application_document_id}"},
                method="PATCH",
                payload={
                    "ocr_status": ocr_status,
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
                "document_type": detected_document_type,
                "raw_text": raw_text,
                "extracted_fields": extracted_fields,
                "confidence_score": confidence_score,
                "parser_version": structured_result.get("parser_version", "structured_ocr_v2"),
                "ocr_status": ocr_status,
                "error_message": error_message,
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
            ocr_record = ocr_rows[0] if ocr_rows else {}
            structured_ocr_record = self.create_structured_ocr_result_record(
                supabase_url,
                supabase_service_key,
                application_id,
                application_document_id,
                permit_document_id,
                detected_document_type,
                raw_text,
                structured_fields,
                confidence_score,
                ocr_record.get("id"),
                user.get("id"),
            )
            self.create_notification(
                supabase_url,
                supabase_service_key,
                user.get("id"),
                "OCR Review Required",
                f"{file_name or 'Your document'} was read as {detected_document_type}. Please review the extracted fields before using them in your application.",
                notification_type="document",
                source_role="System",
                application_id=application_id,
            )

            self.send_json(
                {
                    "success": True,
                    "message": "OCR completed. Please review extracted values.",
                    "ocr": ocr_record,
                    "ocrResult": structured_ocr_record,
                    "ocrResultId": (structured_ocr_record or {}).get("id") or ocr_record.get("id"),
                    "documentType": detected_document_type,
                    "detectedDocumentType": detected_document_type,
                    "structuredFields": structured_fields,
                    "warnings": structured_result.get("warnings") or [],
                    "extracted_fields": extracted_fields,
                    "extractedFields": extracted_fields,
                }
            )

        except Exception as error:
            self.send_json({"error": str(error) or "Unable to process OCR."}, status=500)

    def create_structured_ocr_result_record(self, supabase_url, service_key, application_id, document_id, permit_document_id, document_type, raw_text, structured_fields, confidence_score, legacy_ocr_result_id=None, user_id=None):
        payload = {
            "application_id": application_id,
            "document_id": document_id,
            "permit_document_id": permit_document_id,
            "legacy_ocr_result_id": legacy_ocr_result_id,
            "document_type": document_type,
            "extracted_text": raw_text,
            "extracted_fields_json": structured_fields,
            "confidence_score": confidence_score,
            "created_by": user_id,
        }
        try:
            rows = self.supabase_rest_request(
                supabase_url,
                service_key,
                "ocr_results",
                method="POST",
                payload=payload,
                prefer="return=representation",
            )
            return rows[0] if rows else {}
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return {}

    def update_applicant_ocr_corrections(self, ocr_result_id):
        config = self.ensure_applicant_request("OCR correction")
        if not config:
            return

        supabase_url, supabase_service_key, user = config
        try:
            payload = self.read_json_body()
            corrections = payload.get("corrections") or {}
            if not isinstance(corrections, dict):
                self.send_json({"error": "Corrections must be an object."}, status=400)
                return

            rows = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "ocr_results",
                {
                    "select": "id,application_id,document_id,legacy_ocr_result_id,extracted_fields_json",
                    "id": f"eq.{ocr_result_id}",
                    "limit": 1,
                },
            ) or []
            if not rows:
                self.send_json({"error": "OCR result not found."}, status=404)
                return
            result = rows[0]

            application = self.load_owned_applicant_application(
                supabase_url,
                supabase_service_key,
                user.get("id"),
                result.get("application_id"),
                select="id,status",
            )
            if not application:
                self.send_json({"error": "OCR result not found for this applicant."}, status=404)
                return

            fields = result.get("extracted_fields_json") or {}
            now = utc_now_iso()
            for field_name, corrected_value in corrections.items():
                if field_name not in fields or not isinstance(fields.get(field_name), dict):
                    continue
                corrected_value = self.clean_extracted_value(corrected_value) or ""
                fields[field_name]["corrected_value"] = corrected_value
                fields[field_name]["value"] = corrected_value or fields[field_name].get("value") or ""
                fields[field_name]["corrected"] = bool(corrected_value)
                fields[field_name]["correction_status"] = "corrected" if corrected_value else "unchanged"
                fields[field_name]["corrected_by"] = user.get("id")
                fields[field_name]["corrected_at"] = now
                fields[field_name]["validation_status"] = "valid" if corrected_value else fields[field_name].get("validation_status", "needs_review")
                fields[field_name]["validation_issue"] = "" if corrected_value else fields[field_name].get("validation_issue", "")

            flat_fields = self.flatten_structured_ocr_fields(fields)
            updated = self.supabase_rest_request(
                supabase_url,
                supabase_service_key,
                "ocr_results",
                {"id": f"eq.{ocr_result_id}"},
                method="PATCH",
                payload={
                    "extracted_fields_json": fields,
                    "correction_status": "accepted",
                    "corrected_by": user.get("id"),
                    "corrected_at": now,
                },
                prefer="return=representation",
            ) or []

            document_id = result.get("document_id")
            if document_id:
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "application_documents",
                    {"id": f"eq.{document_id}"},
                    method="PATCH",
                    payload={"ocr_extracted_fields": flat_fields, "ocr_status": "Completed"},
                    prefer="return=minimal",
                )
            if result.get("legacy_ocr_result_id"):
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "application_ocr_results",
                    {"id": f"eq.{result.get('legacy_ocr_result_id')}"},
                    method="PATCH",
                    payload={"extracted_fields": flat_fields, "updated_at": now},
                    prefer="return=minimal",
                )

            self.send_json(
                {
                    "message": "OCR corrections saved.",
                    "ocrResult": updated[0] if updated else result,
                    "structuredFields": fields,
                    "extractedFields": flat_fields,
                    "extracted_fields": flat_fields,
                }
            )
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to save OCR corrections.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to save OCR corrections."}, status=500)

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
                    "select": "id,permit_id,applicant_id,status,application_type,permit_year,source_permit_id,renewal_due_date,original_renewal_due_date,effective_renewal_due_date,renewal_baseline",
                    "id": f"eq.{application_id}",
                    "applicant_id": f"eq.{user.get('id')}",
                    "limit": 1,
                },
            )
            if not application_rows:
                self.send_json({"error": "Application not found."}, status=404)
                return

            application = application_rows[0]
            if application.get("status") not in self.APPLICANT_DRAFT_STATUSES:
                self.send_json({"error": "This application is locked and cannot be submitted from its current status."}, status=409)
                return
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
                upload_required = snapshot.get("uploadRequired")
                if upload_required is None:
                    upload_required = snapshot.get("upload_required", True)

                if upload_required is not False:
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

            renewal_change_confirmed = bool(payload.get("renewalChangeConfirmed") or payload.get("renewal_change_confirmed"))
            renewal_changes = []
            if application.get("application_type") == "renewal":
                renewal_changes = self.track_renewal_change_logs(
                    {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
                    application,
                    business_info,
                    user,
                )
                if renewal_changes and not renewal_change_confirmed:
                    self.send_json({
                        "error": "Please confirm the listed changes before submitting your renewal.",
                        "renewalChanges": renewal_changes,
                    }, status=400)
                    return

            submitted_at = utc_now_iso()
            renewal_fields = self.renewal_submission_fields(
                {"supabase_url": supabase_url, "supabase_service_key": supabase_service_key},
                application,
            )
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
                    "renewal_change_confirmed_at": submitted_at if renewal_changes else None,
                    **renewal_fields,
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
                    "applicationType": application.get("application_type") or "new",
                    "filedAt": renewal_fields.get("filed_at"),
                    "isLate": renewal_fields.get("is_late"),
                    "originalDueDate": renewal_fields.get("original_renewal_due_date"),
                    "effectiveDueDate": renewal_fields.get("effective_renewal_due_date"),
                },
            )
            if application.get("application_type") == "renewal" and application.get("source_permit_id"):
                if renewal_changes:
                    self.supabase_rest_request(
                        supabase_url,
                        supabase_service_key,
                        "renewal_change_logs",
                        {"renewal_application_id": f"eq.{application_id}"},
                        method="PATCH",
                        payload={"confirmed_at": submitted_at},
                        prefer="return=minimal",
                    )
                self.supabase_rest_request(
                    supabase_url,
                    supabase_service_key,
                    "business_permits",
                    {"id": f"eq.{application.get('source_permit_id')}"},
                    method="PATCH",
                    payload={"renewal_status": "submitted", "updated_at": submitted_at},
                    prefer="return=minimal",
                )
                self.create_service_audit_log(
                    supabase_url,
                    supabase_service_key,
                    "renewal_filing_recorded",
                    actor=user,
                    entity_type="application",
                    entity_id=application_id,
                    details={
                        "filedAt": renewal_fields.get("filed_at"),
                        "isLate": renewal_fields.get("is_late"),
                        "timezone": "Asia/Manila",
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

