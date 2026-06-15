from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HOST = "127.0.0.1"
PORT = 8000
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PAGE_ROUTES = {
    "/": "/templates/index.html",
    "/login": "/templates/index.html",
    "/index.html": "/templates/index.html",
    "/register": "/templates/register.html",
    "/signup": "/templates/register.html",
    "/register.html": "/templates/register.html",
}


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        self.path = PAGE_ROUTES.get(self.path, self.path)
        super().do_GET()


def main():
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"BPLO app running at http://{HOST}:{PORT}")
    print(f"Login:    http://{HOST}:{PORT}/")
    print(f"Register: http://{HOST}:{PORT}/register")
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
