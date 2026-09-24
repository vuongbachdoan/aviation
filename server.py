#!/usr/bin/env python3
"""SpartansE-V landing server: serves the static page and relays "Book a pilot"
requests to the team inbox over SMTP. Standard library only.

Config comes from environment variables (a local .env file is loaded if present):
  SMTP_HOST      default smtp.gmail.com
  SMTP_PORT      default 587 (STARTTLS); use 465 for implicit TLS
  SMTP_STARTTLS  default true (ignored on port 465)
  SMTP_USER      login user, e.g. the Gmail address
  SMTP_PASS      login password / Gmail app password
  MAIL_FROM      default SMTP_USER
  MAIL_TO        inbox that receives the notifications
  PORT           HTTP port, default 8000
"""
import json
import os
import re
import smtplib
import ssl
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.message import EmailMessage
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import email_template

ROOT = Path(__file__).resolve().parent
# Only these file types are ever served, so .env / server.py can't leak.
PUBLIC_EXT = {".html", ".js", ".css", ".glb", ".webp", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff2"}
EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]{2,}$")
MAX_BODY = 4096
RATE_PER_IP = (5, 3600)      # 5 requests / hour / IP
RATE_GLOBAL = (60, 3600)     # 60 requests / hour overall


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


def cfg():
    user = os.environ.get("SMTP_USER", "").strip()
    return {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com").strip(),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "starttls": os.environ.get("SMTP_STARTTLS", "true").lower() not in ("0", "false", "no"),
        "user": user,
        # Gmail shows app passwords in groups of four; the spaces are not part of it.
        "password": os.environ.get("SMTP_PASS", "").replace(" ", ""),
        "from": os.environ.get("MAIL_FROM", user).strip(),
        "to": os.environ.get("MAIL_TO", "").strip(),
    }


class RateLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.hits = defaultdict(deque)

    def allow(self, key, limit, window):
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


limiter = RateLimiter()


def send_notification(c, email, page, ip, agent):
    now = datetime.now(timezone.utc)
    msg = EmailMessage()
    msg["Subject"] = email_template.subject(email)
    msg["From"] = f"SpartansE-V Website <{c['from']}>"
    msg["To"] = c["to"]
    msg["Reply-To"] = email
    msg.set_content(email_template.plain_text(email, page, ip, agent, now))
    msg.add_alternative(email_template.html(email, page, ip, agent, now), subtype="html")
    ctx = ssl.create_default_context()
    if c["port"] == 465:
        server = smtplib.SMTP_SSL(c["host"], c["port"], timeout=15, context=ctx)
    else:
        server = smtplib.SMTP(c["host"], c["port"], timeout=15)
    with server:
        if c["port"] != 465 and c["starttls"]:
            server.starttls(context=ctx)
        if c["user"] and c["password"]:
            server.login(c["user"], c["password"])
        server.send_message(msg)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
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

    def do_POST(self):
        if urlsplit(self.path).path != "/api/contact":
            self.send_error(404)
            return
        ip = self.client_address[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self.json(413, {"error": "Request too large."})
        try:
            data = json.loads(self.rfile.read(length))
            assert isinstance(data, dict)
        except Exception:
            return self.json(400, {"error": "Invalid request."})

        # Honeypot: real visitors never fill the hidden "company" field.
        if str(data.get("company") or "").strip():
            return self.json(200, {"ok": True})

        email = str(data.get("email") or "").strip()
        if len(email) > 254 or not EMAIL_RE.match(email):
            return self.json(400, {"error": "Please enter a valid work email."})
        page = str(data.get("page") or "")[:300].replace("\r", " ").replace("\n", " ")
        agent = (self.headers.get("User-Agent") or "")[:300]

        if not limiter.allow(ip, *RATE_PER_IP) or not limiter.allow("*", *RATE_GLOBAL):
            return self.json(429, {"error": "Too many requests — please try again later."})

        c = cfg()
        if not (c["host"] and c["from"] and c["to"]):
            self.log_message("contact form not configured: set SMTP_USER / MAIL_TO")
            return self.json(503, {"error": "The contact form isn't configured yet."})
        try:
            send_notification(c, email, page, ip, agent)
        except smtplib.SMTPAuthenticationError:
            self.log_message("SMTP login rejected for %s — check SMTP_USER / SMTP_PASS", c["user"])
            return self.json(502, {"error": "We couldn't send your request right now."})
        except Exception as e:  # network / TLS / relay errors
            self.log_message("SMTP send failed: %s", type(e).__name__)
            return self.json(502, {"error": "We couldn't send your request right now."})
        self.log_message("pilot request relayed for %s", email)
        return self.json(200, {"ok": True})


def main():
    port = int(os.environ.get("PORT", "8000"))
    c = cfg()
    missing = [k for k, v in (("SMTP_USER", c["user"]), ("SMTP_PASS", c["password"]), ("MAIL_TO", c["to"])) if not v]
    print(f"SpartansE-V landing on http://localhost:{port}/")
    if missing:
        print(f"  warning: {', '.join(missing)} not set — the contact form will not send mail", file=sys.stderr)
    else:
        print(f"  contact form: {c['from']} -> {c['to']} via {c['host']}:{c['port']}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
