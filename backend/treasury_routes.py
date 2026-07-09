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


class TreasuryRoutesMixin:
    def list_treasury_payment_queue(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            rows = self.service_rest_request(
                config,
                "treasury_payment_queue",
                query=urlencode({"select": "*,assessments(*),applications(id,status,business_info,permit_snapshot)", "order": "queued_at.desc", "limit": "300"}),
            ) or []
            queue = []
            for row in rows:
                app = row.get("applications") or {}
                info = app.get("business_info") or {}
                assessment = row.get("assessments") or {}
                queue.append(
                    {
                        "id": row.get("id"),
                        "applicationId": row.get("application_id"),
                        "assessmentId": row.get("assessment_id"),
                        "queueNumber": row.get("queue_number"),
                        "status": row.get("status"),
                        "amountDue": self.money(row.get("amount_due")),
                        "queuedAt": row.get("queued_at"),
                        "controlNumber": (row.get("application_id") or "")[:8],
                        "assessmentNumber": assessment.get("assessment_number") or "",
                        "applicant": self.app_owner_name(info),
                        "businessName": self.app_business_name(info),
                        "permitType": (app.get("permit_snapshot") or {}).get("permitName") or (app.get("permit_snapshot") or {}).get("permit_name") or "Business Permit",
                    }
                )
            self.send_json({"queue": queue, "total": len(queue)})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to load Treasury payment queue.")

    def confirm_treasury_payment(self, queue_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            payload = self.read_json_body()
            amount_paid = self.safe_float(payload.get("amountPaid"), 0)
            payment_method = (payload.get("paymentMethod") or "Cash").strip()
            payment_date = (payload.get("paymentDate") or "").strip()
            or_number = (payload.get("officialReceiptNumber") or "").strip()
            remarks = (payload.get("remarks") or "").strip()
            if not or_number:
                self.send_json({"error": "Official Receipt number is required."}, status=400)
                return
            if not payment_date:
                self.send_json({"error": "Payment date is required."}, status=400)
                return
            if amount_paid <= 0:
                self.send_json({"error": "Amount paid is required."}, status=400)
                return
            if self.service_rest_request(config, "official_receipts", query=urlencode({"select": "id", "receipt_number": f"eq.{or_number}", "limit": 1})) or []:
                self.send_json({"error": "This Official Receipt number is already used."}, status=400)
                return
            queue_rows = self.service_rest_request(config, "treasury_payment_queue", query=urlencode({"select": "*", "id": f"eq.{queue_id}", "limit": "1"})) or []
            if not queue_rows:
                self.send_json({"error": "Payment queue record not found."}, status=404)
                return
            queue = queue_rows[0]
            amount_due = self.safe_float(queue.get("amount_due"), 0)
            if queue.get("status") == "Paid":
                self.send_json({"error": "This payment has already been confirmed."}, status=400)
                return
            if amount_paid < amount_due:
                self.send_json({"error": "Amount paid is below the amount due."}, status=400)
                return
            paid_at = f"{payment_date}T00:00:00+00:00"
            payment_payload = {
                "application_id": queue.get("application_id"),
                "assessment_id": queue.get("assessment_id"),
                "queue_id": queue_id,
                "payment_reference": self.generate_workflow_number("PAY"),
                "amount_due": amount_due,
                "amount_paid": amount_paid,
                "change_amount": self.money(amount_paid - amount_due),
                "payment_method": payment_method,
                "payment_status": "Confirmed",
                "official_receipt_number": or_number,
                "paid_at": paid_at,
                "cashier_id": config["actor"].get("id"),
                "remarks": remarks,
            }
            payments = self.service_rest_request(config, "payments", method="POST", payload=payment_payload, prefer="return=representation") or []
            payment = payments[0] if payments else payment_payload
            receipts = self.service_rest_request(
                config,
                "official_receipts",
                method="POST",
                payload={"payment_id": payment.get("id"), "application_id": queue.get("application_id"), "receipt_number": or_number, "issued_by": config["actor"].get("id"), "issued_at": paid_at, "status": "Issued"},
                prefer="return=representation",
            ) or []
            now = utc_now_iso()
            self.service_rest_request(config, "treasury_payment_queue", method="PATCH", payload={"status": "Paid", "completed_at": now, "assigned_cashier_id": config["actor"].get("id"), "updated_at": now}, query=urlencode({"id": f"eq.{queue_id}"}))
            self.service_rest_request(config, "assessments", method="PATCH", payload={"status": "Paid", "updated_at": now}, query=urlencode({"id": f"eq.{queue.get('assessment_id')}"}))
            self.service_rest_request(config, "applications", method="PATCH", payload={"status": "Payment Verified", "progress": "Ready for Finalization", "payment_status": "Payment Verified", "assessment_status": "Paid", "updated_at": now}, query=urlencode({"id": f"eq.{queue.get('application_id')}"}))
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "payment_confirmed", actor=config["actor"], entity_type="payment", entity_id=payment.get("id"), details={"officialReceiptNumber": or_number, "amountPaid": amount_paid})
            self.notify_application_owner(config["supabase_url"], config["supabase_service_key"], queue.get("application_id"), "Payment Confirmed", f"Your payment has been processed. Official Receipt No. {or_number}. Your application is now ready for BPLO finalization.", notification_type="payment", source_role="Treasury")
            admin_user_ids = self.get_bplo_notification_users(config)
            admin_sent = self.create_notifications(
                config["supabase_url"],
                config["supabase_service_key"],
                [
                    {
                        "user_id": user_id,
                        "application_id": queue.get("application_id"),
                        "title": "Payment Confirmed",
                        "message": f"Treasury confirmed payment and issued Official Receipt {or_number}.",
                        "type": "payment",
                        "source_role": "Treasury",
                    }
                    for user_id in admin_user_ids
                ],
            ) if admin_user_ids else 0
            self.send_json({"message": "Payment confirmed and official receipt generated.", "payment": payment, "receipt": receipts[0] if receipts else {}, "adminNotifications": admin_sent})
        except HTTPError as error:
            self.treasury_error(error, "Unable to confirm payment.")
        except (json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to confirm payment.")

    def treasury_error(self, error, fallback):
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

    def get_treasury_profile(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        actor = config["actor"]
        profile = self.format_profile(config["profile"])
        self.send_json({"user": {"id": actor.get("id"), "email": actor.get("email"), "name": profile["name"] or "Treasury Staff", "role": profile["role"]}})

    def format_treasury_record(self, record):
        return {
            "id": record.get("id"),
            "applicationNo": record.get("application_no") or "",
            "orNo": record.get("or_no") or "",
            "applicant": record.get("applicant") or "",
            "businessName": record.get("business_name") or "",
            "amount": float(record.get("amount") or 0),
            "step": record.get("step") or "Assessment",
            "status": record.get("status") or "Pending",
            "currentStep": record.get("current_step") or record.get("step") or "Assessment",
            "recordType": record.get("record_type") or "payment",
            "transactionDate": record.get("transaction_date") or "",
            "remarks": record.get("remarks") or "",
            "createdAt": record.get("created_at") or "",
        }

    def list_treasury_records(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            query = urlencode({"select": "*", "deleted_at": "is.null", "order": "created_at.desc", "limit": "500"})
            rows = self.service_rest_request(config, "treasury_records", query=query) or []
            records = [self.format_treasury_record(row) for row in rows]
            total_collections = sum(record["amount"] for record in records if record["status"] == "Paid")
            counts = {
                "totalCollections": total_collections,
                "assessmentReview": sum(1 for record in records if record["step"] == "Assessment"),
                "readyForPayment": sum(1 for record in records if record["status"] in {"Ready", "Pending"}),
                "receiptsIssued": sum(1 for record in records if record["status"] == "Paid" or record["currentStep"] == "Official Receipt"),
            }
            self.send_json({"records": records, "counts": counts})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to load treasury records.")

    def export_treasury_reports(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            params = self.get_query_params()
            fmt = self.first_query_value(params, "format", "csv").lower()
            rows = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "*", "deleted_at": "is.null", "order": "transaction_date.desc,created_at.desc", "limit": "1000"}),
            ) or []
            headers = ["Application No.", "OR No.", "Applicant", "Business Name", "Amount", "Step", "Status", "Payment Date", "Cashier", "Remarks"]
            data = [
                [
                    row.get("application_no"),
                    row.get("or_no"),
                    row.get("applicant"),
                    row.get("business_name"),
                    self.money(row.get("amount")),
                    row.get("step"),
                    row.get("status"),
                    row.get("transaction_date"),
                    row.get("cashier") or "Treasury Staff",
                    row.get("remarks"),
                ]
                for row in rows
            ]
            total_collection = self.money(sum(self.safe_float(row.get("amount"), 0) for row in rows if row.get("status") in {"Paid", "Accepted"}))
            if fmt == "pdf":
                self.send_text_download(
                    self.html_report(
                        "Treasury Collection Report",
                        headers,
                        data,
                        {"Total Records": len(data), "Total Collection": f"PHP {total_collection:,.2f}"},
                    ),
                    "treasury-collection-report.html",
                    "text/html; charset=utf-8",
                )
                return
            self.send_text_download(self.csv_report(headers, data), "treasury-collection-report.csv", "text/csv; charset=utf-8")
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to export treasury report.")

    def validate_treasury_payload(self, payload):
        record = {
            "application_no": (payload.get("applicationNo") or "").strip(),
            "or_no": (payload.get("orNo") or "").strip(),
            "applicant": (payload.get("applicant") or "").strip(),
            "business_name": (payload.get("businessName") or "").strip(),
            "amount": payload.get("amount") or 0,
            "step": (payload.get("step") or "Assessment").strip(),
            "status": (payload.get("status") or "Pending").strip(),
            "current_step": (payload.get("currentStep") or payload.get("step") or "Assessment").strip(),
            "record_type": (payload.get("recordType") or "payment").strip(),
            "transaction_date": (payload.get("transactionDate") or "").strip(),
            "remarks": (payload.get("remarks") or "").strip(),
        }
        if not record["application_no"] or not record["applicant"] or not record["business_name"]:
            raise ValueError("Application number, applicant, and business name are required.")
        if record["status"] not in {"Paid", "Pending", "Ready", "Generated", "Not Generated", "Accepted"}:
            raise ValueError("Treasury status is invalid.")
        if not record["transaction_date"]:
            record["transaction_date"] = datetime.now(timezone.utc).date().isoformat()
        return record

    def create_treasury_record(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            record = self.validate_treasury_payload(self.read_json_body())
            record["created_by"] = config["actor"].get("id")
            rows = self.service_rest_request(config, "treasury_records", method="POST", payload=record, prefer="return=representation")
            created = rows[0] if rows else {}
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "treasury_record_created", actor=config["actor"], entity_type="treasury_record", entity_id=created.get("id"), details={"applicationNo": record["application_no"]})
            application = self.find_application_by_reference(config["supabase_url"], config["supabase_service_key"], record["application_no"])
            if application:
                self.create_notification(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    application.get("applicant_id"),
                    "Treasury Update",
                    f"Your treasury record is now {record['status']} for {record['current_step']}.",
                    notification_type="payment",
                    source_role="Treasury",
                    application_id=application.get("id"),
                )
            self.send_json({"message": "Treasury record created.", "record": self.format_treasury_record(created)}, status=201)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to create treasury record.")

    def update_treasury_record(self, record_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            payload = self.validate_treasury_payload(self.read_json_body())
            if payload["status"] == "Paid":
                if not payload["or_no"]:
                    self.send_json({"error": "Official Receipt number is required before marking payment as Paid."}, status=400)
                    return
                if self.safe_float(payload["amount"], 0) <= 0:
                    self.send_json({"error": "Amount paid is required before marking payment as Paid."}, status=400)
                    return
                duplicate_records = self.service_rest_request(
                    config,
                    "treasury_records",
                    query=urlencode({"select": "id", "or_no": f"eq.{payload['or_no']}", "id": f"neq.{record_id}", "deleted_at": "is.null", "limit": 1}),
                ) or []
                duplicate_receipts = self.service_rest_request(
                    config,
                    "official_receipts",
                    query=urlencode({"select": "id", "receipt_number": f"eq.{payload['or_no']}", "limit": 1}),
                ) or []
                if duplicate_records or duplicate_receipts:
                    self.send_json({"error": "This Official Receipt number is already used."}, status=400)
                    return
            payload["updated_at"] = utc_now_iso()
            query = urlencode({"id": f"eq.{record_id}", "deleted_at": "is.null"})
            rows = self.service_rest_request(config, "treasury_records", method="PATCH", payload=payload, query=query, prefer="return=representation")
            if not rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "treasury_record_updated", actor=config["actor"], entity_type="treasury_record", entity_id=record_id, details={"applicationNo": payload["application_no"]})
            application = self.find_application_by_reference(config["supabase_url"], config["supabase_service_key"], payload["application_no"])
            if application:
                status = payload["status"]
                if status == "Paid":
                    title = "Payment Verified"
                    message = "Your payment has been verified by Treasury."
                elif payload["current_step"] == "SOA Generation":
                    title = "Statement of Account Available"
                    message = "Your Statement of Account is now available."
                elif payload["current_step"] == "Official Receipt":
                    title = "Official Receipt Updated"
                    message = "Your Official Receipt has been generated or updated."
                else:
                    title = "Treasury Update"
                    message = f"Your treasury record is now {status} for {payload['current_step']}."
                self.create_notification(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    application.get("applicant_id"),
                    title,
                    message,
                    notification_type="payment",
                    source_role="Treasury",
                    application_id=application.get("id"),
                )
                if status == "Paid":
                    admin_user_ids = self.get_bplo_notification_users(config)
                    self.create_notifications(
                        config["supabase_url"],
                        config["supabase_service_key"],
                        [
                            {
                                "user_id": user_id,
                                "application_id": application.get("id"),
                                "title": "Payment Confirmed",
                                "message": f"Treasury confirmed payment and issued Official Receipt {payload['or_no']}.",
                                "type": "payment",
                                "source_role": "Treasury",
                            }
                            for user_id in admin_user_ids
                        ],
                    )
            self.send_json({"message": "Treasury record updated.", "record": self.format_treasury_record(rows[0])})
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to update treasury record.")

    def ensure_treasury_completion_state(self, config, record):
        application_reference = (record.get("application_no") or "").strip()
        application = self.find_application_by_reference(
            config["supabase_url"],
            config["supabase_service_key"],
            application_reference,
        ) if application_reference else None
        application_id = application.get("id") if application else None
        or_number = (record.get("or_no") or "").strip() or "Pending Official Receipt"
        business_name = (record.get("business_name") or "").strip() or "this application"
        now = utc_now_iso()

        payment = None
        receipt = None
        queue = None
        assessment_id = None
        amount_due = self.money(record.get("amount"))

        if application_id:
            queue_rows = self.service_rest_request(
                config,
                "treasury_payment_queue",
                query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "order": "created_at.desc", "limit": 1}),
            ) or []
            queue = queue_rows[0] if queue_rows else None
            assessment_id = queue.get("assessment_id") if queue else None
            if not assessment_id:
                assessment_rows = self.service_rest_request(
                    config,
                    "assessments",
                    query=urlencode({"select": "id", "application_id": f"eq.{application_id}", "order": "created_at.desc", "limit": 1}),
                ) or []
                assessment_id = (assessment_rows[0] or {}).get("id") if assessment_rows else None

            payment_rows = self.service_rest_request(
                config,
                "payments",
                query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "order": "created_at.desc", "limit": 5}),
            ) or []
            payment = next((row for row in payment_rows if row.get("payment_status") == "Confirmed"), None)
            if not payment:
                payment_payload = {
                    "application_id": application_id,
                    "assessment_id": assessment_id,
                    "queue_id": queue.get("id") if queue else None,
                    "payment_reference": self.generate_workflow_number("PAY"),
                    "amount_due": amount_due,
                    "amount_paid": amount_due,
                    "change_amount": 0,
                    "payment_method": "Cash",
                    "payment_status": "Confirmed",
                    "official_receipt_number": or_number,
                    "paid_at": now,
                    "cashier_id": config["actor"].get("id"),
                    "remarks": (record.get("remarks") or "Treasury workflow completed.").strip(),
                }
                created_payments = self.service_rest_request(
                    config,
                    "payments",
                    method="POST",
                    payload=payment_payload,
                    prefer="return=representation",
                ) or []
                payment = created_payments[0] if created_payments else payment_payload

            receipt_rows = self.service_rest_request(
                config,
                "official_receipts",
                query=urlencode({"select": "*", "application_id": f"eq.{application_id}", "receipt_number": f"eq.{or_number}", "limit": 1}),
            ) or []
            receipt = receipt_rows[0] if receipt_rows else None
            if not receipt:
                created_receipts = self.service_rest_request(
                    config,
                    "official_receipts",
                    method="POST",
                    payload={
                        "payment_id": payment.get("id"),
                        "application_id": application_id,
                        "receipt_number": or_number,
                        "issued_by": config["actor"].get("id"),
                        "issued_at": now,
                        "status": "Issued",
                    },
                    prefer="return=representation",
                ) or []
                receipt = created_receipts[0] if created_receipts else {}

            if queue and queue.get("status") != "Paid":
                self.service_rest_request(
                    config,
                    "treasury_payment_queue",
                    method="PATCH",
                    payload={"status": "Paid", "completed_at": now, "assigned_cashier_id": config["actor"].get("id"), "updated_at": now},
                    query=urlencode({"id": f"eq.{queue.get('id')}"}),
                )

            if assessment_id:
                self.service_rest_request(
                    config,
                    "assessments",
                    method="PATCH",
                    payload={"status": "Paid", "updated_at": now},
                    query=urlencode({"id": f"eq.{assessment_id}"}),
                )

            self.service_rest_request(
                config,
                "applications",
                method="PATCH",
                payload={
                    "status": "Payment Verified",
                    "progress": "Ready for Finalization",
                    "payment_status": "Payment Verified",
                    "assessment_status": "Paid",
                    "updated_at": now,
                },
                query=urlencode({"id": f"eq.{application_id}"}),
            )

        return {
            "application": application,
            "applicationId": application_id,
            "applicationReference": application_reference,
            "businessName": business_name,
            "orNumber": or_number,
            "payment": payment,
            "receipt": receipt,
        }

    def sync_treasury_record_completion(self, record_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            rows = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "*", "id": f"eq.{record_id}", "deleted_at": "is.null", "limit": 1}),
            ) or []
            if not rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return

            state = self.ensure_treasury_completion_state(config, rows[0])
            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "treasury_completion_synced",
                actor=config["actor"],
                entity_type="treasury_record",
                entity_id=record_id,
                details={
                    "applicationNo": state["applicationReference"],
                    "applicationStatusUpdated": bool(state["applicationId"]),
                    "officialReceiptNumber": state["orNumber"],
                },
            )
            self.send_json(
                {
                    "message": "Treasury workflow synced to the application record.",
                    "applicationStatusUpdated": bool(state["applicationId"]),
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to sync treasury completion.")

    def notify_treasury_print_complete(self, record_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            rows = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "*", "id": f"eq.{record_id}", "deleted_at": "is.null", "limit": 1}),
            ) or []
            if not rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return

            record = rows[0]
            state = self.ensure_treasury_completion_state(config, record)
            application_id = state["applicationId"]
            application_reference = state["applicationReference"]
            business_name = state["businessName"]
            or_number = state["orNumber"]
            payment = state["payment"]
            receipt = state["receipt"]

            applicant_sent = False
            if application_id:
                applicant_notification = self.notify_application_owner(
                    config["supabase_url"],
                    config["supabase_service_key"],
                    application_id,
                    "Payment Completed",
                    f"Your payment for {business_name} has been processed. Official Receipt {or_number} is ready, and your application is now ready for BPLO finalization.",
                    notification_type="payment",
                    source_role="Treasury",
                )
                applicant_sent = bool(applicant_notification)

            admin_user_ids = self.get_bplo_notification_users(config)
            admin_notifications = []
            for user_id in admin_user_ids:
                admin_notifications.append(
                    {
                        "user_id": user_id,
                        "application_id": application_id,
                        "title": "Payment Completed",
                        "message": f"Payment has been completed for {business_name}. Official Receipt {or_number} is ready for final processing.",
                        "type": "payment",
                        "source_role": "Treasury",
                    }
                )
            admin_sent = self.create_notifications(
                config["supabase_url"],
                config["supabase_service_key"],
                admin_notifications,
            ) if admin_notifications else 0

            self.create_service_audit_log(
                config["supabase_url"],
                config["supabase_service_key"],
                "treasury_print_notification_sent",
                actor=config["actor"],
                entity_type="treasury_record",
                entity_id=record_id,
                details={
                    "applicationNo": application_reference,
                    "officialReceiptNumber": or_number,
                    "applicantNotified": applicant_sent,
                    "adminNotifications": admin_sent,
                    "applicationStatusUpdated": bool(application_id),
                    "paymentId": payment.get("id") if payment else None,
                    "receiptId": receipt.get("id") if receipt else None,
                },
            )
            self.send_json(
                {
                    "message": "Payment completion notifications sent and application is ready for finalization.",
                    "applicantNotified": applicant_sent,
                    "adminNotifications": admin_sent,
                    "applicationStatusUpdated": bool(application_id),
                }
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to send payment completion notifications.")

    def soft_delete_treasury_record(self, record_id):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            query = urlencode({"id": f"eq.{record_id}", "deleted_at": "is.null"})
            rows = self.service_rest_request(config, "treasury_records", method="PATCH", payload={"deleted_at": utc_now_iso(), "updated_at": utc_now_iso()}, query=query, prefer="return=representation")
            if not rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "treasury_record_deleted", actor=config["actor"], entity_type="treasury_record", entity_id=record_id, details={"softDelete": True})
            self.send_json({"message": "Treasury record deleted.", "record": self.format_treasury_record(rows[0])})
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to delete treasury record.")

