import unittest
from pathlib import Path

from backend.applicant_routes import ApplicantRoutesMixin


ROOT = Path(__file__).resolve().parents[1]
PRINT_TEMPLATE = ROOT / "static" / "templates" / "applicant" / "application_print.html"
PRINT_STYLES = ROOT / "static" / "styles" / "application_print.css"
BUSINESS_TEMPLATE = ROOT / "static" / "templates" / "applicant" / "business_information.html"
APPLICANT_SCRIPT = ROOT / "static" / "features" / "applicant.js"
PRINT_SCRIPT = ROOT / "static" / "features" / "application_print.js"


class PrintRouteHarness(ApplicantRoutesMixin):
    def __init__(self, actor_id="owner", role="applicant", applicant_id="owner"):
        self.actor = {"id": actor_id, "email": f"{actor_id}@example.com", "app_metadata": {"role": role}}
        self.profile = {"role": role, "status": "active"}
        self.application = {
            "id": "application-id",
            "applicant_id": applicant_id,
            "status": "Draft",
            "progress": "Draft",
            "business_info": {"business_name": "Sample Shop", "first_name": "Ana", "last_name": "Reyes"},
            "permit_snapshot": {"permitName": "Business Permit", "permitCode": "BPLO 01"},
            "created_at": "2026-07-17T01:00:00Z",
            "updated_at": "2026-07-17T02:00:00Z",
        }
        self.response = None
        self.audit_actions = []
        self.headers = {}
        self.client_address = ("127.0.0.1", 1)

    def ensure_authenticated_request(self):
        return "https://example.supabase.co", "service-key", self.actor

    def get_profile_by_auth_user_id(self, *_args):
        return self.profile

    def supabase_rest_request(self, _url, _key, table, _query, **_kwargs):
        return [self.application] if table == "applications" else []

    def load_optional_applicant_profile(self, *_args):
        return {}

    def create_service_audit_log(self, _url, _key, action, **_kwargs):
        self.audit_actions.append(action)
        return True

    def send_json(self, payload, status=200):
        self.response = (status, payload)

    def handle_rest_error(self, _error, fallback):
        return fallback


class ApplicationPrintAuthorizationTests(unittest.TestCase):
    def test_owner_can_load_print_data_without_mutating_application(self):
        handler = PrintRouteHarness()
        original = dict(handler.application)
        handler.get_application_print_data("application-id")
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[1]["application"]["businessInfo"]["business_name"], "Sample Shop")
        self.assertEqual(handler.application, original)
        self.assertEqual(handler.audit_actions, ["APPLICATION_FORM_PRINTED"])

    def test_unrelated_applicant_is_forbidden(self):
        handler = PrintRouteHarness(actor_id="other-user", applicant_id="owner")
        handler.get_application_print_data("application-id")
        self.assertEqual(handler.response[0], 403)
        self.assertEqual(handler.response[1]["error"], "You are not authorized to print this application.")
        self.assertEqual(handler.audit_actions, [])

    def test_bplo_admin_can_load_print_data(self):
        handler = PrintRouteHarness(actor_id="staff", role="bplo_admin", applicant_id="owner")
        handler.get_application_print_data("application-id")
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.response[1]["viewerRole"], "bplo_admin")

    def test_same_preview_can_skip_duplicate_audit_entry(self):
        handler = PrintRouteHarness()
        handler.headers = {"X-Print-Audit": "0", "X-Print-Session": "same-preview"}
        handler.get_application_print_data("application-id")
        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.audit_actions, [])


class ApplicationPrintArtifactTests(unittest.TestCase):
    def test_print_view_has_draft_watermark_and_scoped_a4_styles(self):
        template = PRINT_TEMPLATE.read_text(encoding="utf-8")
        styles = PRINT_STYLES.read_text(encoding="utf-8")
        self.assertIn("draft-watermark", template)
        self.assertIn("@media print", styles)
        self.assertIn("size: A4 portrait", styles)
        self.assertIn(".no-print", styles)

    def test_print_action_waits_for_latest_draft_save(self):
        template = BUSINESS_TEMPLATE.read_text(encoding="utf-8")
        script = APPLICANT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("data-print-application-form", template)
        self.assertIn("await saveBusinessDraft({ throwOnError: true })", script)
        self.assertIn("Your latest changes could not be saved", script)

    def test_print_preview_marks_a_session_after_a_successful_load(self):
        script = PRINT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"X-Print-Audit": hasLoggedThisPreview ? "0" : "1"', script)
        self.assertIn('window.sessionStorage.setItem(auditSessionKey, "1")', script)

    def test_print_mapping_uses_current_business_form_field_names(self):
        script = PRINT_SCRIPT.read_text(encoding="utf-8")
        for field_name in (
            "date_of_application",
            "dti_registration_no",
            "registered_contact_number",
            "registered_email",
            "business_type",
            "capital_investment",
        ):
            self.assertIn(field_name, script)


if __name__ == "__main__":
    unittest.main()
