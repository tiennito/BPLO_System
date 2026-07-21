import unittest
from pathlib import Path
from urllib.error import URLError

from backend.auth import AuthMixin


ROOT = Path(__file__).resolve().parents[1]
LOGIN_SCRIPT = ROOT / "static" / "features" / "login.js"


class AuthNetworkHarness(AuthMixin):
    def __init__(self):
        self.headers = {"Authorization": "Bearer test-token"}
        self.response = None

    def get_admin_api_config(self):
        return "https://example.supabase.co", "anon-key", "service-key", "admin@example.com"

    def get_session_user(self, *_args):
        raise URLError(OSError(10013, "An attempt was made to access a socket in a way forbidden by its access permissions"))

    def send_json(self, payload, status=200):
        self.response = (status, payload)


class AuthNetworkErrorTests(unittest.TestCase):
    def test_profile_endpoint_hides_internal_socket_error(self):
        handler = AuthNetworkHarness()
        handler.get_current_user_profile()

        self.assertEqual(handler.response[0], 503)
        self.assertEqual(
            handler.response[1]["error"],
            "The account service is temporarily unavailable. Please try again in a moment.",
        )
        self.assertNotIn("WinError", handler.response[1]["error"])
        self.assertNotIn("socket", handler.response[1]["error"].lower())

    def test_authenticated_endpoint_handles_connection_failure(self):
        handler = AuthNetworkHarness()
        result = handler.ensure_authenticated_request()

        self.assertIsNone(result)
        self.assertEqual(handler.response[0], 503)

    def test_login_client_sanitizes_browser_network_errors(self):
        script = LOGIN_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("friendlyLoginError", script)
        self.assertIn("urlopen error|winerror|socket|failed to fetch|networkerror", script)


if __name__ == "__main__":
    unittest.main()
