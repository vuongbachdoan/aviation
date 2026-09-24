#!/usr/bin/env python3
"""Local dev server for the SpartansE-V landing page: serves the static files
and runs the same /api/contact handler that Vercel runs from api/contact.py.

Config: environment variables, or a .env file next to this script
(see api/_contact.py for the full list). PORT sets the HTTP port (default 8000).
"""
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
# Only these file types are ever served, so .env / *.py can't leak.
PUBLIC_EXT = {".html", ".js", ".css", ".glb", ".webp", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff2"}


def load_dotenv(path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ.setdefault(key, val)


load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "api"))
import _contact  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def reply(self, status, headers, payload=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def public(self):
        path = urlsplit(self.path).path
        if path == "/":
            return True  # serves index.html
        parts = [p for p in path.split("/") if p]
        if any(p.startswith(".") for p in parts) or Path(path).suffix.lower() not in PUBLIC_EXT:
            self.send_error(404)
            return False
        return True

    def do_GET(self):
        if self.public():
            super().do_GET()

    def do_HEAD(self):
        if self.public():
            super().do_HEAD()

    def do_OPTIONS(self):
        if urlsplit(self.path).path != "/api/contact":
            return self.reply(404, [])
        self.reply(*_contact.preflight(self.headers))

    def do_POST(self):
        if urlsplit(self.path).path != "/api/contact":
            return self.reply(404, [], {"error": "Not found."})
        status, payload, headers = _contact.handle_post(self.headers, self.rfile.read, self.client_address[0])
        self.reply(status, headers, payload)


def main():
    port = int(os.environ.get("PORT", "8000"))
    c = _contact.cfg()
    origins = _contact.allowed_origins()
    print(f"SpartansE-V landing on http://localhost:{port}/")
    print(f"  api access: {', '.join(sorted(origins)) if origins else 'same-origin only (FRONTEND_ORIGIN unset)'}")
    missing = [k for k, v in (("SMTP_USER", c["user"]), ("SMTP_PASS", c["password"]), ("MAIL_TO", c["to"])) if not v]
    if missing:
        print(f"  warning: {', '.join(missing)} not set — the contact form will not send mail", file=sys.stderr)
    else:
        print(f"  contact form: {c['from']} -> {c['to']} via {c['host']}:{c['port']}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
