from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import os


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ENV_FILE = BASE_DIR / ".env"


def load_env():
    if not ENV_FILE.exists():
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()

HOST = os.getenv("APP_HOST", "127.0.0.1")
PORT = int(os.getenv("APP_PORT", "8000"))
PAGE_ROUTES = {
    "/": "/templates/login.html",
    "/login": "/templates/login.html",
    "/login.html": "/templates/login.html",
    "/register": "/templates/register.html",
    "/signup": "/templates/register.html",
    "/register.html": "/templates/register.html",
    "/applicant": "/templates/applicant/dashboard.html",
    "/applicant/": "/templates/applicant/dashboard.html",
    "/applicant/dashboard": "/templates/applicant/dashboard.html",
    "/applicant/dashboard/": "/templates/applicant/dashboard.html",
    "/applicant/dashboard.html": "/templates/applicant/dashboard.html",
}


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        request_path = urlsplit(self.path).path

        if request_path == "/config.js":
            supabase_url = os.getenv("SUPABASE_URL", "")
            supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
            supabase_publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
            payload = (
                "window.APP_CONFIG = "
                f"{{supabaseUrl: {supabase_url!r}, supabaseAnonKey: {supabase_anon_key!r}, "
                f"supabasePublishableKey: {supabase_publishable_key!r}}};"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(payload.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(payload.encode("utf-8"))
            return

        self.path = PAGE_ROUTES.get(request_path, request_path)
        super().do_GET()


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
