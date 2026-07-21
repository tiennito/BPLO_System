import unittest
from pathlib import Path

from backend.applicant_routes import ApplicantRoutesMixin


ROOT = Path(__file__).resolve().parents[1]
APPLICANT_SCRIPT = ROOT / "static" / "features" / "applicant.js"
SELF_SERVICE_SCRIPT = ROOT / "static" / "features" / "applicant_self_service.js"
PROFILE_TEMPLATE = ROOT / "static" / "templates" / "applicant" / "profile.html"
PROFILE_MIGRATION = ROOT / "database" / "19. applicant_profile_source_of_truth.sql"


class ApplicantProfileHarness(ApplicantRoutesMixin):
    def __init__(self, request_payload=None, role="applicant"):
        self.user = {
            "id": "user-1",
            "email": "old@example.com",
            "app_metadata": {"role": role},
            "email_confirmed_at": "2026-01-01T00:00:00Z",
        }
        self.profile = {
            "id": "profile-1",
            "auth_user_id": "user-1",
            "role": role,
            "status": "active",
            "first_name": "Old",
            "middle_name": "Middle",
            "last_name": "Name",
            "suffix": "",
            "email": "old@example.com",
            "contact_number": "09171234567",
        }
        self.applicant = {
            "id": "applicant-1",
            "user_id": "user-1",
            "first_name": "Old",
            "first_name_raw": "Old",
            "middle_name": "Middle",
            "last_name": "Name",
            "suffix": "",
            "email": "old@example.com",
            "contact_number": "09171234567",
            "house_number": "12",
            "address_street": "Rizal Street",
            "address_barangay": "Poblacion",
            "address_city": "Victoria",
            "address_province": "Laguna",
            "postal_code": "4011",
            "updated_at": "2026-07-17T01:00:00Z",
        }
        self.request_payload = request_payload or {
            "firstName": "Updated",
            "middleName": "Middle",
            "lastName": "Name",
            "suffix": "",
            "email": "old@example.com",
            "contactNumber": "09171234567",
            "houseNumber": "12",
            "street": "Rizal Street",
            "barangay": "Poblacion",
            "municipalityCity": "Victoria",
            "province": "Laguna",
            "postalCode": "4011",
            "updatedAt": "2026-07-17T01:00:00Z",
        }
        self.response = None
        self.audit = None
        self.return_updated_row = True

    def ensure_applicant_request(self, _label):
        return "https://example.supabase.co", "service-key", self.user

    def read_json_body(self):
        return self.request_payload

    def get_profile_by_auth_user_id(self, *_args):
        return self.profile

    def load_optional_applicant_profile(self, *_args):
        return self.applicant

    def get_profile_by_email(self, *_args):
        return None

    def supabase_rest_request(self, _url, _key, table, _query=None, method="GET", payload=None, **_kwargs):
        if table == "applicants" and method == "PATCH":
            if not self.return_updated_row:
                return []
            self.applicant.update(payload or {})
            return [dict(self.applicant)]
        return []

    def update_profile_record(self, _url, _key, _profile_id, payload):
        self.profile.update(payload)
        self.profile["updated_at"] = "2026-07-17T02:00:00Z"
        return dict(self.profile)

    def create_service_audit_log(self, _url, _key, action, **kwargs):
        self.audit = (action, kwargs)
        return True

    def create_notification(self, *_args, **_kwargs):
        return True

    def send_json(self, payload, status=200):
        self.response = (status, payload)

    def handle_rest_error(self, _error, fallback):
        return fallback


class ApplicantProfileSynchronizationTests(unittest.TestCase):
    def test_success_updates_primary_applicant_row_and_returns_latest_profile(self):
        handler = ApplicantProfileHarness()
        handler.update_applicant_profile_settings()

        self.assertEqual(handler.response[0], 200)
        self.assertTrue(handler.response[1]["success"])
        self.assertEqual(handler.response[1]["source"], "applicants")
        self.assertEqual(handler.response[1]["profile"]["firstName"], "Updated")
        self.assertEqual(handler.applicant["first_name_raw"], "Updated")
        self.assertEqual(handler.audit[0], "APPLICANT_PROFILE_UPDATED")
        self.assertIn("firstName", handler.audit[1]["details"]["changedFields"])

    def test_partial_update_preserves_unchanged_fields(self):
        handler = ApplicantProfileHarness({
            "contactNumber": "09179998888",
            "updatedAt": "2026-07-17T01:00:00Z",
        })
        handler.update_applicant_profile_settings()

        self.assertEqual(handler.response[0], 200)
        self.assertEqual(handler.applicant["contact_number"], "09179998888")
        self.assertEqual(handler.applicant["first_name_raw"], "Old")
        self.assertEqual(handler.applicant["address_barangay"], "Poblacion")

    def test_stale_profile_update_is_rejected(self):
        handler = ApplicantProfileHarness({
            "firstName": "Conflict",
            "updatedAt": "2026-07-16T01:00:00Z",
        })
        handler.update_applicant_profile_settings()

        self.assertEqual(handler.response[0], 409)
        self.assertEqual(handler.applicant["first_name_raw"], "Old")
        self.assertIsNone(handler.audit)

    def test_unauthorized_role_cannot_update_applicant_profile(self):
        handler = ApplicantProfileHarness(role="bplo_admin")
        handler.update_applicant_profile_settings()

        self.assertEqual(handler.response[0], 403)
        self.assertEqual(handler.response[1]["error"], "You are not authorized to update this profile.")

    def test_zero_updated_rows_never_returns_false_success(self):
        handler = ApplicantProfileHarness()
        handler.return_updated_row = False
        handler.update_applicant_profile_settings()

        self.assertEqual(handler.response[0], 500)
        self.assertFalse(handler.response[1].get("success", False))
        self.assertIsNone(handler.audit)

    def test_invalid_postal_code_is_rejected(self):
        handler = ApplicantProfileHarness()
        with self.assertRaisesRegex(ValueError, "Postal code"):
            handler.validate_applicant_profile_payload(
                {"postalCode": "40A1"},
                handler.format_applicant_profile_settings(handler.user, handler.profile, handler.applicant),
            )


class ApplicantProfileArtifactTests(unittest.TestCase):
    def test_dashboard_and_application_prefill_use_profile_api(self):
        script = APPLICANT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('applicantApi("/applicant/api/profile")', script)
        self.assertNotIn('.from("applicants")', script)
        self.assertIn("PROFILE_UPDATE_SIGNAL_KEY", script)

    def test_success_modal_and_refresh_flow_are_present(self):
        script = SELF_SERVICE_SCRIPT.read_text(encoding="utf-8")
        template = PROFILE_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("showProfileSuccessModal", script)
        self.assertIn('await api("/applicant/api/profile")', script)
        self.assertIn("Your profile information has been updated successfully.", template)
        self.assertNotIn("setTimeout(redirectToApplicantHome", script)

    def test_profile_migration_adds_supported_fields_and_safe_update_policy(self):
        migration = PROFILE_MIGRATION.read_text(encoding="utf-8")
        for column in ("birthdate", "sex", "civil_status", "house_number", "profile_photo_url"):
            self.assertIn(f"add column if not exists {column}", migration)
        self.assertIn("with check ((select auth.uid()) = user_id)", migration)


if __name__ == "__main__":
    unittest.main()
