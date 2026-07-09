from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.parse import quote
import json
import os
import re
import uuid

from .config import PAGE_ROUTES, STATIC_DIR

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def normalize_role(value):
    role = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "admin": "bplo_admin",
        "administrator": "bplo_admin",
        "department": "department_office",
        "department_user": "department_office",
        "department_office_user": "department_office",
        "treasury_office": "treasury",
        "treasury_user": "treasury",
        "client": "applicant",
    }
    return aliases.get(role, role)

def profile_status(value):
    status = (value or "active").strip().lower()
    return status if status in {"active", "inactive", "pending", "disabled"} else "active"

def dashboard_path_for_role(role):
    paths = {
        "super_admin": "/admin/dashboard",
        "bplo_admin": "/admin/staff-administrator",
        "department_office": "/department/dashboard",
        "treasury": "/treasury/dashboard",
        "applicant": "/applicant/dashboard",
    }
    return paths.get(normalize_role(role))

def slugify_key(value):
    normalized = []
    previous_was_separator = False
    for character in (value or "").strip().lower():
        if character.isalnum():
            normalized.append(character)
            previous_was_separator = False
        elif not previous_was_separator:
            normalized.append("_")
            previous_was_separator = True
    return "".join(normalized).strip("_")

def department_key_from_name(name):
    key = slugify_key(name)
    for suffix in ("_office", "_department"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    seeded_aliases = {
        "health_sanitary": "health",
        "zoning_mpdc": "zoning",
        "fire": "fire",
        "engineering": "engineering",
    }
    return seeded_aliases.get(key, key)

def normalize_business_classification_value(value):
    value = (value or "").strip()
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"\s+", " ", value).strip().upper()
    value = re.sub(r"\s*/\s*", " / ", value)
    value = re.sub(r"\s*-\s*", " - ", value)
    return re.sub(r"\s+", " ", value).strip()

def normalize_business_classification_key(value):
    value = normalize_business_classification_value(value).replace("&", " AND ")
    value = re.sub(r"\bBAKE\s+SHOP\b", "BAKESHOP", value)
    value = re.sub(r"\bPHONE\s+CARDS\b", "PHONECARDS", value)
    value = re.sub(r"\bSMALL\s+LOT\b", "SMALLLOT", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def main():
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"BPLO app running at http://{HOST}:{PORT}")
    print("Static assets, CSS, and JS are all served from the same port.")
    print("Press Ctrl+C to stop the server.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()



class CoreHandlerMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        request_path = urlsplit(self.path).path

        evidence_file_match = re.fullmatch(r"/department/evidence/([^/]+)/(view|download)", request_path)
        if evidence_file_match:
            self.stream_department_evidence_file(evidence_file_match.group(1), evidence_file_match.group(2))
            return

        document_file_match = re.fullmatch(r"/attachments/application-documents/([^/]+)/(view|download)", request_path)
        if document_file_match:
            self.stream_application_document_file(document_file_match.group(1), document_file_match.group(2))
            return

        if request_path == "/department/api/me":
            self.get_department_profile()
            return

        if request_path == "/department/api/applications":
            self.list_department_applications()
            return

        workspace_match = re.fullmatch(r"/department/api/applications/([^/]+)/workspace", request_path)
        if workspace_match:
            self.get_department_application_workspace(workspace_match.group(1))
            return

        evidence_match = re.fullmatch(r"/department/api/applications/([^/]+)/evidence", request_path)
        if evidence_match:
            self.list_department_evidence(evidence_match.group(1))
            return

        if request_path.startswith("/department/api/applications/"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 4:
                self.get_department_application(parts[-1])
                return

        if request_path == "/department/api/requirements":
            self.list_department_requirements()
            return

        if request_path == "/department/api/inspections":
            self.list_department_inspections()
            return

        if request_path == "/department/api/reports":
            self.list_department_reports()
            return

        if request_path == "/department/api/reports/export":
            self.export_department_reports()
            return

        if request_path == "/department/api/settings":
            self.get_department_settings()
            return

        if request_path == "/treasury/api/me":
            self.get_treasury_profile()
            return

        if request_path == "/treasury/api/records":
            self.list_treasury_records()
            return

        if request_path == "/treasury/api/payment-queue":
            self.list_treasury_payment_queue()
            return

        if request_path == "/treasury/api/reports/export":
            self.export_treasury_reports()
            return

        if request_path == "/api/me/profile":
            self.get_current_user_profile()
            return

        if request_path == "/api/business-classifications":
            self.list_business_classifications()
            return

        if request_path == "/admin/api/users":
            self.list_admin_users()
            return

        if request_path == "/admin/api/departments":
            self.list_admin_departments()
            return

        if request_path == "/admin/api/audit-logs":
            self.list_admin_audit_logs()
            return

        if request_path == "/admin/api/applications":
            self.list_admin_applications()
            return

        if request_path.startswith("/admin/api/applications/"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 4:
                self.get_admin_application_review(parts[-1])
                return
            if len(parts) == 5 and parts[-1] == "assessment":
                self.get_admin_application_assessment(parts[-2])
                return

        if request_path.startswith("/admin/application-documents/") and request_path.endswith("/preview"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 4:
                self.preview_admin_application_document(parts[2])
                return

        admin_evidence_file_match = re.fullmatch(r"/admin/department-evidence/([^/]+)/(view|download)", request_path)
        if admin_evidence_file_match:
            self.stream_admin_department_evidence_file(admin_evidence_file_match.group(1), admin_evidence_file_match.group(2))
            return

        if request_path == "/admin/api/reports/export":
            self.export_admin_reports()
            return

        if request_path == "/admin/api/business-classifications":
            self.list_admin_business_classifications()
            return

        if request_path == "/admin/api/permits":
            self.list_admin_permits()
            return

        if request_path.startswith("/admin/api/permits/"):
            permit_id = request_path.rsplit("/", 1)[-1]
            self.get_admin_permit(permit_id)
            return

        if request_path == "/applicant/api/permits":
            self.list_applicant_permits()
            return

        if request_path == "/applicant/api/notifications":
            self.list_applicant_notifications()
            return

        if request_path == "/applicant/api/drafts":
            self.list_applicant_drafts()
            return

        draft_match = re.fullmatch(r"/applicant/api/applications/([^/]+)/draft", request_path)
        if draft_match:
            self.get_applicant_draft(draft_match.group(1))
            return

        progress_match = re.fullmatch(r"/applicant/api/applications/([^/]+)/progress", request_path)
        if progress_match:
            self.get_applicant_application_progress(progress_match.group(1))
            return

        if request_path.startswith("/applicant/api/application/") and request_path.endswith("/ocr-fields"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.get_applicant_application_ocr_fields(parts[3])
                return

        if request_path.startswith("/applicant/api/permits/"):
            permit_id = request_path.rsplit("/", 1)[-1]
            self.get_applicant_permit(permit_id)
            return

        if request_path == "/config.js":
            supabase_url = os.getenv("SUPABASE_URL", "")
            supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
            supabase_publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
            admin_email = os.getenv("ADMIN_EMAIL", "")
            payload = (
                "window.APP_CONFIG = "
                f"{{supabaseUrl: {supabase_url!r}, supabaseAnonKey: {supabase_anon_key!r}, "
                f"supabasePublishableKey: {supabase_publishable_key!r}, adminEmail: {admin_email!r}}};"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        if re.fullmatch(r"/admin/staff-administrator/applications/[^/]+/?", request_path):
            self.path = "/templates/staff_administrator/application_review.html"
        else:
            self.path = PAGE_ROUTES.get(request_path, request_path)
        super().do_GET()

    def do_POST(self):
        request_path = urlsplit(self.path).path

        if request_path == "/department/api/requirements":
            self.create_department_requirement()
            return

        evidence_upload_match = re.fullmatch(r"/department/api/applications/([^/]+)/evidence", request_path)
        if evidence_upload_match:
            self.create_department_evidence(evidence_upload_match.group(1))
            return

        if request_path == "/department/api/inspections":
            self.create_department_inspection()
            return

        if request_path == "/department/api/inspection-notifications":
            self.send_department_inspection_notification()
            return

        assessment_match = re.fullmatch(r"/department/api/applications/([^/]+)/assessment", request_path)
        if assessment_match:
            self.upsert_department_assessment(assessment_match.group(1))
            return

        if request_path == "/department/api/remarks":
            self.create_department_remark()
            return

        if request_path == "/department/api/verifications":
            self.create_department_verification()
            return

        if request_path == "/department/api/reports":
            self.create_department_report()
            return

        if request_path == "/department/api/settings":
            self.upsert_department_settings()
            return

        if request_path == "/treasury/api/records":
            self.create_treasury_record()
            return

        if request_path.startswith("/treasury/api/payment-queue/") and request_path.endswith("/confirm"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.confirm_treasury_payment(parts[-2])
                return

        if request_path.startswith("/treasury/api/records/") and request_path.endswith("/print-notify"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.notify_treasury_print_complete(parts[-2])
                return

        if request_path.startswith("/treasury/api/records/") and request_path.endswith("/sync-completion"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.sync_treasury_record_completion(parts[-2])
                return

        if request_path == "/admin/api/users":
            self.create_admin_user()
            return

        if request_path == "/admin/api/departments":
            self.create_admin_department()
            return

        if request_path == "/admin/api/permits":
            self.create_admin_permit()
            return

        if request_path.startswith("/admin/api/applications/"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5 and parts[-1] == "approve-initial-review":
                self.approve_admin_initial_review(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "reject":
                self.reject_admin_application(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "request-revision":
                self.request_admin_application_revision(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "complete-assessment":
                self.complete_admin_assessment(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "finalize":
                self.finalize_admin_application(parts[-2])
                return
            if len(parts) == 5 and parts[-1] == "release-permit":
                self.release_admin_business_permit(parts[-2])
                return

        if request_path == "/admin/api/document-reviews":
            self.create_admin_document_review()
            return

        if request_path == "/admin/api/assessment-items":
            self.create_admin_assessment_item()
            return

        if request_path == "/admin/api/business-classifications":
            self.create_admin_business_classification()
            return

        if request_path == "/applicant/api/applications":
            self.start_applicant_application()
            return

        if request_path == "/applicant/api/application-documents":
            self.update_applicant_application_document()
            return

        if request_path == "/applicant/api/ocr-extract":
            self.extract_applicant_document_ocr()
            return

        if request_path == "/applicant/api/submit-application":
            self.submit_applicant_application()
            return

        if request_path == "/api/audit-logs":
            self.create_audit_log()
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def do_PATCH(self):
        request_path = urlsplit(self.path).path

        if request_path.startswith("/department/api/applications/") and request_path.endswith("/evaluation"):
            parts = request_path.strip("/").split("/")
            if len(parts) == 5:
                self.update_department_application_evaluation(parts[3])
                return

        if request_path.startswith("/department/api/requirements/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_department_requirement(record_id)
            return

        if request_path.startswith("/department/api/inspections/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_department_inspection(record_id)
            return

        if request_path.startswith("/department/api/verifications/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_department_verification(record_id)
            return

        if request_path.startswith("/department/api/reports/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_department_report(record_id)
            return

        if request_path == "/department/api/settings":
            self.upsert_department_settings()
            return

        if request_path.startswith("/treasury/api/records/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.update_treasury_record(record_id)
            return

        if request_path == "/applicant/api/notifications/mark-all-read":
            self.mark_all_applicant_notifications_read()
            return

        if request_path.startswith("/applicant/api/notifications/") and request_path.endswith("/read"):
            notification_id = request_path.strip("/").split("/")[-2]
            self.mark_applicant_notification_read(notification_id)
            return

        if request_path.startswith("/applicant/api/ocr-results/") and request_path.endswith("/corrections"):
            ocr_result_id = request_path.strip("/").split("/")[-2]
            self.update_applicant_ocr_corrections(ocr_result_id)
            return

        draft_match = re.fullmatch(r"/applicant/api/applications/([^/]+)/draft", request_path)
        if draft_match:
            self.save_applicant_draft(draft_match.group(1))
            return

        if request_path.startswith("/admin/api/departments/"):
            department_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_department(department_id)
            return

        if request_path.startswith("/admin/api/permits/"):
            permit_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_permit(permit_id)
            return

        if request_path.startswith("/admin/api/business-classifications/"):
            classification_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_business_classification(classification_id)
            return

        if request_path.startswith("/admin/api/document-reviews/"):
            review_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_document_review(review_id)
            return

        if request_path.startswith("/admin/api/assessment-items/"):
            item_id = request_path.rsplit("/", 1)[-1]
            self.update_admin_assessment_item(item_id)
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def do_DELETE(self):
        request_path = urlsplit(self.path).path

        if request_path.startswith("/department/api/requirements/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_department_record("department_requirement_checklists", record_id, "requirement_deleted")
            return

        if request_path.startswith("/department/api/evidence/"):
            evidence_id = request_path.rsplit("/", 1)[-1]
            self.delete_department_evidence(evidence_id)
            return

        if request_path.startswith("/department/api/inspections/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_department_record("department_inspections", record_id, "inspection_deleted")
            return

        if request_path.startswith("/department/api/remarks/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_department_record("department_remarks", record_id, "remark_deleted")
            return

        if request_path.startswith("/department/api/reports/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_department_record("department_reports", record_id, "report_deleted")
            return

        if request_path == "/department/api/settings":
            self.delete_department_settings()
            return

        if request_path.startswith("/treasury/api/records/"):
            record_id = request_path.rsplit("/", 1)[-1]
            self.soft_delete_treasury_record(record_id)
            return

        if request_path.startswith("/applicant/api/notifications/"):
            notification_id = request_path.rsplit("/", 1)[-1]
            self.delete_applicant_notification(notification_id)
            return

        if request_path.startswith("/admin/api/departments/"):
            department_id = request_path.rsplit("/", 1)[-1]
            self.delete_admin_department(department_id)
            return

        if request_path.startswith("/admin/api/permits/"):
            permit_id = request_path.rsplit("/", 1)[-1]
            self.delete_admin_permit(permit_id)
            return

        if request_path.startswith("/admin/api/assessment-items/"):
            item_id = request_path.rsplit("/", 1)[-1]
            self.delete_admin_assessment_item(item_id)
            return

        self.send_json({"error": "Endpoint not found."}, status=404)

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}

        raw_body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw_body)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file_bytes(self, file_bytes, file_name, content_type, disposition="inline"):
        disposition_name = (file_name or "download").replace('"', "")
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(file_bytes)))
        self.send_header("Content-Disposition", f'{disposition}; filename="{disposition_name}"')
        self.end_headers()
        self.wfile.write(file_bytes)

    def send_text_download(self, text, file_name, content_type):
        body = (text or "").encode("utf-8-sig")
        disposition_name = (file_name or "report.txt").replace('"', "")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{disposition_name}"')
        self.end_headers()
        self.wfile.write(body)

    def content_type_for_filename(self, filename):
        extension = Path(filename or "").suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
        }.get(extension, "application/octet-stream")

    def handle_rest_error(self, error, fallback_message):
        response_body = error.read().decode("utf-8")
        try:
            response_payload = json.loads(response_body)
            message = response_payload.get("message") or response_payload.get("msg") or response_body
        except json.JSONDecodeError:
            message = response_body or fallback_message

        if "permits_permit_code_key" in message or "permit_code" in message:
            return "This permit code already exists. Use a different permit code."

        return message

    def get_query_params(self):
        return parse_qs(urlsplit(self.path).query, keep_blank_values=False)

    def first_query_value(self, params, key, default=""):
        values = params.get(key) or []
        return (values[0] if values else default) or default

    def csv_report(self, headers, rows):
        def escape_cell(value):
            text = "" if value is None else str(value)
            if any(character in text for character in [",", '"', "\n", "\r"]):
                return '"' + text.replace('"', '""') + '"'
            return text

        lines = [",".join(escape_cell(header) for header in headers)]
        for row in rows:
            lines.append(",".join(escape_cell(value) for value in row))
        return "\r\n".join(lines) + "\r\n"

    def html_report(self, title, headers, rows, summary=None):
        def esc(value):
            return (
                str(value if value is not None else "")
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        summary_html = ""
        if summary:
            summary_html = "<dl>" + "".join(f"<div><dt>{esc(key)}</dt><dd>{esc(value)}</dd></div>" for key, value in summary.items()) + "</dl>"
        head = "".join(f"<th>{esc(header)}</th>" for header in headers)
        body = "".join("<tr>" + "".join(f"<td>{esc(value)}</td>" for value in row) + "</tr>" for row in rows)
        return f"""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"UTF-8\" />
    <title>{esc(title)}</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 24px; color: #101828; }}
      h1 {{ margin-bottom: 4px; }}
      .generated {{ color: #667085; margin-bottom: 18px; }}
      table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
      th, td {{ border: 1px solid #d0d5dd; padding: 8px; text-align: left; vertical-align: top; }}
      th {{ background: #f2f4f7; }}
      dl {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 18px 0; }}
      dt {{ color: #667085; font-size: 11px; text-transform: uppercase; }}
      dd {{ margin: 4px 0 0; font-weight: 700; }}
    </style>
  </head>
  <body>
    <h1>{esc(title)}</h1>
    <p class=\"generated\">Generated {esc(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}</p>
    {summary_html}
    <table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
  </body>
</html>"""

    def safe_float(self, value, default=0):
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def money(self, value):
        return round(self.safe_float(value), 2)

    def generate_workflow_number(self, prefix):
        return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:5].upper()}"

    def app_owner_name(self, business_info):
        return (
            business_info.get("owner_name")
            or " ".join(
                part
                for part in [
                    business_info.get("first_name") or business_info.get("firstName"),
                    business_info.get("middle_name") or business_info.get("middleName"),
                    business_info.get("last_name") or business_info.get("lastName"),
                ]
                if part
            ).strip()
            or "-"
        )

    def app_business_name(self, business_info):
        return business_info.get("business_name") or business_info.get("businessName") or "-"

    def app_business_address(self, business_info):
        return (
            business_info.get("business_address")
            or business_info.get("businessAddress")
            or " ".join(
                part
                for part in [
                    business_info.get("unit_street") or business_info.get("unitStreet"),
                    business_info.get("business_barangay") or business_info.get("businessBarangay"),
                    business_info.get("business_municipality") or business_info.get("businessMunicipality"),
                ]
                if part
            ).strip()
            or "-"
        )

