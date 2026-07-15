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
            record_rows = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "id", "application_no": f"eq.{(queue.get('application_id') or '')[:8]}", "deleted_at": "is.null", "limit": 1}),
            ) or []
            treasury_record_payload = {
                "application_no": (queue.get("application_id") or "")[:8],
                "or_no": or_number,
                "amount": amount_due,
                "step": "Official Receipt",
                "current_step": "Official Receipt",
                "status": "Paid",
                "transaction_date": payment_date,
                "remarks": remarks or "Payment confirmed and Official Receipt issued.",
                "updated_at": now,
            }
            if record_rows:
                self.service_rest_request(config, "treasury_records", method="PATCH", payload=treasury_record_payload, query=urlencode({"id": f"eq.{record_rows[0].get('id')}"}), prefer="return=minimal")
            else:
                app_rows = self.service_rest_request(config, "applications", query=urlencode({"select": "business_info", "id": f"eq.{queue.get('application_id')}", "limit": 1})) or []
                info = ((app_rows[0] if app_rows else {}) or {}).get("business_info") or {}
                treasury_record_payload.update({"applicant": self.app_owner_name(info), "business_name": self.app_business_name(info), "record_type": "payment", "created_by": config["actor"].get("id")})
                self.service_rest_request(config, "treasury_records", method="POST", payload=treasury_record_payload, prefer="return=minimal")
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
        current_step = record.get("current_step") or record.get("step") or "Assessment"
        status = record.get("status") or "Pending"
        or_no = record.get("or_no") or ""
        soa_status = self.treasury_soa_status(current_step, status)
        payment_status = self.treasury_payment_status(current_step, status, or_no)
        or_status = self.treasury_or_status(current_step, status, or_no)
        return {
            "id": record.get("id"),
            "applicationNo": record.get("application_no") or "",
            "orNo": or_no,
            "applicant": record.get("applicant") or "",
            "businessName": record.get("business_name") or "",
            "amount": float(record.get("amount") or 0),
            "step": record.get("step") or "Assessment",
            "status": status,
            "currentStep": current_step,
            "soaStatus": soa_status,
            "paymentStatus": payment_status,
            "orStatus": or_status,
            "actionLabel": self.treasury_action_label(current_step, status, or_no),
            "recordType": record.get("record_type") or "payment",
            "transactionDate": record.get("transaction_date") or "",
            "remarks": record.get("remarks") or "",
            "createdAt": record.get("created_at") or "",
        }

    def treasury_soa_status(self, current_step, status):
        if current_step == "Assessment":
            return "Not Generated"
        if current_step == "SOA Generation" and status == "Ready":
            return "Ready"
        return "Generated"

    def treasury_payment_status(self, current_step, status, or_no=""):
        if status in {"Paid", "Accepted"} or or_no:
            return "Paid"
        if current_step in {"Official Receipt"} and status == "Ready":
            return "Paid"
        if current_step == "Payment":
            return "Pending"
        return "Not Paid"

    def treasury_or_status(self, current_step, status, or_no=""):
        if status in {"Paid", "Accepted"} or or_no:
            return "Issued"
        if current_step == "Official Receipt" and status == "Ready":
            return "Ready"
        return "Not Issued"

    def treasury_action_label(self, current_step, status, or_no=""):
        if current_step == "Assessment":
            return "Process"
        if current_step == "SOA Generation":
            return "Generate SOA"
        if current_step == "Payment":
            return "Accept Payment"
        if current_step == "Official Receipt" and self.treasury_or_status(current_step, status, or_no) == "Ready":
            return "Issue OR"
        if self.treasury_or_status(current_step, status, or_no) == "Issued":
            return "View OR"
        return "Process"

    def ensure_treasury_records_from_payment_queue(self, config):
        queue_rows = self.service_rest_request(
            config,
            "treasury_payment_queue",
            query=urlencode({"select": "*,assessments(*),applications(id,business_info)", "order": "queued_at.desc", "limit": "300"}),
        ) or []
        for row in queue_rows:
            application_id = row.get("application_id")
            if not application_id:
                continue
            receipt_rows = self.service_rest_request(
                config,
                "official_receipts",
                query=urlencode({"select": "receipt_number,issued_at,status", "application_id": f"eq.{application_id}", "order": "issued_at.desc", "limit": 1}),
            ) or []
            receipt = receipt_rows[0] if receipt_rows else None
            existing = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "id", "application_no": f"eq.{application_id[:8]}", "deleted_at": "is.null", "limit": 1}),
            ) or []
            if existing:
                if receipt and row.get("status") == "Paid":
                    self.service_rest_request(
                        config,
                        "treasury_records",
                        method="PATCH",
                        payload={
                            "or_no": receipt.get("receipt_number") or "",
                            "step": "Official Receipt",
                            "current_step": "Official Receipt",
                            "status": "Paid",
                            "transaction_date": (receipt.get("issued_at") or "")[:10] or datetime.now(timezone.utc).date().isoformat(),
                            "updated_at": utc_now_iso(),
                        },
                        query=urlencode({"id": f"eq.{existing[0].get('id')}"}),
                        prefer="return=minimal",
                    )
                continue
            app = row.get("applications") or {}
            info = app.get("business_info") or {}
            assessment = row.get("assessments") or {}
            is_paid = bool(receipt and row.get("status") == "Paid")
            self.service_rest_request(
                config,
                "treasury_records",
                method="POST",
                payload={
                    "application_no": application_id[:8],
                    "or_no": receipt.get("receipt_number") if is_paid else "",
                    "applicant": self.app_owner_name(info),
                    "business_name": self.app_business_name(info),
                    "amount": row.get("amount_due") or assessment.get("grand_total") or 0,
                    "step": "Official Receipt" if is_paid else "Assessment",
                    "status": "Paid" if is_paid else "Ready",
                    "current_step": "Official Receipt" if is_paid else "Assessment",
                    "record_type": "payment",
                    "transaction_date": ((receipt or {}).get("issued_at") or "")[:10] or datetime.now(timezone.utc).date().isoformat(),
                    "remarks": "Payment confirmed and Official Receipt issued." if is_paid else "Assessment completed and queued for Treasury workflow.",
                    "created_by": config["actor"].get("id"),
                },
                prefer="return=minimal",
            )

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
                "assessmentReview": sum(1 for record in records if record["currentStep"] == "Assessment"),
                "readyForPayment": sum(1 for record in records if record["currentStep"] == "Payment"),
                "receiptsIssued": sum(1 for record in records if record["orStatus"] == "Issued"),
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
            export_type = self.first_query_value(params, "type", "reports").lower()
            rows = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "*", "deleted_at": "is.null", "order": "transaction_date.desc,created_at.desc", "limit": "1000"}),
            ) or []
            records = [self.format_treasury_record(row) for row in rows]
            search = self.first_query_value(params, "search", "").lower()
            status_filter = self.first_query_value(params, "status", "")
            date_from = self.first_query_value(params, "dateFrom", "")
            date_to = self.first_query_value(params, "dateTo", "")
            step_filter = self.first_query_value(params, "step", "")
            method_filter = self.first_query_value(params, "method", "")
            report_type_filter = self.first_query_value(params, "reportType", "")

            def in_date_range(record):
                record_date = record.get("transactionDate") or ""
                return (not date_from or record_date >= date_from) and (not date_to or record_date <= date_to)

            if export_type == "processing":
                title = "Treasury Processing Queue"
                headers = ["Application No.", "Applicant", "Business Name", "Amount Due", "Current Step", "SOA Status", "Payment Status", "OR Status", "Action"]
                filtered = []
                for record in records:
                    haystack = f"{record.get('applicationNo')} {record.get('applicant')} {record.get('businessName')}".lower()
                    statuses = {record.get("status"), record.get("soaStatus"), record.get("paymentStatus"), record.get("orStatus")}
                    if search and search not in haystack:
                        continue
                    if step_filter and record.get("currentStep") != step_filter:
                        continue
                    if status_filter and status_filter not in statuses:
                        continue
                    if not in_date_range(record):
                        continue
                    filtered.append(record)
                data = [[record.get("applicationNo"), record.get("applicant"), record.get("businessName"), f"PHP {record.get('amount', 0):,.2f}", record.get("currentStep"), record.get("soaStatus"), record.get("paymentStatus"), record.get("orStatus"), record.get("actionLabel")] for record in filtered]
                total_amount = self.money(sum(self.safe_float(record.get("amount"), 0) for record in filtered))
                filename = "treasury-processing-queue.pdf"
            elif export_type == "payments":
                title = "Treasury Payment Records"
                headers = ["OR No.", "Payment Date", "Applicant", "Business Name", "Amount", "Payment Method", "Status", "Cashier"]
                filtered = []
                for record in records:
                    payment_method = record.get("paymentMethod") or record.get("method") or ""
                    haystack = f"{record.get('orNo')} {record.get('applicant')} {record.get('businessName')}".lower()
                    if search and search not in haystack:
                        continue
                    if status_filter and record.get("status") != status_filter:
                        continue
                    if method_filter and payment_method != method_filter:
                        continue
                    if not in_date_range(record):
                        continue
                    filtered.append(record)
                data = [[record.get("orNo") or "-", record.get("transactionDate") or "-", record.get("applicant"), record.get("businessName"), f"PHP {record.get('amount', 0):,.2f}", record.get("paymentMethod") or record.get("method") or "-", record.get("status"), record.get("cashier") or "Treasury Staff"] for record in filtered]
                total_amount = self.money(sum(self.safe_float(record.get("amount"), 0) for record in filtered))
                filename = "treasury-payment-records.pdf"
            elif export_type == "receipts":
                title = "Treasury Official Receipts"
                headers = ["OR No.", "Applicant", "Business Name", "Payment Date", "Amount", "Receipt Status", "Issued By"]
                filtered = []
                for record in records:
                    haystack = f"{record.get('orNo')} {record.get('applicant')} {record.get('businessName')}".lower()
                    if record.get("orStatus") != "Issued" and not record.get("orNo"):
                        continue
                    if search and search not in haystack:
                        continue
                    if status_filter and record.get("orStatus") != status_filter:
                        continue
                    if not in_date_range(record):
                        continue
                    filtered.append(record)
                data = [[record.get("orNo") or "-", record.get("applicant"), record.get("businessName"), record.get("transactionDate") or "-", f"PHP {record.get('amount', 0):,.2f}", record.get("orStatus"), record.get("cashier") or "Treasury Staff"] for record in filtered]
                total_amount = self.money(sum(self.safe_float(record.get("amount"), 0) for record in filtered))
                filename = "treasury-official-receipts.pdf"
            else:
                title = "Treasury Reports"
                headers = ["Report ID", "Report Type", "Covered Period", "Total Amount", "Status", "Generated By", "Generated On"]
                report_rows = []
                for record in records:
                    current_step = record.get("currentStep")
                    report_type = "Official Receipts Report" if current_step == "Official Receipt" else "Payment Summary" if current_step == "Payment" else "Treasury Transactions" if current_step == "SOA Generation" else "Collection Summary"
                    report_status = "Completed" if record.get("status") in {"Paid", "Accepted"} else "Processing" if record.get("status") in {"Ready", "Generated"} else "Pending"
                    report = {
                        "id": f"RPT-{record.get('applicationNo') or record.get('id') or ''}",
                        "reportType": report_type,
                        "coveredPeriod": record.get("transactionDate") or (record.get("createdAt") or "")[:10] or "-",
                        "totalAmount": record.get("amount") or 0,
                        "status": report_status,
                        "generatedBy": "Treasury Staff",
                        "generatedOn": (record.get("createdAt") or "")[:10] or record.get("transactionDate") or "-",
                    }
                    haystack = f"{report['id']} {report['generatedBy']}".lower()
                    report_date = "" if report["coveredPeriod"] == "-" else report["coveredPeriod"]
                    if search and search not in haystack:
                        continue
                    if report_type_filter and report["reportType"] != report_type_filter:
                        continue
                    if status_filter and report["status"] != status_filter:
                        continue
                    if date_from and report_date < date_from:
                        continue
                    if date_to and report_date > date_to:
                        continue
                    report_rows.append(report)
                data = [[report["id"], report["reportType"], report["coveredPeriod"], f"PHP {report['totalAmount']:,.2f}", report["status"], report["generatedBy"], report["generatedOn"]] for report in report_rows]
                total_amount = self.money(sum(self.safe_float(report.get("totalAmount"), 0) for report in report_rows))
                filename = "treasury-reports.pdf"

            if not data:
                self.send_json({"error": "No records available for export."}, status=404)
                return
            self.send_binary_download(
                self.pdf_report(title, headers, data, {"Total Records": len(data), "Total Amount": f"PHP {total_amount:,.2f}"}),
                filename,
                "application/pdf",
            )
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to export treasury report.")
        except ValueError as error:
            self.send_json({"error": str(error) or "No records available for export."}, status=404)

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

    def assert_treasury_transition(self, current, payload):
        current_step = current.get("current_step") or current.get("step") or "Assessment"
        current_status = current.get("status") or "Pending"
        next_step = payload.get("current_step") or payload.get("step") or current_step
        next_status = payload.get("status") or current_status
        same_stage = next_step == current_step

        allowed = {
            ("Assessment", "SOA Generation", "Ready"),
            ("SOA Generation", "Payment", "Generated"),
            ("Payment", "Official Receipt", "Ready"),
            ("Official Receipt", "Official Receipt", "Paid"),
            ("Official Receipt", "Official Receipt", "Accepted"),
        }
        if same_stage and next_status == current_status:
            return
        if (current_step, next_step, next_status) not in allowed:
            raise ValueError("This action does not match the current treasury workflow step.")
        if current_step == "Assessment" and current_status not in {"Pending", "Ready", "Not Generated"}:
            raise ValueError("Assessment must be ready before SOA generation.")
        if current_step == "SOA Generation" and current_status != "Ready":
            raise ValueError("SOA must be ready before it can be generated.")
        if current_step == "Payment" and current_status != "Generated":
            raise ValueError("SOA must be generated before payment can be accepted.")
        if next_status == "Paid" and not (payload.get("or_no") or "").strip():
            raise ValueError("Official Receipt number is required before issuing the OR.")

    def create_treasury_record(self):
        config = self.ensure_treasury_request()
        if not config:
            return
        try:
            record = self.validate_treasury_payload(self.read_json_body())
            if record["current_step"] != "Assessment" or record["status"] not in {"Pending", "Ready", "Not Generated"}:
                self.send_json({"error": "New treasury records must start at the Assessment step."}, status=400)
                return
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
            existing_rows = self.service_rest_request(
                config,
                "treasury_records",
                query=urlencode({"select": "*", "id": f"eq.{record_id}", "deleted_at": "is.null", "limit": 1}),
            ) or []
            if not existing_rows:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return
            self.assert_treasury_transition(existing_rows[0], payload)
            if payload["or_no"] and payload["status"] not in {"Paid", "Accepted"}:
                self.send_json({"error": "Official Receipt number can only be saved when the OR is issued."}, status=400)
                return
            application = self.find_application_by_reference(config["supabase_url"], config["supabase_service_key"], payload["application_no"])
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
                    query=urlencode({"select": "id,application_id", "receipt_number": f"eq.{payload['or_no']}", "limit": 5}),
                ) or []
                application_id = application.get("id") if application else None
                duplicate_receipts = [
                    receipt
                    for receipt in duplicate_receipts
                    if not application_id or receipt.get("application_id") != application_id
                ]
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

    def advance_treasury_record(self, record_id):
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
            body = self.read_json_body()
            current_step = record.get("current_step") or record.get("step") or "Assessment"
            now = utc_now_iso()
            today = datetime.now(timezone.utc).date().isoformat()
            payload = {
                "application_no": record.get("application_no"),
                "or_no": record.get("or_no") or "",
                "applicant": record.get("applicant"),
                "business_name": record.get("business_name"),
                "amount": record.get("amount") or 0,
                "step": current_step,
                "current_step": current_step,
                "status": record.get("status") or "Pending",
                "record_type": record.get("record_type") or "payment",
                "transaction_date": record.get("transaction_date") or today,
                "remarks": record.get("remarks") or "",
                "updated_at": now,
            }

            if current_step == "Assessment":
                payload.update({"step": "SOA Generation", "current_step": "SOA Generation", "status": "Ready", "remarks": "Assessment completed; SOA is ready to generate."})
            elif current_step == "SOA Generation":
                payload.update({"step": "Payment", "current_step": "Payment", "status": "Generated", "remarks": "Statement of Account generated; payment is ready for acceptance."})
            elif current_step == "Payment":
                payload.update({"step": "Official Receipt", "current_step": "Official Receipt", "status": "Ready", "transaction_date": today, "remarks": "Payment accepted; Official Receipt is ready for issuance."})
            elif current_step == "Official Receipt":
                or_number = (body.get("officialReceiptNumber") or record.get("or_no") or "").strip()
                payment_date = (body.get("paymentDate") or record.get("transaction_date") or today).strip()
                amount_paid = self.safe_float(body.get("amountPaid"), self.safe_float(record.get("amount"), 0))
                remarks = (body.get("remarks") or record.get("remarks") or "Official Receipt issued.").strip()
                if not or_number:
                    self.send_json({"error": "Official Receipt number is required before issuing the OR."}, status=400)
                    return
                if amount_paid < self.safe_float(record.get("amount"), 0):
                    self.send_json({"error": "Amount paid must match or cover the total amount due."}, status=400)
                    return
                application = self.find_application_by_reference(config["supabase_url"], config["supabase_service_key"], record.get("application_no"))
                application_id = application.get("id") if application else None
                duplicate_records = self.service_rest_request(
                    config,
                    "treasury_records",
                    query=urlencode({"select": "id", "or_no": f"eq.{or_number}", "id": f"neq.{record_id}", "deleted_at": "is.null", "limit": 1}),
                ) or []
                duplicate_receipts = self.service_rest_request(
                    config,
                    "official_receipts",
                    query=urlencode({"select": "id,application_id", "receipt_number": f"eq.{or_number}", "limit": 5}),
                ) or []
                duplicate_receipts = [
                    receipt
                    for receipt in duplicate_receipts
                    if not application_id or receipt.get("application_id") != application_id
                ]
                if duplicate_records or duplicate_receipts:
                    self.send_json({"error": "This Official Receipt number is already used."}, status=400)
                    return
                payload.update({"or_no": or_number, "amount": amount_paid, "step": "Official Receipt", "current_step": "Official Receipt", "status": "Paid", "transaction_date": payment_date, "remarks": remarks})
            else:
                self.send_json({"error": "This treasury record is not in a processable workflow step."}, status=400)
                return

            self.assert_treasury_transition(record, payload)
            updated = self.service_rest_request(
                config,
                "treasury_records",
                method="PATCH",
                payload=payload,
                query=urlencode({"id": f"eq.{record_id}", "deleted_at": "is.null"}),
                prefer="return=representation",
            ) or []
            if not updated:
                self.send_json({"error": "Treasury record not found."}, status=404)
                return
            if payload["status"] == "Paid":
                self.ensure_treasury_completion_state(config, updated[0])
            self.create_service_audit_log(config["supabase_url"], config["supabase_service_key"], "treasury_workflow_advanced", actor=config["actor"], entity_type="treasury_record", entity_id=record_id, details={"from": current_step, "to": payload["current_step"], "status": payload["status"]})
            self.send_json({"message": "Treasury workflow advanced.", "record": self.format_treasury_record(updated[0])})
        except ValueError as error:
            self.send_json({"error": str(error)}, status=400)
        except (HTTPError, json.JSONDecodeError, URLError, TimeoutError) as error:
            self.treasury_error(error, "Unable to advance treasury workflow.")

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

