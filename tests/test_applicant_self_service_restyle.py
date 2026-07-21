import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "static" / "templates" / "applicant"
STYLE_PATH = ROOT / "static" / "styles" / "applicant_self_service.css"
SCRIPT_PATH = ROOT / "static" / "features" / "applicant_self_service.js"


class TemplateParser(HTMLParser):
    pass


class ApplicantSelfServiceRestyleTests(unittest.TestCase):
    def read_template(self, name):
        return (TEMPLATE_DIR / name).read_text(encoding="utf-8")

    def test_templates_are_valid_and_share_the_new_visual_shell(self):
        for name in ("permits.html", "documents.html", "profile.html"):
            html = self.read_template(name)
            parser = TemplateParser()
            parser.feed(html)
            parser.close()
            self.assertIn("applicant-self-service-page", html)
            self.assertIn("/styles/applicant_self_service.css?v=1", html)
            self.assertIn("BPLO Permit System", html)
            self.assertIn("data-applicant-initials", html)
            self.assertIn("footer-shield", html)

    def test_permits_and_documents_keep_required_data_hooks(self):
        permits = self.read_template("permits.html")
        documents = self.read_template("documents.html")
        for hook in (
            "data-permit-search",
            "data-permit-status-filter",
            "data-permit-type-filter",
            "data-application-type-filter",
            "data-permit-sort",
            "data-permits-body",
        ):
            self.assertIn(hook, permits)
        for hook in (
            "data-document-search",
            "data-document-application-filter",
            "data-document-category-filter",
            "data-document-status-filter",
            "data-document-date-filter",
            "data-documents-body",
            "data-clear-document-filters",
            "data-apply-document-filters",
            "data-document-guidelines",
        ):
            self.assertIn(hook, documents)

    def test_profile_keeps_all_editable_and_read_only_fields(self):
        profile = self.read_template("profile.html")
        for name in (
            "firstName", "middleName", "lastName", "suffix", "email",
            "contactNumber", "birthdate", "sex", "civilStatus", "houseNumber",
            "street", "barangay", "municipalityCity", "province", "postalCode",
            "userId", "role", "accountStatus", "verifiedEmail",
        ):
            self.assertIn(f'name="{name}"', profile)
        self.assertIn("profile-photo-copy", profile)
        self.assertIn("data-profile-photo-upload", profile)
        self.assertIn("data-profile-photo-remove", profile)

    def test_styles_are_scoped_and_responsive(self):
        css = STYLE_PATH.read_text(encoding="utf-8")
        self.assertIn(".applicant-self-service-page .records-card", css)
        self.assertIn(".record-status-badge", css)
        self.assertIn(".profile-settings-grid", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn("grid-template-columns: 1fr", css)

    def test_script_renders_reference_actions_and_filter_controls(self):
        script = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('data-lucide="eye"', script)
        self.assertIn('data-lucide="download"', script)
        self.assertIn("record-status-badge", script)
        self.assertIn("[data-clear-document-filters]", script)
        self.assertIn("[data-apply-document-filters]", script)
        self.assertIn("[data-document-guidelines]", script)
        self.assertIn("profileInitials", script)


if __name__ == "__main__":
    unittest.main()
