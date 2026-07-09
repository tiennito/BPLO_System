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


class AssessmentServiceMixin:
    def get_or_create_assessment(self, config, application_id):
        rows = self.service_rest_request(
            config,
            "assessments",
            query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "limit": "1"}),
        ) or []
        if rows:
            return rows[0]
        created = self.service_rest_request(
            config,
            "assessments",
            method="POST",
            payload={
                "application_id": application_id,
                "assessment_number": self.generate_workflow_number("SOA"),
                "status": "In Progress",
            },
            prefer="return=representation",
        ) or []
        return created[0] if created else None

    def recalculate_assessment(self, config, assessment_id):
        items = self.service_rest_request(
            config,
            "assessment_items",
            query=urlencode({"select": "*", "assessment_id": f"eq.{assessment_id}", "is_active": "eq.true"}),
        ) or []
        subtotal = sum(self.money(item.get("amount")) for item in items)
        penalties = sum(self.money(item.get("penalty")) for item in items)
        discounts = sum(self.money(item.get("discount")) for item in items)
        grand_total = sum(self.money(item.get("final_amount")) for item in items)
        updated = self.service_rest_request(
            config,
            "assessments",
            method="PATCH",
            payload={
                "subtotal": subtotal,
                "penalty_total": penalties,
                "discount_total": discounts,
                "grand_total": grand_total,
                "updated_at": utc_now_iso(),
            },
            query=urlencode({"id": f"eq.{assessment_id}"}),
            prefer="return=representation",
        ) or []
        return updated[0] if updated else None

    def get_admin_application_assessment(self, application_id):
        config = self.admin_config_with_actor("assessment viewing")
        if not config:
            return
        try:
            assessment = self.get_or_create_assessment(config, application_id)
            self.recalculate_assessment(config, assessment.get("id"))
            bundle = self.load_application_bundle(config["supabase_url"], config["supabase_service_key"], application_id)
            self.send_json({"assessment": self.format_admin_review_bundle(bundle)})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to load assessment.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to load assessment."}, status=500)

    def build_assessment_item_payload(self, config, payload, existing=None):
        assessment_id = (payload.get("assessmentId") or (existing or {}).get("assessment_id") or "").strip()
        application_id = (payload.get("applicationId") or (existing or {}).get("application_id") or "").strip()
        quantity = self.safe_float(payload.get("quantity"), 1)
        rate = self.safe_float(payload.get("rate"), 0)
        amount = self.safe_float(payload.get("amount"), quantity * rate)
        penalty = self.safe_float(payload.get("penalty"), 0)
        discount = self.safe_float(payload.get("discount"), 0)
        final_amount = self.safe_float(payload.get("finalAmount"), amount + penalty - discount)
        return {
            "assessment_id": assessment_id,
            "application_id": application_id,
            "department_key": (payload.get("departmentKey") or (existing or {}).get("department_key") or "bplo").strip(),
            "fee_type_id": (payload.get("feeTypeId") or None),
            "fee_name": (payload.get("feeName") or (existing or {}).get("fee_name") or "").strip(),
            "category": (payload.get("category") or (existing or {}).get("category") or "Regulatory Fees and Charges").strip(),
            "computation_basis": (payload.get("computationBasis") or "").strip(),
            "formula_type": (payload.get("formulaType") or (existing or {}).get("formula_type") or "fixed").strip(),
            "quantity": quantity,
            "unit": (payload.get("unit") or "").strip(),
            "rate": rate,
            "percentage": self.safe_float(payload.get("percentage"), 0),
            "base_amount": self.safe_float(payload.get("baseAmount"), amount),
            "amount": self.money(amount),
            "penalty": self.money(penalty),
            "discount": self.money(discount),
            "final_amount": self.money(final_amount),
            "remarks": (payload.get("remarks") or "").strip(),
            "status": (payload.get("status") or "Submitted").strip(),
            "updated_by": config["actor"].get("id"),
            "updated_at": utc_now_iso(),
        }

    def create_admin_assessment_item(self):
        config = self.admin_config_with_actor("assessment item creation")
        if not config:
            return
        try:
            payload = self.read_json_body()
            application_id = (payload.get("applicationId") or "").strip()
            if not application_id:
                self.send_json({"error": "Application is required."}, status=400)
                return
            assessment = self.get_or_create_assessment(config, application_id)
            payload["assessmentId"] = assessment.get("id")
            item = self.build_assessment_item_payload(config, payload)
            if not item["fee_name"]:
                self.send_json({"error": "Fee item name is required."}, status=400)
                return
            item["created_by"] = config["actor"].get("id")
            rows = self.service_rest_request(config, "assessment_items", method="POST", payload=item, prefer="return=representation") or []
            updated_assessment = self.recalculate_assessment(config, assessment.get("id"))
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "fee_created", actor=config["actor"], entity_type="assessment_item", entity_id=(rows[0] if rows else {}).get("id"), details={"feeName": item["fee_name"]})
            self.send_json({"message": "Assessment item added.", "item": rows[0] if rows else {}, "assessment": updated_assessment}, status=201)
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to create assessment item.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to create assessment item."}, status=500)

    def update_admin_assessment_item(self, item_id):
        config = self.admin_config_with_actor("assessment item update")
        if not config:
            return
        try:
            existing = self.service_rest_request(config, "assessment_items", query=urlencode({"select": "*", "id": f"eq.{item_id}", "limit": "1"})) or []
            if not existing:
                self.send_json({"error": "Assessment item not found."}, status=404)
                return
            assessment = self.service_rest_request(config, "assessments", query=urlencode({"select": "id,status", "id": f"eq.{existing[0].get('assessment_id')}", "limit": "1"})) or []
            if assessment and assessment[0].get("status") in {"Completed", "For Payment", "Paid"}:
                self.send_json({"error": "This assessment is locked and can no longer be edited."}, status=400)
                return
            item = self.build_assessment_item_payload(config, self.read_json_body(), existing=existing[0])
            item.pop("assessment_id", None)
            item.pop("application_id", None)
            rows = self.service_rest_request(config, "assessment_items", method="PATCH", payload=item, query=urlencode({"id": f"eq.{item_id}", "is_active": "eq.true"}), prefer="return=representation") or []
            updated_assessment = self.recalculate_assessment(config, existing[0].get("assessment_id"))
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "fee_updated", actor=config["actor"], entity_type="assessment_item", entity_id=item_id, details={"feeName": item.get("fee_name")})
            self.send_json({"message": "Assessment item updated.", "item": rows[0] if rows else {}, "assessment": updated_assessment})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to update assessment item.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to update assessment item."}, status=500)

    def delete_admin_assessment_item(self, item_id):
        config = self.admin_config_with_actor("assessment item removal")
        if not config:
            return
        try:
            existing = self.service_rest_request(config, "assessment_items", query=urlencode({"select": "*", "id": f"eq.{item_id}", "limit": "1"})) or []
            if not existing:
                self.send_json({"error": "Assessment item not found."}, status=404)
                return
            rows = self.service_rest_request(config, "assessment_items", method="PATCH", payload={"is_active": False, "status": "Cancelled", "updated_by": config["actor"].get("id"), "updated_at": utc_now_iso()}, query=urlencode({"id": f"eq.{item_id}"}), prefer="return=representation") or []
            updated_assessment = self.recalculate_assessment(config, existing[0].get("assessment_id"))
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "fee_removed", actor=config["actor"], entity_type="assessment_item", entity_id=item_id, details={"softDelete": True})
            self.send_json({"message": "Assessment item removed.", "item": rows[0] if rows else {}, "assessment": updated_assessment})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to remove assessment item.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to remove assessment item."}, status=500)

    def complete_admin_assessment(self, application_id):
        config = self.admin_config_with_actor("assessment completion")
        if not config:
            return
        try:
            app = self.load_application_core(config["supabase_url"], config["supabase_service_key"], application_id)
            if not app:
                self.send_json({"error": "Application not found."}, status=404)
                return
            if app.get("status") in {"Rejected", "For Revision"}:
                self.send_json({"error": "This application has an unresolved rejection or revision request."}, status=400)
                return
            assessment = self.get_or_create_assessment(config, application_id)
            assessment = self.recalculate_assessment(config, assessment.get("id"))
            items = self.service_rest_request(config, "assessment_items", query=urlencode({"select": "id", "assessment_id": f"eq.{assessment.get('id')}", "is_active": "eq.true"})) or []
            if not items:
                self.send_json({"error": "The assessment cannot be completed because no fee items were submitted."}, status=400)
                return
            now = utc_now_iso()
            updated_assessment = self.service_rest_request(
                config,
                "assessments",
                method="PATCH",
                payload={"status": "For Payment", "completed_by": config["actor"].get("id"), "completed_at": now, "locked_at": now, "updated_at": now},
                query=urlencode({"id": f"eq.{assessment.get('id')}"}),
                prefer="return=representation",
            ) or []
            self.service_rest_request(config, "assessment_items", method="PATCH", payload={"status": "Locked", "updated_at": now}, query=urlencode({"assessment_id": f"eq.{assessment.get('id')}", "is_active": "eq.true"}))
            self.service_rest_request(config, "applications", method="PATCH", payload={"status": "For Payment", "progress": "Payment Required", "assessment_status": "Completed", "payment_status": "For Payment", "updated_at": now}, query=urlencode({"id": f"eq.{application_id}"}))
            queue_rows = self.service_rest_request(
                config,
                "treasury_payment_queue",
                query=urlencode({"select": "*", "assessment_id": f"eq.{assessment.get('id')}", "limit": "1"}),
            ) or []
            if queue_rows:
                queue_rows = self.service_rest_request(
                    config,
                    "treasury_payment_queue",
                    method="PATCH",
                    payload={"status": "Waiting for Payment", "amount_due": assessment.get("grand_total") or 0, "updated_at": now},
                    query=urlencode({"id": f"eq.{queue_rows[0].get('id')}"}),
                    prefer="return=representation",
                ) or queue_rows
            else:
                queue_rows = self.service_rest_request(
                    config,
                    "treasury_payment_queue",
                    method="POST",
                    payload={"application_id": application_id, "assessment_id": assessment.get("id"), "queue_number": self.generate_workflow_number("Q"), "status": "Waiting for Payment", "amount_due": assessment.get("grand_total") or 0},
                    prefer="return=representation",
                ) or []
            info = app.get("business_info") or {}
            try:
                self.service_rest_request(config, "treasury_records", method="POST", payload={"application_no": (application_id or "")[:8], "applicant": self.app_owner_name(info), "business_name": self.app_business_name(info), "amount": assessment.get("grand_total") or 0, "step": "Assessment", "status": "Ready", "current_step": "Payment Queue", "record_type": "payment", "transaction_date": datetime.now(timezone.utc).date().isoformat(), "remarks": "Generated from completed assessment."}, prefer="return=minimal")
            except HTTPError:
                pass
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "assessment_completed", actor=config["actor"], entity_type="assessment", entity_id=assessment.get("id"), details={"grandTotal": assessment.get("grand_total")})
            self.notify_application_owner(config["supabase_url"], config["supabase_service_key"], application_id, "Payment Required", "Your application has been forwarded to the Treasury for payment. Please settle the assessed fees to continue finalization.", notification_type="payment", source_role="BPLO")
            self.send_json({"message": "Assessment completed and routed to Treasury.", "assessment": updated_assessment[0] if updated_assessment else assessment, "queue": queue_rows[0] if queue_rows else {}})
        except HTTPError as error:
            self.send_json({"error": self.handle_rest_error(error, "Unable to complete assessment.")}, status=error.code)
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.send_json({"error": str(error) or "Unable to complete assessment."}, status=500)

    def get_department_workspace_assessment_item(self, config, application_id):
        assessment_rows = self.service_rest_request(
            config,
            "assessments",
            query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "limit": "1"}),
        ) or []
        assessment = assessment_rows[0] if assessment_rows else None
        if not assessment:
            return None, None

        item_rows = self.service_rest_request(
            config,
            "assessment_items",
            query=urlencode(
                {
                    "select": "*",
                    "assessment_id": f"eq.{assessment.get('id')}",
                    "application_id": f"eq.{application_id}",
                    "department_key": f"eq.{config['department_key']}",
                    "is_active": "eq.true",
                    "order": "created_at.asc",
                }
            ),
        ) or []
        return assessment, (item_rows[-1] if item_rows else None), item_rows

    def upsert_department_assessment(self, application_id):
        config = self.ensure_department_request()
        if not config:
            return

        try:
            payload = self.read_json_body()
            application_id = (application_id or payload.get("applicationId") or "").strip()
            if not application_id:
                self.send_json({"error": "Application is required."}, status=400)
                return
            if not self.get_department_assignments(config, application_id=application_id):
                self.send_json({"error": "Application not found for this department."}, status=404)
                return

            assessment = self.get_or_create_assessment(config, application_id)
            if not assessment:
                self.send_json({"error": "Unable to prepare assessment record."}, status=500)
                return

            incoming_items = payload.get("items") if isinstance(payload.get("items"), list) else None
            if incoming_items is None:
                incoming_items = [payload]

            cleaned_items = []
            for raw_item in incoming_items:
                if not isinstance(raw_item, dict):
                    continue
                fee_name = (raw_item.get("feeName") or "Department fee").strip()
                category = (raw_item.get("category") or "").strip()
                amount = self.money(self.safe_float(raw_item.get("amount"), 0))
                penalty = self.money(self.safe_float(raw_item.get("penalty"), 0))
                if not fee_name and not category and amount == 0 and penalty == 0:
                    continue
                if not fee_name:
                    self.send_json({"error": "Fee description is required."}, status=400)
                    return
                item_payload = dict(raw_item)
                item_payload["feeName"] = fee_name
                item_payload["assessmentId"] = assessment.get("id")
                item_payload["applicationId"] = application_id
                item_payload["departmentKey"] = config["department_key"]
                item_payload["remarks"] = (raw_item.get("remarks") or payload.get("remarks") or "").strip()
                item_payload["finalAmount"] = self.money(amount + penalty)
                cleaned_items.append(item_payload)

            if not cleaned_items:
                self.send_json({"error": "At least one fee item is required."}, status=400)
                return

            existing_rows = self.service_rest_request(
                config,
                "assessment_items",
                query=urlencode(
                    {
                        "select": "*",
                        "assessment_id": f"eq.{assessment.get('id')}",
                        "application_id": f"eq.{application_id}",
                        "department_key": f"eq.{config['department_key']}",
                        "is_active": "eq.true",
                        "order": "created_at.asc",
                    }
                ),
            ) or []
            existing_by_id = {str(row.get("id")): row for row in existing_rows if row.get("id")}
            saved_items = []
            submitted_ids = set()

            for raw_item in cleaned_items:
                item_id = (raw_item.get("id") or "").strip()
                existing = existing_by_id.get(item_id)
                item = self.build_assessment_item_payload(config, raw_item, existing=existing)
                item["status"] = "Submitted"
                if existing:
                    item.pop("assessment_id", None)
                    item.pop("application_id", None)
                    rows = self.service_rest_request(
                        config,
                        "assessment_items",
                        method="PATCH",
                        payload=item,
                        query=urlencode({"id": f"eq.{existing.get('id')}", "is_active": "eq.true"}),
                        prefer="return=representation",
                    ) or []
                    saved_item = rows[0] if rows else {}
                    submitted_ids.add(str(existing.get("id")))
                    action = "department_fee_updated"
                else:
                    item["created_by"] = config["actor"].get("id")
                    rows = self.service_rest_request(
                        config,
                        "assessment_items",
                        method="POST",
                        payload=item,
                        prefer="return=representation",
                    ) or []
                    saved_item = rows[0] if rows else {}
                    if saved_item.get("id"):
                        submitted_ids.add(str(saved_item.get("id")))
                    action = "department_fee_created"
                if saved_item:
                    saved_items.append(saved_item)
                self.create_service_audit_log(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    action,
                    actor=config["actor"],
                    entity_type="assessment_item",
                    entity_id=saved_item.get("id"),
                    details={"department": config["department_key"], "applicationId": application_id, "feeName": item.get("fee_name")},
                )

            removed_ids = [str(row.get("id")) for row in existing_rows if str(row.get("id")) not in submitted_ids]
            if removed_ids:
                self.service_rest_request(
                    config,
                    "assessment_items",
                    method="PATCH",
                    payload={
                        "is_active": False,
                        "status": "Cancelled",
                        "updated_by": config["actor"].get("id"),
                        "updated_at": utc_now_iso(),
                    },
                    query=urlencode({"id": f"in.({','.join(removed_ids)})"}),
                    prefer="return=minimal",
                )

            updated_assessment = self.recalculate_assessment(config, assessment.get("id"))
            refreshed_items = self.service_rest_request(
                config,
                "assessment_items",
                query=urlencode(
                    {
                        "select": "*",
                        "assessment_id": f"eq.{assessment.get('id')}",
                        "application_id": f"eq.{application_id}",
                        "department_key": f"eq.{config['department_key']}",
                        "is_active": "eq.true",
                        "order": "created_at.asc",
                    }
                ),
            ) or []
            self.send_json(
                {
                    "message": "Department assessment saved.",
                    "item": refreshed_items[-1] if refreshed_items else (saved_items[-1] if saved_items else {}),
                    "items": refreshed_items,
                    "assessment": updated_assessment,
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.department_error(error, "Unable to save department assessment.")

