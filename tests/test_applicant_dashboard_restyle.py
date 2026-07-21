import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_TEMPLATE = ROOT / "static" / "templates" / "applicant" / "dashboard.html"
DASHBOARD_STYLES = ROOT / "static" / "styles" / "applicant_dashboard.css"
APPLICANT_SCRIPT = ROOT / "static" / "features" / "applicant.js"


class ApplicantDashboardRestyleTests(unittest.TestCase):
    def test_dashboard_template_is_valid_and_keeps_workflow_hooks(self):
        template = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
        parser = HTMLParser()
        parser.feed(template)

        self.assertIn('class="applicant-dashboard-page"', template)
        self.assertIn('/styles/applicant_dashboard.css?v=4', template)
        self.assertIn('data-start-latest-renewal', template)
        self.assertIn('data-renewal-notice', template)
        self.assertIn('data-renewal-drawer', template)
        self.assertIn('data-notification-toggle', template)

    def test_profile_controls_form_one_accessible_account_menu(self):
        template = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
        profile_button_start = template.index('class="profile-button"')
        profile_button_end = template.index("</button>", profile_button_start)
        profile_button = template[profile_button_start:profile_button_end]

        self.assertIn('aria-haspopup="menu"', profile_button)
        self.assertIn('aria-label="Open account menu"', profile_button)
        self.assertIn('data-applicant-initials', profile_button)
        self.assertNotIn('Profile</span>', profile_button)
        self.assertNotIn('profile-chevron', profile_button)
        self.assertIn('View/Edit Profile', template)
        self.assertIn('role="menu"', template)
        self.assertNotIn('<span class="avatar" data-applicant-initials', template[profile_button_end:])

        notification_start = template.index('class="notification-menu"')
        self.assertLess(notification_start, profile_button_start)

    def test_reference_sections_and_descriptions_are_present(self):
        template = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
        for text in (
            "Your Information",
            "Quick Actions",
            "New Business Permit",
            "View All Permits",
            "My Documents",
            "Start Renewal",
            "Recent Business Permits",
        ):
            self.assertIn(text, template)

    def test_new_styles_are_scoped_to_dashboard(self):
        styles = DASHBOARD_STYLES.read_text(encoding="utf-8")
        self.assertIn(".applicant-dashboard-page .topbar", styles)
        self.assertIn(".applicant-dashboard-page .info-grid", styles)
        self.assertIn(".applicant-dashboard-page .action-grid", styles)
        self.assertIn(".applicant-dashboard-page .permits-table-wrap", styles)
        self.assertIn("@media (max-width: 680px)", styles)

    def test_quick_actions_use_five_equal_desktop_columns(self):
        styles = DASHBOARD_STYLES.read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr));", styles)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", styles)
        self.assertIn("grid-template-columns: 1fr;", styles)

    def test_dynamic_permit_rows_have_status_and_progress_ui(self):
        script = APPLICANT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("permit-status--${escapeHtml(statusClass)}", script)
        self.assertIn("permit-progress-track", script)
        self.assertIn("permit-row-actions", script)
        self.assertIn("formatDashboardInitials", script)


if __name__ == "__main__":
    unittest.main()
