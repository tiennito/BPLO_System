from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo
import json

from .utils import normalize_role, profile_status, utc_now_iso


try:
    MANILA_TZ = ZoneInfo("Asia/Manila")
except Exception:
    MANILA_TZ = timezone(timedelta(hours=8), name="Asia/Manila")
MONEY_QUANTUM = Decimal("0.01")
RATE_QUANTUM = Decimal("0.00001")
RENEWAL_STATUSES = {
    "not_open", "upcoming", "open", "draft", "submitted", "under_review",
    "for_payment", "paid", "renewed", "late", "closed",
}
INTEREST_MONTH_RULES = {
    "anniversary_cycle", "calendar_month", "completed_month",
    "manual_treasury_confirmation",
}
REUSE_POLICIES = {
    "remains_valid", "reupload_every_year", "reupload_when_expired",
    "updated_copy_required", "not_required_for_renewal",
}
DEFAULT_RENEWAL_SETTINGS = {
    "renewal_start_month": 1,
    "renewal_start_day": 1,
    "renewal_due_month": 1,
    "renewal_due_day": 20,
    "surcharge_rate": "0.25000",
    "monthly_interest_rate": "0.02000",
    "maximum_interest_months": 36,
    "interest_month_rule": "anniversary_cycle",
    "penalties_enabled": True,
}
RENEWAL_IMPORTANT_FIELDS = {
    "business_name": "Business name",
    "owner_name": "Owner name",
    "ownership_type": "Ownership type",
    "business_address": "Business address",
    "business_classification": "Business classification",
    "nature_of_business": "Nature of business",
    "line_of_business": "Line of business",
    "business_line": "Line of business",
    "business_area": "Business area",
    "employees_total": "Number of employees",
    "number_of_employees": "Number of employees",
    "capitalization": "Capitalization",
    "capital_investment": "Capitalization",
}
RENEWAL_EDITABLE_APPLICATION_STATUSES = {"Draft", "For Revision"}


def renewal_display_status(value):
    normalized = str(value or "Draft").strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "draft": "Draft",
        "for renewal": "For Renewal",
        "submitted": "Submitted",
        "under review": "Under Review",
        "under office evaluation": "Under Review",
        "under department evaluation": "Under Review",
        "for revision": "For Revision",
        "assessment finalized": "For Payment",
        "for payment": "For Payment",
        "payment verified": "Approved",
        "paid": "Approved",
        "finalized": "Approved",
        "approved": "Approved",
        "permit ready for release": "Ready for Release",
        "ready for pickup": "Ready for Release",
        "ready for release": "Ready for Release",
        "permit released": "Completed",
        "released": "Completed",
        "completed": "Completed",
    }
    return aliases.get(normalized, str(value or "Draft").strip().title())


def renewal_status_message(status):
    return {
        "Draft": "Your renewal application has not yet been completed.",
        "For Renewal": "Your permit is eligible for renewal for the upcoming calendar year.",
        "Submitted": "Your renewal application has been submitted and is waiting for review.",
        "Under Review": "Your renewal application is currently being evaluated.",
        "For Revision": "Your renewal application needs changes before it can proceed.",
        "For Payment": "Your renewal assessment is ready for payment.",
        "Approved": "Your renewal application has received final approval.",
        "Ready for Release": "Your renewed permit is ready for release.",
        "Completed": "Your business permit renewal has been completed.",
    }.get(status, "Check the latest status of your business permit renewal.")


def renewal_action_label(status):
    return {
        "Draft": "Continue Renewal",
        "For Revision": "Continue Renewal",
        "For Payment": "View Payment Details",
        "Ready for Release": "View Release Details",
        "Completed": "View Renewal Record",
    }.get(status, "View Renewal")


def manila_now(clock=None):
    value = clock or datetime.now(MANILA_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=MANILA_TZ)
    return value.astimezone(MANILA_TZ)


def parse_date(value):
    if isinstance(value, datetime):
        return manila_now(value).date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("A valid date is required.")
    return date.fromisoformat(text[:10])


def parse_datetime(value):
    if isinstance(value, datetime):
        return manila_now(value)
    text = str(value or "").strip()
    if not text:
        raise ValueError("A valid date and time is required.")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return manila_now(parsed)


def calendar_permit_validity(issued_at):
    issued = parse_date(issued_at)
    permit_year = issued.year
    return {
        "issued_date": issued.isoformat(),
        "permit_year": permit_year,
        "valid_until": date(permit_year, 12, 31).isoformat(),
        "renewal_year": permit_year + 1,
    }


def renewal_window(renewal_year, settings=None, extension=None):
    settings = {**DEFAULT_RENEWAL_SETTINGS, **(settings or {})}
    start = date(
        int(renewal_year),
        int(settings["renewal_start_month"]),
        int(settings["renewal_start_day"]),
    )
    original_due = date(
        int(renewal_year),
        int(settings["renewal_due_month"]),
        int(settings["renewal_due_day"]),
    )
    effective_due = original_due
    if extension and extension.get("is_active", True):
        extension_due = parse_date(extension.get("extended_due_date"))
        if extension_due >= original_due:
            effective_due = extension_due
    return {
        "start_date": start,
        "original_due_date": original_due,
        "effective_due_date": effective_due,
        "late_start_date": effective_due.fromordinal(effective_due.toordinal() + 1),
    }


def filed_after_deadline(filed_at, effective_due_date):
    filed = parse_datetime(filed_at)
    deadline = datetime.combine(parse_date(effective_due_date), time.max, tzinfo=MANILA_TZ)
    return filed > deadline


def delayed_months(due_date, calculation_date, rule, manual_months=None, maximum=36):
    due = parse_date(due_date)
    calculated = parse_date(calculation_date)
    if calculated <= due:
        return 0
    maximum = max(0, int(maximum))
    rule = str(rule or "").strip()
    if rule == "manual_treasury_confirmation":
        if manual_months is None or str(manual_months).strip() == "":
            raise ValueError("Treasury must confirm the number of delayed months.")
        months = int(manual_months)
        if months < 0:
            raise ValueError("Delayed months cannot be negative.")
    else:
        month_delta = (calculated.year - due.year) * 12 + calculated.month - due.month
        if rule == "anniversary_cycle":
            months = month_delta + (1 if calculated.day > due.day else 0)
        elif rule == "calendar_month":
            months = month_delta + 1
        elif rule == "completed_month":
            months = month_delta - (1 if calculated.day < due.day else 0)
        else:
            raise ValueError("Unsupported delayed-month rule.")
    return min(max(0, months), maximum)


def decimal_value(value, field_name="amount"):
    try:
        parsed = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid {field_name}.") from None
    if parsed < 0:
        raise ValueError(f"{field_name.replace('_', ' ').title()} cannot be negative.")
    return parsed


def money_value(value):
    return decimal_value(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_renewal_fees(
    *,
    base_renewal_fee,
    other_fees=0,
    penalty_base=None,
    is_late=False,
    due_date,
    calculation_date,
    settings=None,
    extension=None,
    manual_months=None,
):
    settings = {**DEFAULT_RENEWAL_SETTINGS, **(settings or {})}
    base_fee = money_value(base_renewal_fee)
    other = money_value(other_fees)
    penalty = money_value(base_fee if penalty_base in (None, "") else penalty_base)
    surcharge_rate = decimal_value(settings["surcharge_rate"], "surcharge_rate").quantize(RATE_QUANTUM)
    interest_rate = decimal_value(settings["monthly_interest_rate"], "monthly_interest_rate").quantize(RATE_QUANTUM)
    penalties_enabled = bool(settings.get("penalties_enabled", True)) and bool(is_late)
    surcharge_suspended = bool((extension or {}).get("surcharge_suspended"))
    interest_suspended = bool((extension or {}).get("interest_suspended"))
    months = 0
    surcharge = Decimal("0.00")
    interest = Decimal("0.00")

    if penalties_enabled:
        months = delayed_months(
            due_date,
            calculation_date,
            settings["interest_month_rule"],
            manual_months=manual_months,
            maximum=settings["maximum_interest_months"],
        )
        if not surcharge_suspended:
            surcharge = (penalty * surcharge_rate).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        if not interest_suspended:
            interest_base = penalty + surcharge
            interest = (interest_base * interest_rate * Decimal(months)).quantize(
                MONEY_QUANTUM,
                rounding=ROUND_HALF_UP,
            )

    total = (base_fee + other + surcharge + interest).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    return {
        "base_renewal_fee": f"{base_fee:.2f}",
        "other_fees": f"{other:.2f}",
        "penalty_base": f"{penalty:.2f}",
        "surcharge_rate": f"{surcharge_rate:.5f}" if penalties_enabled and not surcharge_suspended else "0.00000",
        "surcharge_amount": f"{surcharge:.2f}",
        "interest_rate": f"{interest_rate:.5f}" if penalties_enabled and not interest_suspended else "0.00000",
        "interest_month_rule": settings["interest_month_rule"],
        "months_delayed": months,
        "maximum_interest_months": int(settings["maximum_interest_months"]),
        "interest_amount": f"{interest:.2f}",
        "total_amount": f"{total:.2f}",
    }


def status_for_permit(permit, application, today, window):
    if application:
        status = str(application.get("status") or "").lower()
        payment = str(application.get("payment_status") or "").lower()
        assessment = str(application.get("assessment_status") or "").lower()
        if status in {"released", "completed"}:
            return "renewed"
        if payment in {"paid", "payment verified"} or status == "paid":
            return "paid"
        if "payment" in status or assessment in {"completed", "finalized", "for payment"}:
            return "for_payment"
        if status == "draft":
            return "draft"
        if status == "submitted":
            return "submitted"
        if any(token in status for token in ("review", "evaluation", "revision")):
            return "under_review"
    if today < date(window["start_date"].year - 1, 12, 1):
        return "not_open"
    if today < window["start_date"]:
        return "upcoming"
    if today <= window["effective_due_date"]:
        return "open"
    return "late"


class RenewalServiceMixin:
    REMINDER_COPY = {
        "advance_december_1": ("Annual Permit Renewal Reminder", "The next annual renewal period is approaching."),
        "second_december_15": ("Second Annual Permit Renewal Reminder", "Please prepare your annual renewal requirements."),
        "expiration_december_31": ("Business Permit Expiration Notice", "Your current business permit expires today."),
        "renewal_open_january_1": ("Annual Renewal Period Is Open", "You may now file your annual business permit renewal."),
        "deadline_january_10": ("Annual Renewal Deadline Reminder", "The regular annual renewal deadline is approaching."),
        "three_days_remaining": ("Three Days Remaining to Renew", "Three days remain in the regular annual renewal period."),
        "last_day": ("Last Day to File on Time", "Today is the last day to file within the regular renewal period."),
        "late_notice": ("Late Annual Renewal Notice", "The regular annual renewal deadline has passed. Applicable surcharge and monthly interest may be added after assessment."),
    }

    def ensure_renewal_role(self, allowed_roles, action_label="renewal management"):
        supabase_url, client_key, service_key, _admin_email = self.get_admin_api_config()
        if not supabase_url or not client_key or not service_key:
            self.send_json({"error": f"{action_label.title()} is not configured."}, status=500)
            return None
        token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            self.send_json({"error": "Please sign in before continuing."}, status=401)
            return None
        try:
            actor = self.get_session_user(token, supabase_url, client_key)
        except HTTPError:
            self.send_json({"error": "Invalid or expired session."}, status=401)
            return None
        profile = self.get_profile_by_auth_user_id(supabase_url, service_key, actor.get("id")) or {}
        role = normalize_role(profile.get("role"))
        if profile_status(profile.get("status")) != "active" or role not in set(allowed_roles):
            self.send_json({"error": "You are not authorized to perform this renewal action."}, status=403)
            return None
        return {
            "supabase_url": supabase_url,
            "supabase_service_key": service_key,
            "actor": actor,
            "profile": profile,
            "role": role,
        }

    def load_renewal_settings(self, config):
        rows = self.service_rest_request(
            config,
            "renewal_settings",
            query=urlencode({"select": "*", "order": "updated_at.desc", "limit": 1}),
        ) or []
        return {**DEFAULT_RENEWAL_SETTINGS, **(rows[0] if rows else {})}

    def load_renewal_extension(self, config, renewal_year):
        rows = self.service_rest_request(
            config,
            "renewal_deadline_extensions",
            query=urlencode({
                "select": "*",
                "renewal_year": f"eq.{int(renewal_year)}",
                "is_active": "eq.true",
                "order": "created_at.desc",
                "limit": 1,
            }),
        ) or []
        return rows[0] if rows else None

    def renewal_window_from_database(self, config, renewal_year):
        settings = self.load_renewal_settings(config)
        extension = self.load_renewal_extension(config, renewal_year)
        return settings, extension, renewal_window(renewal_year, settings, extension)

    def reusable_business_information(self, business_info, source_permit):
        allowed = {
            "business_name", "businessName", "trade_name", "tradeName", "owner_name",
            "first_name", "firstName", "middle_name", "middleName", "last_name", "lastName",
            "suffix", "business_address", "businessAddress", "unit_street", "unitStreet",
            "business_barangay", "businessBarangay", "business_municipality", "businessMunicipality",
            "contact_number", "contactNumber", "email", "business_classification_id",
            "business_classification", "business_classification_parent_category", "line_of_business",
            "business_line", "business_type", "ownership_type", "type_of_business",
            "registration_number", "tin", "business_area", "employees_total", "employees_lgu",
            "business_activity", "nature_of_business", "capitalization", "capital_investment",
            "goods_value", "gross_sales", "business_email", "business_mobile", "business_telephone",
            "owner_contact_number", "home_address", "business_premise", "location_detail",
        }
        copied = {key: value for key, value in (business_info or {}).items() if key in allowed}
        copied.update({
            "application_type": "renewal",
            "previous_permit_number": source_permit.get("permit_number"),
            "previous_permit_year": source_permit.get("permit_year"),
        })
        return copied

    def renewal_baseline(self, business_info, source_permit, source_application):
        reusable = self.reusable_business_information(business_info, source_permit)
        return {
            "businessInfo": reusable,
            "previousPermit": {
                "id": source_permit.get("id"),
                "permitNumber": source_permit.get("permit_number"),
                "permitYear": source_permit.get("permit_year"),
                "issuedDate": source_permit.get("issued_date") or source_permit.get("issue_date"),
                "expirationDate": source_permit.get("valid_until") or source_permit.get("expiration_date"),
                "status": source_permit.get("status"),
            },
            "previousApplication": {
                "id": source_application.get("id"),
                "referenceNumber": (source_application.get("id") or "")[:8],
                "status": source_application.get("status"),
                "submittedAt": source_application.get("submitted_at"),
            },
        }

    def track_renewal_change_logs(self, config, application, merged_info, actor):
        if (application.get("application_type") or "") != "renewal":
            return []
        baseline = application.get("renewal_baseline") or {}
        baseline_info = baseline.get("businessInfo") or {}
        existing_rows = self.service_rest_request(
            config,
            "renewal_change_logs",
            query=urlencode({"select": "*", "renewal_application_id": f"eq.{application.get('id')}"}),
        ) or []
        existing_by_field = {row.get("field_name"): row for row in existing_rows}
        changed = []
        now = utc_now_iso()
        for field, label in RENEWAL_IMPORTANT_FIELDS.items():
            old_value = baseline_info.get(field)
            new_value = merged_info.get(field)
            if str(old_value or "").strip() == str(new_value or "").strip():
                existing = existing_by_field.get(field)
                if existing:
                    self.service_rest_request(
                        config,
                        "renewal_change_logs",
                        method="DELETE",
                        query=urlencode({"id": f"eq.{existing.get('id')}"}),
                        prefer="return=minimal",
                    )
                continue
            payload = {
                "renewal_application_id": application.get("id"),
                "field_name": field,
                "field_label": label,
                "previous_value": "" if old_value is None else str(old_value),
                "new_value": "" if new_value is None else str(new_value),
                "changed_by": actor.get("id"),
                "changed_at": now,
            }
            existing = existing_by_field.get(field)
            if existing:
                rows = self.service_rest_request(
                    config,
                    "renewal_change_logs",
                    method="PATCH",
                    payload=payload,
                    query=urlencode({"id": f"eq.{existing.get('id')}"}),
                    prefer="return=representation",
                ) or []
            else:
                rows = self.service_rest_request(
                    config,
                    "renewal_change_logs",
                    method="POST",
                    payload=payload,
                    prefer="return=representation",
                ) or []
            changed.extend(rows or [payload])
        return changed

    def find_existing_renewal(self, config, source_permit_id, permit_year):
        rows = self.service_rest_request(
            config,
            "applications",
            query=urlencode({
                "select": "*",
                "application_type": "eq.renewal",
                "source_permit_id": f"eq.{source_permit_id}",
                "permit_year": f"eq.{int(permit_year)}",
                "limit": 1,
            }),
        ) or []
        return rows[0] if rows else None

    def create_renewal_documents(self, config, source_application_id, application_id, permit_id, actor):
        requirements = self.service_rest_request(
            config,
            "renewal_requirements",
            query=urlencode({
                "select": "*,permit_documents(*)",
                "permit_id": f"eq.{permit_id}",
                "is_active": "eq.true",
                "order": "updated_at.asc",
            }),
        ) or []
        if not requirements:
            documents = self.service_rest_request(
                config,
                "permit_documents",
                query=urlencode({"select": "*", "permit_id": f"eq.{permit_id}", "order": "created_at.asc"}),
            ) or []
            requirements = [
                {"permit_document_id": item.get("id"), "reuse_policy": "reupload_every_year", "permit_documents": item}
                for item in documents
            ]
        source_documents = self.service_rest_request(
            config,
            "application_documents",
            query=urlencode({"select": "*", "application_id": f"eq.{source_application_id}"}),
        ) or []
        source_by_requirement = {row.get("permit_document_id"): row for row in source_documents}
        today = manila_now().date()
        created = []
        for requirement in requirements:
            policy = requirement.get("reuse_policy") or "reupload_every_year"
            if policy == "not_required_for_renewal":
                continue
            document = requirement.get("permit_documents") or {}
            document_id = requirement.get("permit_document_id") or document.get("id")
            source = source_by_requirement.get(document_id) or {}
            snapshot = {
                **document,
                "requirementName": requirement.get("requirement_name") or document.get("document_name"),
                "description": requirement.get("description") or document.get("short_description") or "",
                "uploadRequired": requirement.get("is_required", document.get("upload_required", True)),
                "acceptedFileTypes": requirement.get("allowed_file_types") or document.get("accepted_file_types") or [],
                "maxFileSize": requirement.get("max_file_size") or document.get("max_file_size"),
                "numberOfCopies": requirement.get("number_of_copies") or 1,
                "validityRequired": bool(requirement.get("validity_required")),
                "renewalReusePolicy": policy,
                "sourceDocumentId": source.get("id"),
                "referenceLabel": "Current Renewal Requirement",
            }
            expiry_raw = (source.get("document_snapshot") or {}).get("expirationDate") or (source.get("document_snapshot") or {}).get("expiration_date")
            source_valid = bool(source.get("file_url"))
            if expiry_raw:
                try:
                    source_valid = source_valid and parse_date(expiry_raw) >= today
                except ValueError:
                    source_valid = False
            reusable = source_valid and (policy == "remains_valid" or policy == "reupload_when_expired")
            payload = {
                "application_id": application_id,
                "permit_document_id": document_id,
                "document_snapshot": snapshot,
                "upload_status": "Uploaded" if reusable else "Pending",
                "source_document_id": source.get("id") or None,
                "renewal_reuse_policy": policy,
                "file_url": source.get("file_url") if reusable else None,
                "file_name": source.get("file_name") if reusable else None,
                "uploaded_at": source.get("uploaded_at") if reusable else None,
                "reused_at": utc_now_iso() if reusable else None,
                "remarks": "Reused from the prior permit after renewal-policy validation." if reusable else None,
            }
            rows = self.service_rest_request(
                config,
                "application_documents",
                method="POST",
                payload=payload,
                prefer="return=representation",
            ) or []
            created.extend(rows)
            if reusable:
                self.create_service_audit_log(
                    config["supabase_url"], config["supabase_service_key"], "renewal_document_reused",
                    actor=actor, entity_type="application_document",
                    entity_id=(rows[0] if rows else {}).get("id"),
                    details={"sourceDocumentId": source.get("id"), "reusePolicy": policy},
                )
        return created

    def latest_approved_permit_for_applicant(self, config, applicant_id):
        applications = self.service_rest_request(
            config,
            "applications",
            query=urlencode({
                "select": "id,permit_id,applicant_id,status,submitted_at,created_at",
                "applicant_id": f"eq.{applicant_id}",
                "order": "created_at.desc",
                "limit": 100,
            }),
        ) or []
        application_ids = [row.get("id") for row in applications if row.get("id")]
        if not application_ids:
            return None
        permits = self.service_rest_request(
            config,
            "business_permits",
            query=urlencode({
                "select": "*",
                "application_id": f"in.({','.join(application_ids)})",
                "status": "in.(Released,Expired)",
                "order": "released_at.desc.nullslast,issued_date.desc.nullslast,issue_date.desc.nullslast",
                "limit": 1,
            }),
        ) or []
        return permits[0] if permits else None

    def start_latest_applicant_renewal(self):
        auth = self.ensure_applicant_request("business permit renewal")
        if not auth:
            return
        supabase_url, service_key, user = auth
        if not self.require_applicant_role_for_self_service(supabase_url, service_key, user):
            return
        config = {"supabase_url": supabase_url, "supabase_service_key": service_key}
        try:
            permit = self.latest_approved_permit_for_applicant(config, user.get("id"))
            if not permit:
                self.send_json({"error": "No approved business permit was found."}, status=404)
                return
            self.create_or_continue_applicant_renewal(permit.get("id"), auth_config=auth)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to start permit renewal.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError, ValueError) as error:
            self.send_json({"error": str(error) or "Unable to start permit renewal."}, status=500)

    def create_or_continue_applicant_renewal(self, permit_id, auth_config=None):
        auth = auth_config or self.ensure_applicant_request("annual permit renewal")
        if not auth:
            return
        supabase_url, service_key, user = auth
        if not self.require_applicant_role_for_self_service(supabase_url, service_key, user):
            return
        config = {"supabase_url": supabase_url, "supabase_service_key": service_key}
        try:
            permits = self.service_rest_request(
                config,
                "business_permits",
                query=urlencode({"select": "*", "id": f"eq.{permit_id}", "limit": 1}),
            ) or []
            if not permits:
                self.send_json({"error": "Business permit not found."}, status=404)
                return
            permit = permits[0]
            source_apps = self.service_rest_request(
                config,
                "applications",
                query=urlencode({"select": "*", "id": f"eq.{permit.get('application_id')}", "limit": 1}),
            ) or []
            source_app = source_apps[0] if source_apps else None
            if not source_app or source_app.get("applicant_id") != user.get("id"):
                self.send_json({"error": "You do not have access to this business permit."}, status=403)
                return
            if permit.get("status") not in {"Released", "Expired"}:
                self.send_json({"error": "Only released or expired permits can be renewed."}, status=400)
                return
            validity = calendar_permit_validity(
                permit.get("issued_date") or permit.get("issue_date") or permit.get("released_at") or permit.get("valid_until")
            )
            renewal_year = int(permit.get("renewal_year") or validity["renewal_year"])
            existing = self.find_existing_renewal(config, permit_id, renewal_year)
            if existing:
                self.create_service_audit_log(
                    supabase_url, service_key, "existing_renewal_reopened", actor=user,
                    entity_type="application", entity_id=existing.get("id"),
                    details={"sourcePermitId": permit_id, "permitYear": renewal_year},
                )
                self.send_json({
                    "message": f"You already have a renewal application for permit year {renewal_year}. Continue your existing application.",
                    "application": existing,
                    "reusedDraft": True,
                    "nextUrl": f"/applicant/business-information?applicationId={existing.get('id')}",
                })
                return
            settings, extension, window = self.renewal_window_from_database(config, renewal_year)
            if manila_now().date() < date(renewal_year - 1, 12, 1):
                self.send_json({"error": f"Renewal for permit year {renewal_year} opens for preparation on December 1, {renewal_year - 1}."}, status=400)
                return
            payload = {
                "permit_id": source_app.get("permit_id"),
                "applicant_id": user.get("id"),
                "application_type": "renewal",
                "permit_year": renewal_year,
                "source_permit_id": permit_id,
                "previous_permit_id": permit_id,
                "previous_application_id": source_app.get("id"),
                "renewal_application_number": self.generate_workflow_number("REN"),
                "renewal_due_date": window["effective_due_date"].isoformat(),
                "original_renewal_due_date": window["original_due_date"].isoformat(),
                "effective_renewal_due_date": window["effective_due_date"].isoformat(),
                "status": "Draft",
                "progress": "Draft",
                "business_info": self.reusable_business_information(source_app.get("business_info") or {}, permit),
                "renewal_baseline": self.renewal_baseline(source_app.get("business_info") or {}, permit, source_app),
                "business_classification_id": source_app.get("business_classification_id"),
                "permit_snapshot": {
                    **(source_app.get("permit_snapshot") or {}),
                    "applicationType": "renewal",
                    "sourcePermitId": permit_id,
                    "previousPermitNumber": permit.get("permit_number"),
                    "previousPermitYear": permit.get("permit_year") or validity["permit_year"],
                    "renewalYear": renewal_year,
                },
            }
            try:
                rows = self.service_rest_request(
                    config, "applications", method="POST", payload=payload,
                    prefer="return=representation",
                ) or []
            except HTTPError as error:
                if error.code != 409:
                    raise
                rows = []
            application = rows[0] if rows else self.find_existing_renewal(config, permit_id, renewal_year)
            if not application:
                self.send_json({"error": "Unable to create the renewal application."}, status=500)
                return
            if rows:
                self.create_renewal_documents(
                    config, source_app.get("id"), application.get("id"), source_app.get("permit_id"), user,
                )
                self.service_rest_request(
                    config, "business_permits", method="PATCH",
                    payload={"renewal_status": "draft", "updated_at": utc_now_iso()},
                    query=urlencode({"id": f"eq.{permit_id}"}),
                )
                self.create_service_audit_log(
                    supabase_url, service_key, "renewal_draft_created", actor=user,
                    entity_type="application", entity_id=application.get("id"),
                    details={
                        "sourcePermitId": permit_id,
                        "permitYear": renewal_year,
                        "originalDueDate": window["original_due_date"].isoformat(),
                        "effectiveDueDate": window["effective_due_date"].isoformat(),
                        "deadlineExtensionId": (extension or {}).get("id"),
                    },
                )
                self.create_service_audit_log(
                    supabase_url, service_key, "previous_renewal_data_copied", actor=user,
                    entity_type="application", entity_id=application.get("id"),
                    details={"previousApplicationId": source_app.get("id"), "previousPermitId": permit_id},
                )
                self.create_notification(
                    supabase_url, service_key, user.get("id"),
                    "Renewal Draft Created",
                    f"Your renewal draft for permit {permit.get('permit_number') or ''} has been created.",
                    notification_type="renewal",
                    source_role="System",
                    application_id=application.get("id"),
                    related_permit_id=permit_id,
                    action_url=f"/applicant/business-information?applicationId={application.get('id')}",
                )
            self.send_json({
                "message": "Renewal application draft created." if rows else "Your renewal draft has been restored.",
                "application": application,
                "reusedDraft": not bool(rows),
                "nextUrl": f"/applicant/business-information?applicationId={application.get('id')}",
            }, status=201 if rows else 200)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError, ValueError) as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to start permit renewal.") if isinstance(error, HTTPError) else str(error)}, status=error.code if isinstance(error, HTTPError) else 500)

    def renewal_submission_fields(self, config, application, filed_at=None):
        if application.get("application_type") != "renewal":
            return {}
        renewal_year = int(application.get("permit_year"))
        _settings, extension, window = self.renewal_window_from_database(config, renewal_year)
        filed = manila_now(filed_at)
        late = filed_after_deadline(filed, window["effective_due_date"])
        return {
            "filed_at": filed.isoformat(),
            "is_late": late,
            "renewal_due_date": window["effective_due_date"].isoformat(),
            "original_renewal_due_date": window["original_due_date"].isoformat(),
            "effective_renewal_due_date": window["effective_due_date"].isoformat(),
            "deadline_extension_id": (extension or {}).get("id"),
        }

    def load_owned_renewal_application(self, config, application_id, applicant_id=None):
        query = {
            "select": "*",
            "id": f"eq.{application_id}",
            "application_type": "eq.renewal",
            "limit": 1,
        }
        if applicant_id:
            query["applicant_id"] = f"eq.{applicant_id}"
        rows = self.service_rest_request(config, "applications", query=urlencode(query)) or []
        return rows[0] if rows else None

    def format_renewal_dashboard_summary(self, application, previous_permit):
        application = application or {}
        previous_permit = previous_permit or {}
        business_info = application.get("business_info") or {}
        baseline_permit = ((application.get("renewal_baseline") or {}).get("previousPermit") or {})
        raw_status = application.get("status") or "For Renewal"
        status = renewal_display_status(raw_status)
        permit_year = previous_permit.get("permit_year") or baseline_permit.get("permitYear")
        if not permit_year:
            issued_at = previous_permit.get("issued_date") or previous_permit.get("issue_date") or baseline_permit.get("issuedDate") or ""
            permit_year = issued_at[:4] if issued_at else None
        renewal_year = application.get("permit_year") or previous_permit.get("renewal_year")
        return {
            "hasRenewal": bool(application.get("id")),
            "eligible": True,
            "renewalId": application.get("id"),
            "businessId": application.get("business_classification_id"),
            "sourcePermitId": application.get("source_permit_id") or application.get("previous_permit_id") or previous_permit.get("id"),
            "businessName": business_info.get("business_name") or business_info.get("businessName") or previous_permit.get("business_name") or "Business Permit",
            "previousPermitNumber": previous_permit.get("permit_number") or baseline_permit.get("permitNumber") or "",
            "permitYear": permit_year,
            "renewalYear": renewal_year,
            "status": status,
            "rawStatus": raw_status,
            "lastUpdatedAt": application.get("updated_at") or previous_permit.get("updated_at") or application.get("created_at") or "",
            "message": renewal_status_message(status),
            "actionLabel": "Start Renewal" if not application.get("id") else renewal_action_label(status),
            "canEdit": status in RENEWAL_EDITABLE_APPLICATION_STATUSES,
        }

    def get_applicant_renewal_dashboard_summary(self):
        auth = self.ensure_applicant_request("renewal dashboard summary")
        if not auth:
            return
        supabase_url, service_key, user = auth
        if not self.require_applicant_role_for_self_service(supabase_url, service_key, user):
            return
        config = {"supabase_url": supabase_url, "supabase_service_key": service_key}
        try:
            rows = self.service_rest_request(
                config,
                "applications",
                query=urlencode({
                    "select": "id,permit_id,applicant_id,status,progress,payment_status,assessment_status,business_info,business_classification_id,permit_snapshot,permit_year,source_permit_id,previous_permit_id,previous_application_id,renewal_application_number,renewal_due_date,filed_at,submitted_at,finalized_at,created_at,updated_at,renewal_baseline,application_type",
                    "applicant_id": f"eq.{user.get('id')}",
                    "application_type": "eq.renewal",
                    "order": "permit_year.desc.nullslast,updated_at.desc.nullslast,created_at.desc",
                    "limit": 1,
                }),
            ) or []
            application = rows[0] if rows else None
            permit = None
            if application:
                source_permit_id = application.get("source_permit_id") or application.get("previous_permit_id")
                permits = self.service_rest_request(
                    config,
                    "business_permits",
                    query=urlencode({"select": "*", "id": f"eq.{source_permit_id}", "limit": 1}),
                ) or []
                permit = permits[0] if permits else None
            else:
                permit = self.latest_approved_permit_for_applicant(config, user.get("id"))
                if permit:
                    expiration = permit.get("expiration_date") or permit.get("valid_until") or ""
                    if not self.is_renewal_eligible(expiration, permit.get("status") or "", permit.get("renewal_status")):
                        permit = None

            if not application and not permit:
                self.send_json({"hasRenewal": False, "eligible": False})
                return
            self.send_json(self.format_renewal_dashboard_summary(application, permit))
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load renewal information.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError, ValueError) as error:
            self.send_json({"error": str(error) or "Unable to load renewal information."}, status=500)

    def renewal_requirement_status(self, document, review):
        document = document or {}
        review = review or {}
        upload_status = str(document.get("upload_status") or "Pending")
        if not document.get("file_url") or upload_status in {"Pending", "Removed"}:
            upload_label = "Not Uploaded"
        elif upload_status == "Rejected":
            upload_label = "Rejected"
        else:
            upload_label = "Uploaded"
        review_status = str(review.get("status") or "")
        verification_label = {
            "Verified": "Approved",
            "Rejected": "Rejected",
            "For Revision": "Requires Replacement",
            "Under Review": "Under Review",
            "Resubmitted": "Under Review",
            "Pending": "Pending",
        }.get(review_status, "Not Reviewed" if upload_label == "Uploaded" else "Not Available")
        return upload_label, verification_label

    def build_applicant_renewal_details(self, config, application):
        application_id = application.get("id")
        source_permit_id = application.get("source_permit_id") or application.get("previous_permit_id")
        permits = self.service_rest_request(
            config,
            "business_permits",
            query=urlencode({"select": "*", "id": f"eq.{source_permit_id}", "limit": 1}),
        ) or []
        previous_permit = permits[0] if permits else {}
        documents = self.service_rest_request(
            config,
            "application_documents",
            query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "order": "created_at.asc"}),
        ) or []
        reviews = self.service_rest_request(
            config,
            "application_document_reviews",
            query=urlencode({
                "select": "id,document_id,status,remarks,reviewed_at,created_at",
                "application_id": f"eq.{application_id}",
                "is_deleted": "eq.false",
                "order": "created_at.desc",
            }),
        ) or []
        latest_review_by_document = {}
        for review in reviews:
            latest_review_by_document.setdefault(review.get("document_id"), review)
        document_by_requirement = {row.get("permit_document_id"): row for row in documents}

        requirement_query = {
            "select": "*,permit_documents(*)",
            "permit_id": f"eq.{application.get('permit_id')}",
            "is_active": "eq.true",
            "deleted_at": "is.null",
            "order": "display_order.asc,updated_at.desc",
        }
        configured = self.service_rest_request(
            config, "renewal_requirements", query=urlencode(requirement_query),
        ) or []
        classification_id = application.get("business_classification_id")
        configured = [
            item for item in configured
            if not item.get("business_classification_id") or item.get("business_classification_id") == classification_id
        ]
        if not configured:
            configured = [
                {
                    "permit_document_id": row.get("permit_document_id"),
                    "permit_documents": row.get("document_snapshot") or {},
                    "requirement_name": (row.get("document_snapshot") or {}).get("requirementName"),
                    "description": (row.get("document_snapshot") or {}).get("description"),
                    "is_required": (row.get("document_snapshot") or {}).get("uploadRequired", True),
                }
                for row in documents
            ]

        requirements = []
        for requirement in configured:
            permit_document = requirement.get("permit_documents") or {}
            permit_document_id = requirement.get("permit_document_id") or permit_document.get("id")
            document = document_by_requirement.get(permit_document_id) or {}
            review = latest_review_by_document.get(document.get("id")) or {}
            upload_status, verification_status = self.renewal_requirement_status(document, review)
            requirements.append({
                "id": requirement.get("id") or document.get("id"),
                "permitDocumentId": permit_document_id,
                "name": requirement.get("requirement_name") or permit_document.get("document_name") or permit_document.get("documentName") or "Renewal requirement",
                "description": requirement.get("description") or permit_document.get("short_description") or permit_document.get("shortDescription") or "",
                "required": requirement.get("is_required", permit_document.get("upload_required", True)),
                "uploadStatus": upload_status,
                "verificationStatus": verification_status,
                "adminRemarks": review.get("remarks") or document.get("reviewer_remarks") or document.get("remarks") or "",
                "fileName": document.get("file_name") or "",
            })

        revision_rows = self.service_rest_request(
            config,
            "application_status_history",
            query=urlencode({
                "select": "status,remarks,created_at",
                "application_id": f"eq.{application_id}",
                "status": "eq.For Revision",
                "order": "created_at.desc",
                "limit": 1,
            }),
        ) or []
        progress = self.build_applicant_progress(config, application)
        departments = progress.get("departments") or []
        in_progress_departments = [item.get("departmentName") for item in departments if item.get("state") in {"In Progress", "Pending", "For Revision"}]
        status = renewal_display_status(application.get("status"))
        responsible_office = ", ".join(filter(None, in_progress_departments))
        if not responsible_office:
            responsible_office = {
                "Draft": "Applicant",
                "Submitted": "BPLO",
                "Under Review": "BPLO / Assigned Department",
                "For Revision": "Applicant",
                "For Payment": "Municipal Treasury",
                "Approved": "BPLO",
                "Ready for Release": "BPLO Releasing",
                "Completed": "Completed",
            }.get(status, "BPLO")

        business_info = application.get("business_info") or {}
        previous_issue = previous_permit.get("issued_date") or previous_permit.get("issue_date") or ""
        previous_expiry = previous_permit.get("expiration_date") or previous_permit.get("valid_until") or ""
        return {
            **self.format_renewal_dashboard_summary(application, previous_permit),
            "previousPermit": {
                "id": previous_permit.get("id"),
                "permitNumber": previous_permit.get("permit_number") or "",
                "businessName": previous_permit.get("business_name") or business_info.get("business_name") or "",
                "ownerName": previous_permit.get("owner_name") or self.app_owner_name(business_info),
                "businessAddress": previous_permit.get("business_address") or business_info.get("business_address") or "",
                "permitType": previous_permit.get("permit_type") or ((application.get("permit_snapshot") or {}).get("permitName")) or "Business Permit",
                "dateIssued": previous_issue,
                "expirationDate": previous_expiry,
                "status": previous_permit.get("status") or "",
                "canView": False,
                "canDownload": False,
            },
            "requirements": requirements,
            "progress": {
                **progress,
                "startedAt": application.get("created_at") or "",
                "lastUpdatedAt": application.get("updated_at") or "",
                "submittedAt": application.get("submitted_at") or "",
                "responsibleOffice": responsible_office,
                "revisionRemarks": (revision_rows[0] if revision_rows else {}).get("remarks") or "",
                "paymentStatus": application.get("payment_status") or "Unpaid",
                "releaseStatus": "Completed" if status == "Completed" else ("Ready for Release" if status == "Ready for Release" else "Not Ready"),
            },
        }

    def get_applicant_renewal_details(self, application_id):
        auth = self.ensure_applicant_request("renewal detail viewing")
        if not auth:
            return
        supabase_url, service_key, user = auth
        if not self.require_applicant_role_for_self_service(supabase_url, service_key, user):
            return
        config = {"supabase_url": supabase_url, "supabase_service_key": service_key, "actor": user}
        try:
            application = self.load_owned_renewal_application(config, application_id, user.get("id"))
            if not application:
                self.send_json({"error": "Renewal application not found."}, status=404)
                return
            details = self.build_applicant_renewal_details(config, application)
            self.create_service_audit_log(
                supabase_url, service_key, "renewal_details_opened", actor=user,
                entity_type="application", entity_id=application_id,
                details={"previousStatus": application.get("status"), "newStatus": application.get("status")},
            )
            self.send_json(details)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load your renewal details.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError, ValueError) as error:
            self.send_json({"error": str(error) or "Unable to load your renewal details. Please refresh the page or try again."}, status=500)

    def continue_applicant_renewal(self, application_id):
        auth = self.ensure_applicant_request("renewal continuation")
        if not auth:
            return
        supabase_url, service_key, user = auth
        if not self.require_applicant_role_for_self_service(supabase_url, service_key, user):
            return
        config = {"supabase_url": supabase_url, "supabase_service_key": service_key}
        try:
            application = self.load_owned_renewal_application(config, application_id, user.get("id"))
            if not application:
                self.send_json({"error": "Renewal application not found."}, status=404)
                return
            status = renewal_display_status(application.get("status"))
            can_edit = status in RENEWAL_EDITABLE_APPLICATION_STATUSES
            self.create_service_audit_log(
                supabase_url, service_key,
                "renewal_draft_continued" if can_edit else "renewal_record_viewed",
                actor=user, entity_type="application", entity_id=application_id,
                details={"previousStatus": application.get("status"), "newStatus": application.get("status")},
            )
            self.send_json({
                "renewalId": application_id,
                "canEdit": can_edit,
                "actionLabel": renewal_action_label(status),
                "nextUrl": f"/applicant/business-information?applicationId={application_id}",
            })
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to continue your renewal.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to continue your renewal."}, status=500)

    def get_applicant_renewal_previous_records(self, application_id):
        auth = self.ensure_applicant_request("renewal previous records")
        if not auth:
            return
        supabase_url, service_key, user = auth
        config = {"supabase_url": supabase_url, "supabase_service_key": service_key}
        try:
            application = self.load_owned_renewal_application(config, application_id, user.get("id"))
            if not application:
                self.send_json({"error": "Renewal application not found."}, status=404)
                return
            source_permit_id = application.get("source_permit_id") or application.get("previous_permit_id")
            previous_application_id = application.get("previous_application_id")
            permits = self.service_rest_request(
                config, "business_permits",
                query=urlencode({"select": "*", "id": f"eq.{source_permit_id}", "limit": 1}),
            ) or []
            documents = []
            payments = []
            receipts = []
            if previous_application_id:
                documents = self.service_rest_request(
                    config, "application_documents",
                    query=urlencode({"select": "*", "application_id": f"eq.{previous_application_id}", "order": "created_at.asc"}),
                ) or []
                payments = self.service_rest_request(
                    config, "payments",
                    query=urlencode({"select": "*", "application_id": f"eq.{previous_application_id}", "order": "paid_at.desc,created_at.desc"}),
                ) or []
                receipts = self.service_rest_request(
                    config, "official_receipts",
                    query=urlencode({"select": "*", "application_id": f"eq.{previous_application_id}", "order": "issued_at.desc"}),
                ) or []
            self.send_json({
                "previousPermit": permits[0] if permits else None,
                "previousApplicationId": previous_application_id,
                "previousApplicationReference": (previous_application_id or "")[:8],
                "documents": [
                    {
                        "id": row.get("id"),
                        "name": (row.get("document_snapshot") or {}).get("documentName") or (row.get("document_snapshot") or {}).get("document_name") or row.get("file_name") or "Previous document",
                        "fileName": row.get("file_name") or "",
                        "uploadedAt": row.get("uploaded_at") or row.get("created_at") or "",
                        "status": row.get("upload_status") or "",
                        "referenceOnly": True,
                    }
                    for row in documents
                ],
                "payments": payments,
                "receipts": receipts,
                "label": "Previous Year - For Reference Only",
            })
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load previous renewal records.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load previous renewal records."}, status=500)

    def get_applicant_renewal_requirements(self, application_id):
        auth = self.ensure_applicant_request("renewal requirements")
        if not auth:
            return
        supabase_url, service_key, user = auth
        config = {"supabase_url": supabase_url, "supabase_service_key": service_key}
        try:
            application = self.load_owned_renewal_application(config, application_id, user.get("id"))
            if not application:
                self.send_json({"error": "Renewal application not found."}, status=404)
                return
            documents = self.service_rest_request(
                config,
                "application_documents",
                query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "order": "created_at.asc"}),
            ) or []
            self.send_json({
                "requirements": [
                    {
                        "id": row.get("id"),
                        "permitDocumentId": row.get("permit_document_id"),
                        "name": (row.get("document_snapshot") or {}).get("requirementName")
                            or (row.get("document_snapshot") or {}).get("documentName")
                            or (row.get("document_snapshot") or {}).get("document_name")
                            or "Renewal requirement",
                        "description": (row.get("document_snapshot") or {}).get("description")
                            or (row.get("document_snapshot") or {}).get("shortDescription")
                            or (row.get("document_snapshot") or {}).get("short_description")
                            or "",
                        "required": (row.get("document_snapshot") or {}).get("uploadRequired", True),
                        "acceptedFileTypes": (row.get("document_snapshot") or {}).get("acceptedFileTypes")
                            or (row.get("document_snapshot") or {}).get("accepted_file_types")
                            or [],
                        "maxFileSize": (row.get("document_snapshot") or {}).get("maxFileSize")
                            or (row.get("document_snapshot") or {}).get("max_file_size"),
                        "status": row.get("upload_status") or "Pending",
                        "fileName": row.get("file_name") or "",
                        "issueDate": row.get("issue_date") or "",
                        "expirationDate": row.get("expiration_date") or "",
                        "documentYear": row.get("document_year") or application.get("permit_year"),
                        "reusePolicy": row.get("renewal_reuse_policy") or "",
                        "sourceDocumentId": row.get("source_document_id") or "",
                    }
                    for row in documents
                ]
            })
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load renewal requirements.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load renewal requirements."}, status=500)

    def reminder_schedule(self, renewal_year, window):
        previous_year = int(renewal_year) - 1
        return [
            ("advance_december_1", date(previous_year, 12, 1)),
            ("second_december_15", date(previous_year, 12, 15)),
            ("expiration_december_31", date(previous_year, 12, 31)),
            ("renewal_open_january_1", window["start_date"]),
            ("deadline_january_10", date(int(renewal_year), 1, 10)),
            ("three_days_remaining", window["effective_due_date"].fromordinal(window["effective_due_date"].toordinal() - 3)),
            ("last_day", window["effective_due_date"]),
            ("late_notice", window["late_start_date"]),
        ]

    def send_renewal_reminder(self, config, permit, applicant_id, application_id, reminder_type, window):
        renewal_year = int(permit.get("renewal_year"))
        try:
            claims = self.service_rest_request(
                config, "renewal_notification_logs", method="POST",
                payload={
                    "permit_id": permit.get("id"), "applicant_id": applicant_id,
                    "renewal_year": renewal_year, "reminder_type": reminder_type,
                },
                prefer="return=representation",
            ) or []
        except HTTPError as error:
            if error.code == 409:
                return False
            raise
        if not claims:
            return False
        title, lead = self.REMINDER_COPY[reminder_type]
        message = (
            f"{lead} Business: {permit.get('business_name') or 'Business'}. "
            f"Permit {permit.get('permit_number') or '-'} ({permit.get('permit_year')}). "
            f"Valid until {permit.get('valid_until') or permit.get('expiration_date')}. "
            f"Renewal year {renewal_year}; regular period {window['start_date'].isoformat()} to "
            f"{window['effective_due_date'].isoformat()}. Current status: {permit.get('renewal_status') or 'not_open'}."
        )
        notification = self.create_notification(
            config["supabase_url"], config["supabase_service_key"], applicant_id,
            title, message, notification_type="renewal", source_role="System",
            application_id=application_id, related_permit_id=permit.get("id"),
            action_url=f"/applicant/permits/{permit.get('id')}/renew",
        )
        if not notification:
            self.service_rest_request(
                config, "renewal_notification_logs", method="DELETE",
                query=urlencode({"id": f"eq.{claims[0].get('id')}"}),
            )
            raise RuntimeError("Renewal notification could not be created.")
        self.service_rest_request(
            config, "renewal_notification_logs", method="PATCH",
            payload={"notification_id": notification.get("id")},
            query=urlencode({"id": f"eq.{claims[0].get('id')}"}),
        )
        self.create_service_audit_log(
            config["supabase_url"], config["supabase_service_key"], "renewal_notification_delivered",
            entity_type="business_permit", entity_id=permit.get("id"),
            details={"reminderType": reminder_type, "renewalYear": renewal_year, "notificationId": notification.get("id")},
        )
        return True

    def process_daily_renewals(self, config, clock=None, only_permit_id=None):
        today = manila_now(clock).date()
        query = {"select": "*", "status": "in.(Released,Expired)", "order": "created_at.asc", "limit": 5000}
        if only_permit_id:
            query["id"] = f"eq.{only_permit_id}"
        permits = self.service_rest_request(config, "business_permits", query=urlencode(query)) or []
        result = {"processed": 0, "updated": 0, "notifications": 0, "errors": []}
        for permit in permits:
            try:
                validity = calendar_permit_validity(
                    permit.get("issued_date") or permit.get("issue_date") or permit.get("released_at") or permit.get("valid_until")
                )
                renewal_year = int(permit.get("renewal_year") or validity["renewal_year"])
                permit = {**permit, "renewal_year": renewal_year, "permit_year": permit.get("permit_year") or validity["permit_year"], "valid_until": permit.get("valid_until") or validity["valid_until"]}
                settings, _extension, window = self.renewal_window_from_database(config, renewal_year)
                application = self.find_existing_renewal(config, permit.get("id"), renewal_year)
                new_status = status_for_permit(permit, application, today, window)
                if new_status != permit.get("renewal_status"):
                    self.service_rest_request(
                        config, "business_permits", method="PATCH",
                        payload={"renewal_status": new_status, "updated_at": utc_now_iso()},
                        query=urlencode({"id": f"eq.{permit.get('id')}"}),
                    )
                    self.create_service_audit_log(
                        config["supabase_url"], config["supabase_service_key"], "renewal_status_changed",
                        entity_type="business_permit", entity_id=permit.get("id"),
                        details={"previous": permit.get("renewal_status"), "new": new_status, "timezone": "Asia/Manila"},
                    )
                    permit["renewal_status"] = new_status
                    result["updated"] += 1
                source_apps = self.service_rest_request(
                    config, "applications",
                    query=urlencode({"select": "applicant_id", "id": f"eq.{permit.get('application_id')}", "limit": 1}),
                ) or []
                applicant_id = (source_apps[0] if source_apps else {}).get("applicant_id")
                if applicant_id:
                    logs = self.service_rest_request(
                        config, "renewal_notification_logs",
                        query=urlencode({
                            "select": "reminder_type", "permit_id": f"eq.{permit.get('id')}",
                            "renewal_year": f"eq.{renewal_year}",
                        }),
                    ) or []
                    sent_types = {row.get("reminder_type") for row in logs}
                    due = [(kind, target) for kind, target in self.reminder_schedule(renewal_year, window) if target <= today and kind not in sent_types]
                    exact = [item for item in due if item[1] == today]
                    candidate = exact[-1] if exact else (due[-1] if due and not sent_types else None)
                    if candidate and self.send_renewal_reminder(
                        config, permit, applicant_id, (application or {}).get("id"), candidate[0], window,
                    ):
                        result["notifications"] += 1
                result["processed"] += 1
            except Exception as error:  # Continue other permits; the scheduled job is fault-isolated.
                result["errors"].append({"permitId": permit.get("id"), "error": str(error)})
        return result

    def run_admin_renewal_job(self):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin"}, "renewal status job")
        if not config:
            return
        result = self.process_daily_renewals(config)
        self.send_json(result, status=207 if result["errors"] else 200)

    def list_admin_renewals(self):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin"}, "renewal monitoring")
        if not config:
            return
        params = parse_qs(urlsplit(self.path).query)
        page = max(1, int((params.get("page") or ["1"])[0] or 1))
        page_size = min(100, max(10, int((params.get("pageSize") or ["25"])[0] or 25)))
        filters = {"select": "*"}
        mappings = {
            "existingPermitYear": "existing_permit_year", "renewalYear": "renewal_year",
            "renewalStatus": "renewal_status", "departmentStatus": "department_status",
            "assessmentStatus": "renewal_assessment_status", "paymentStatus": "payment_status",
        }
        for source, column in mappings.items():
            value = ((params.get(source) or [""])[0]).strip()
            if value:
                if source == "renewalStatus" and value == "unrenewed":
                    filters["renewal_application_id"] = "is.null"
                else:
                    filters[column] = f"eq.{value}"
        timing = ((params.get("timing") or [""])[0]).strip().lower()
        if timing in {"on_time", "late"}:
            filters["is_late"] = f"eq.{'true' if timing == 'late' else 'false'}"
        business = ((params.get("businessName") or [""])[0]).strip()
        permit_number = ((params.get("permitNumber") or [""])[0]).strip()
        if business:
            filters["business_name"] = f"ilike.*{business}*"
        if permit_number:
            filters["permit_number"] = f"ilike.*{permit_number}*"
        count_rows = self.service_rest_request(config, "renewal_monitoring", query=urlencode({**filters, "select": "permit_id", "limit": 10000})) or []
        rows = self.service_rest_request(
            config, "renewal_monitoring",
            query=urlencode({**filters, "order": "updated_at.desc", "limit": page_size, "offset": (page - 1) * page_size}),
        ) or []
        self.send_json({"renewals": rows, "total": len(count_rows), "page": page, "pageSize": page_size})

    def get_admin_renewal_summary(self):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin"}, "renewal summary")
        if not config:
            return
        rows = self.service_rest_request(config, "renewal_monitoring", query=urlencode({"select": "renewal_status,renewal_application_id", "limit": 10000})) or []
        counts = {key: 0 for key in ("upcoming", "open", "submitted", "late", "under_review", "for_payment", "renewed", "unrenewed")}
        for row in rows:
            status = row.get("renewal_status") or "not_open"
            if status in counts:
                counts[status] += 1
            if not row.get("renewal_application_id") and status not in {"not_open", "renewed", "closed"}:
                counts["unrenewed"] += 1
        self.send_json({"summary": counts, "total": len(rows)})

    def get_renewal_settings(self):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin", "treasury"}, "renewal settings")
        if not config:
            return
        settings = self.load_renewal_settings(config)
        extensions = self.service_rest_request(config, "renewal_deadline_extensions", query=urlencode({"select": "*", "order": "renewal_year.desc,created_at.desc", "limit": 100})) or []
        requirements = self.service_rest_request(config, "renewal_requirements", query=urlencode({"select": "*,permit_documents(document_name)", "order": "updated_at.desc", "limit": 1000})) or []
        self.send_json({"settings": settings, "extensions": extensions, "requirements": requirements})

    def get_treasury_renewal_assessment(self, application_id):
        config = self.ensure_renewal_role({"treasury"}, "renewal assessment viewing")
        if not config:
            return
        apps = self.service_rest_request(
            config,
            "applications",
            query=urlencode({"select": "id,application_type,source_permit_id,permit_year,business_info,filed_at,is_late,original_renewal_due_date,effective_renewal_due_date", "id": f"eq.{application_id}", "application_type": "eq.renewal", "limit": 1}),
        ) or []
        if not apps:
            self.send_json({"error": "Renewal application not found."}, status=404)
            return
        assessments = self.service_rest_request(
            config,
            "renewal_fee_assessments",
            query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "status": "neq.voided", "order": "created_at.desc", "limit": 1}),
        ) or []
        self.send_json({"application": apps[0], "assessment": assessments[0] if assessments else None})

    def update_renewal_settings(self):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin", "treasury"}, "renewal settings update")
        if not config:
            return
        payload = self.read_json_body()
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            self.send_json({"error": "A reason for the settings change is required."}, status=400)
            return
        current = self.load_renewal_settings(config)
        field_map = {
            "renewalStartMonth": "renewal_start_month", "renewalStartDay": "renewal_start_day",
            "renewalDueMonth": "renewal_due_month", "renewalDueDay": "renewal_due_day",
            "surchargeRate": "surcharge_rate", "monthlyInterestRate": "monthly_interest_rate",
            "maximumInterestMonths": "maximum_interest_months", "interestMonthRule": "interest_month_rule",
            "penaltiesEnabled": "penalties_enabled",
        }
        changes = {column: payload[key] for key, column in field_map.items() if key in payload}
        if "interest_month_rule" in changes and changes["interest_month_rule"] not in INTEREST_MONTH_RULES:
            self.send_json({"error": "Unsupported delayed-month rule."}, status=400)
            return
        changes.update({"updated_by": config["actor"].get("id"), "updated_at": utc_now_iso()})
        rows = self.service_rest_request(
            config, "renewal_settings", method="PATCH", payload=changes,
            query=urlencode({"id": f"eq.{current.get('id')}"}), prefer="return=representation",
        ) or []
        updated = rows[0] if rows else {**current, **changes}
        self.service_rest_request(
            config, "renewal_settings_history", method="POST",
            payload={
                "settings_id": current.get("id"), "previous_values": current,
                "new_values": updated, "reason": reason, "changed_by": config["actor"].get("id"),
            },
        )
        self.create_service_audit_log(
            config["supabase_url"], config["supabase_service_key"], "renewal_settings_changed",
            actor=config["actor"], entity_type="renewal_settings", entity_id=current.get("id"),
            details={"previous": current, "new": updated, "reason": reason},
        )
        self.send_json({"message": "Renewal settings updated.", "settings": updated})

    def create_renewal_deadline_extension(self):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin", "treasury"}, "renewal deadline extension")
        if not config:
            return
        payload = self.read_json_body()
        required = ("renewalYear", "extendedDueDate", "reason", "authorizationReference")
        if any(not str(payload.get(key) or "").strip() for key in required):
            self.send_json({"error": "Renewal year, extended due date, reason, and authorization reference are required."}, status=400)
            return
        year = int(payload["renewalYear"])
        settings = self.load_renewal_settings(config)
        window = renewal_window(year, settings)
        extended = parse_date(payload["extendedDueDate"])
        if extended < window["original_due_date"]:
            self.send_json({"error": "The extended due date cannot be before the original due date."}, status=400)
            return
        self.service_rest_request(
            config, "renewal_deadline_extensions", method="PATCH",
            payload={"is_active": False},
            query=urlencode({"renewal_year": f"eq.{year}", "is_active": "eq.true"}),
        )
        rows = self.service_rest_request(
            config, "renewal_deadline_extensions", method="POST",
            payload={
                "renewal_year": year, "original_due_date": window["original_due_date"].isoformat(),
                "extended_due_date": extended.isoformat(), "reason": str(payload["reason"]).strip(),
                "authorization_reference": str(payload["authorizationReference"]).strip(),
                "surcharge_suspended": bool(payload.get("surchargeSuspended")),
                "interest_suspended": bool(payload.get("interestSuspended")),
                "authorized_by": config["actor"].get("id"),
            }, prefer="return=representation",
        ) or []
        extension = rows[0] if rows else {}
        self.create_service_audit_log(
            config["supabase_url"], config["supabase_service_key"], "renewal_deadline_extended",
            actor=config["actor"], entity_type="renewal_deadline_extension", entity_id=extension.get("id"),
            details=extension,
        )
        self.send_json({"message": "Renewal deadline extension recorded.", "extension": extension}, status=201)

    def list_admin_renewal_requirements(self):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin"}, "renewal requirement listing")
        if not config:
            return
        rows = self.service_rest_request(
            config,
            "renewal_requirements",
            query=urlencode({
                "select": "*,permits(permit_name,permit_code),permit_documents(document_name,short_description,accepted_file_types,max_file_size,upload_required),departments(name),business_classifications(name)",
                "deleted_at": "is.null",
                "order": "display_order.asc,updated_at.desc",
                "limit": 1000,
            }),
        ) or []
        self.send_json({"requirements": rows, "total": len(rows)})

    def upsert_renewal_requirement(self, requirement_id=None):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin"}, "renewal requirement update")
        if not config:
            return
        payload = self.read_json_body()
        permit_id = str(payload.get("permitId") or "").strip()
        document_id = str(payload.get("permitDocumentId") or "").strip()
        policy = str(payload.get("reusePolicy") or "reupload_every_year").strip()
        reason = str(payload.get("reason") or "").strip()
        if (not requirement_id and (not permit_id or not document_id)) or policy not in REUSE_POLICIES or not reason:
            self.send_json({"error": "Permit, document, supported reuse policy, and reason are required."}, status=400)
            return
        if requirement_id:
            existing = self.service_rest_request(
                config, "renewal_requirements",
                query=urlencode({"select": "*", "id": f"eq.{requirement_id}", "deleted_at": "is.null", "limit": 1}),
            ) or []
        else:
            existing = self.service_rest_request(
                config, "renewal_requirements",
                query=urlencode({"select": "*", "permit_id": f"eq.{permit_id}", "permit_document_id": f"eq.{document_id}", "deleted_at": "is.null", "limit": 1}),
            ) or []
        row_payload = {
            "reuse_policy": policy,
            "requirement_name": payload.get("requirementName") or payload.get("name") or None,
            "description": payload.get("description") or None,
            "business_classification_id": payload.get("businessClassificationId") or None,
            "responsible_department_id": payload.get("responsibleDepartmentId") or payload.get("requiredDepartmentId") or None,
            "required_department_id": payload.get("requiredDepartmentId") or payload.get("responsibleDepartmentId") or None,
            "is_required": bool(payload.get("isRequired", payload.get("required", True))),
            "allowed_file_types": payload.get("allowedFileTypes") or ["pdf", "png", "jpg", "jpeg"],
            "max_file_size": int(payload.get("maxFileSize") or 5242880),
            "number_of_copies": int(payload.get("numberOfCopies") or 1),
            "validity_required": bool(payload.get("validityRequired")),
            "previous_document_may_be_reused": policy in {"remains_valid", "reupload_when_expired"},
            "new_upload_required": policy not in {"remains_valid"},
            "display_order": int(payload.get("displayOrder") or 100),
            "is_active": bool(payload.get("isActive", True)),
            "updated_by": config["actor"].get("id"), "updated_at": utc_now_iso(),
        }
        if permit_id:
            row_payload["permit_id"] = permit_id
        if document_id:
            row_payload["permit_document_id"] = document_id
        if existing:
            rows = self.service_rest_request(
                config, "renewal_requirements", method="PATCH", payload=row_payload,
                query=urlencode({"id": f"eq.{existing[0].get('id')}"}), prefer="return=representation",
            ) or []
        else:
            rows = self.service_rest_request(config, "renewal_requirements", method="POST", payload=row_payload, prefer="return=representation") or []
        record = rows[0] if rows else row_payload
        self.create_service_audit_log(
            config["supabase_url"], config["supabase_service_key"], "renewal_requirement_changed",
            actor=config["actor"], entity_type="renewal_requirement", entity_id=record.get("id"),
            details={"previous": existing[0] if existing else None, "new": record, "reason": reason},
        )
        self.send_json({"message": "Renewal requirement saved.", "requirement": record})

    def delete_admin_renewal_requirement(self, requirement_id):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin"}, "renewal requirement deletion")
        if not config:
            return
        payload = self.read_json_body()
        reason = str(payload.get("reason") or "Requirement deactivated.").strip()
        existing = self.service_rest_request(
            config,
            "renewal_requirements",
            query=urlencode({"select": "*", "id": f"eq.{requirement_id}", "limit": 1}),
        ) or []
        if not existing:
            self.send_json({"error": "Renewal requirement not found."}, status=404)
            return
        linked = self.service_rest_request(
            config,
            "application_documents",
            query=urlencode({"select": "id", "permit_document_id": f"eq.{existing[0].get('permit_document_id')}", "limit": 1}),
        ) or []
        rows = self.service_rest_request(
            config,
            "renewal_requirements",
            method="PATCH",
            payload={"is_active": False, "deleted_at": utc_now_iso(), "updated_by": config["actor"].get("id"), "updated_at": utc_now_iso()},
            query=urlencode({"id": f"eq.{requirement_id}"}),
            prefer="return=representation",
        ) or []
        self.create_service_audit_log(
            config["supabase_url"], config["supabase_service_key"], "renewal_requirement_deactivated",
            actor=config["actor"], entity_type="renewal_requirement", entity_id=requirement_id,
            details={"reason": reason, "linkedDocumentsFound": bool(linked)},
        )
        self.send_json({"message": "Renewal requirement deactivated.", "requirement": rows[0] if rows else {}})

    def calculate_renewal_assessment(self, application_id, finalize=False):
        allowed = {"treasury"} if finalize else {"super_admin", "bplo_admin"}
        config = self.ensure_renewal_role(allowed, "renewal fee assessment")
        if not config:
            return
        try:
            request_payload = self.read_json_body()
            apps = self.service_rest_request(
                config, "applications",
                query=urlencode({"select": "*", "id": f"eq.{application_id}", "application_type": "eq.renewal", "limit": 1}),
            ) or []
            if not apps:
                self.send_json({"error": "Renewal application not found."}, status=404)
                return
            application = apps[0]
            current_rows = self.service_rest_request(
                config, "renewal_fee_assessments",
                query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "status": "neq.voided", "limit": 1}),
            ) or []
            current = current_rows[0] if current_rows else None
            if current and current.get("status") in {"finalized", "paid"}:
                self.send_json({"error": f"A {current.get('status')} renewal assessment cannot be recalculated."}, status=409)
                return
            settings = self.load_renewal_settings(config)
            extension = self.load_renewal_extension(config, application.get("permit_year"))
            calculation_date = manila_now().date()
            due_date = application.get("effective_renewal_due_date") or application.get("renewal_due_date")
            values = calculate_renewal_fees(
                base_renewal_fee=request_payload.get("baseRenewalFee"),
                other_fees=request_payload.get("otherFees", 0),
                penalty_base=request_payload.get("penaltyBase"),
                is_late=bool(application.get("is_late")),
                due_date=due_date,
                calculation_date=calculation_date,
                settings=settings,
                extension=extension,
                manual_months=request_payload.get("monthsDelayed"),
            )
            assessment_payload = {
                "application_id": application_id,
                "permit_year": application.get("permit_year"),
                **values,
                "calculation_date": calculation_date.isoformat(),
                "settings_snapshot": {
                    "settings": settings, "deadlineExtension": extension,
                    "filingDate": application.get("filed_at"), "isLate": application.get("is_late"),
                    "originalDueDate": application.get("original_renewal_due_date"),
                    "effectiveDueDate": due_date,
                },
                "status": "finalized" if finalize else "calculated",
                "calculated_by": config["actor"].get("id"),
                "finalized_by": config["actor"].get("id") if finalize else None,
                "finalized_at": utc_now_iso() if finalize else None,
            }
            if current:
                rows = self.service_rest_request(
                    config, "renewal_fee_assessments", method="PATCH", payload=assessment_payload,
                    query=urlencode({"id": f"eq.{current.get('id')}"}), prefer="return=representation",
                ) or []
            else:
                rows = self.service_rest_request(config, "renewal_fee_assessments", method="POST", payload=assessment_payload, prefer="return=representation") or []
            assessment = rows[0] if rows else assessment_payload
            event = "renewal_assessment_finalized" if finalize else "renewal_interest_recalculated"
            self.create_service_audit_log(
                config["supabase_url"], config["supabase_service_key"], event,
                actor=config["actor"], entity_type="renewal_fee_assessment", entity_id=assessment.get("id"),
                details={"previous": current, "new": assessment},
            )
            if finalize:
                self.sync_finalized_renewal_to_treasury(config, application, assessment)
            self.send_json({"message": "Renewal assessment finalized." if finalize else "Renewal assessment calculated.", "assessment": assessment})
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to calculate renewal assessment.")}, status=error.code)

    def sync_finalized_renewal_to_treasury(self, config, application, renewal_assessment):
        application_id = application.get("id")
        general = self.service_rest_request(
            config, "assessments", query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "limit": 1}),
        ) or []
        surcharge = decimal_value(renewal_assessment.get("surcharge_amount"))
        interest = decimal_value(renewal_assessment.get("interest_amount"))
        assessment_payload = {
            "status": "For Payment",
            "subtotal": renewal_assessment.get("base_renewal_fee"),
            "penalty_total": f"{(surcharge + interest).quantize(MONEY_QUANTUM):.2f}",
            "grand_total": renewal_assessment.get("total_amount"),
            "completed_by": config["actor"].get("id"), "completed_at": utc_now_iso(),
            "locked_at": utc_now_iso(), "updated_at": utc_now_iso(),
        }
        if general:
            rows = self.service_rest_request(
                config, "assessments", method="PATCH", payload=assessment_payload,
                query=urlencode({"id": f"eq.{general[0].get('id')}"}), prefer="return=representation",
            ) or []
        else:
            rows = self.service_rest_request(
                config, "assessments", method="POST",
                payload={"application_id": application_id, "assessment_number": self.generate_workflow_number("ASM"), **assessment_payload},
                prefer="return=representation",
            ) or []
        assessment = rows[0] if rows else (general[0] if general else {})
        queue = self.service_rest_request(
            config, "treasury_payment_queue", query=urlencode({"select": "*", "assessment_id": f"eq.{assessment.get('id')}", "limit": 1}),
        ) or []
        queue_payload = {"amount_due": renewal_assessment.get("total_amount"), "status": "Waiting for Payment", "updated_at": utc_now_iso()}
        if queue:
            self.service_rest_request(config, "treasury_payment_queue", method="PATCH", payload=queue_payload, query=urlencode({"id": f"eq.{queue[0].get('id')}"}))
        else:
            self.service_rest_request(
                config, "treasury_payment_queue", method="POST",
                payload={
                    "application_id": application_id, "assessment_id": assessment.get("id"),
                    "queue_number": self.generate_workflow_number("QUEUE"), **queue_payload,
                },
            )
        self.service_rest_request(
            config, "applications", method="PATCH",
            payload={"status": "For Payment", "progress": "Payment Required", "assessment_status": "Finalized", "payment_status": "For Payment", "updated_at": utc_now_iso()},
            query=urlencode({"id": f"eq.{application_id}"}),
        )
        self.service_rest_request(
            config, "business_permits", method="PATCH",
            payload={"renewal_status": "for_payment", "updated_at": utc_now_iso()},
            query=urlencode({"id": f"eq.{application.get('source_permit_id')}"}),
        )

    def void_renewal_assessment(self, assessment_id):
        config = self.ensure_renewal_role({"super_admin", "bplo_admin"}, "renewal assessment void")
        if not config:
            return
        payload = self.read_json_body()
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            self.send_json({"error": "A reason is required to void an assessment."}, status=400)
            return
        rows = self.service_rest_request(
            config, "renewal_fee_assessments",
            query=urlencode({"select": "*", "id": f"eq.{assessment_id}", "limit": 1}),
        ) or []
        if not rows:
            self.send_json({"error": "Renewal assessment not found."}, status=404)
            return
        if rows[0].get("status") == "paid":
            self.send_json({"error": "Paid assessments cannot be voided or edited."}, status=409)
            return
        updated = self.service_rest_request(
            config, "renewal_fee_assessments", method="PATCH",
            payload={"status": "voided", "void_reason": reason, "voided_by": config["actor"].get("id"), "voided_at": utc_now_iso()},
            query=urlencode({"id": f"eq.{assessment_id}"}), prefer="return=representation",
        ) or []
        self.create_service_audit_log(
            config["supabase_url"], config["supabase_service_key"], "renewal_assessment_voided",
            actor=config["actor"], entity_type="renewal_fee_assessment", entity_id=assessment_id,
            details={"previous": rows[0], "new": updated[0] if updated else None, "reason": reason},
        )
        self.send_json({"message": "Renewal assessment voided.", "assessment": updated[0] if updated else {}})
