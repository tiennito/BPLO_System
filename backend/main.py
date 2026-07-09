from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .admin_routes import AdminRoutesMixin
from .applicant_routes import ApplicantRoutesMixin
from .assessment_service import AssessmentServiceMixin
from .auth import AuthMixin
from .config import HOST, PORT
from .department_routes import DepartmentRoutesMixin
from .notification_service import NotificationServiceMixin
from .ocr_service import OCRServiceMixin
from .permit_service import PermitServiceMixin
from .supabase_client import SupabaseClientMixin
from .treasury_routes import TreasuryRoutesMixin
from .utils import CoreHandlerMixin


class AppHandler(
    CoreHandlerMixin,
    AuthMixin,
    SupabaseClientMixin,
    OCRServiceMixin,
    NotificationServiceMixin,
    PermitServiceMixin,
    AssessmentServiceMixin,
    AdminRoutesMixin,
    ApplicantRoutesMixin,
    DepartmentRoutesMixin,
    TreasuryRoutesMixin,
    SimpleHTTPRequestHandler,
):
    """HTTP handler composed from focused backend modules."""


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


if __name__ == "__main__":
    main()
