"""Shared "Book a pilot" logic used by both the Vercel function (api/contact.py)
and the local dev server (server.py). Standard library only.

Environment:
  SMTP_HOST        default smtp.gmail.com
  SMTP_PORT        default 587 (STARTTLS); use 465 for implicit TLS
  SMTP_STARTTLS    default true (ignored on port 465)
  SMTP_USER        login user, e.g. the Gmail address
  SMTP_PASS        login password / Gmail app password
  MAIL_FROM        default SMTP_USER
  MAIL_TO          inbox that receives the notifications
  FRONTEND_ORIGIN  comma-separated origins allowed to call the API,
                   e.g. https://aviation-weld-zeta.vercel.app,https://aerotrace-intelligence.com
                   (unset = same-origin only)
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
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _email_template as email_template  # noqa: E402

EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]{2,}$")
MAX_BODY = 4096
RATE_PER_IP = (5, 3600)      # 5 requests / hour / IP
RATE_GLOBAL = (60, 3600)     # 60 requests / hour overall
CORS_MAX_AGE = "600"


def log(msg, *args):
    print("[contact] " + (msg % args if args else msg), file=sys.stderr, flush=True)


def allowed_origins():
    raw = os.environ.get("FRONTEND_ORIGIN", "")
    return {o.strip().rstrip("/").lower() for o in raw.split(",") if o.strip()}


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
    """In-memory limiter. On serverless it is per warm instance, so it only
    softens bursts; the origin check and honeypot do the rest."""

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


def request_origin(headers):
    origin = headers.get("Origin")
    if not origin:  # some browsers omit Origin on same-origin POSTs; fall back to Referer
        ref = urlsplit(headers.get("Referer") or "")
        origin = f"{ref.scheme}://{ref.netloc}" if ref.scheme and ref.netloc else ""
    return origin.rstrip("/").lower()


def origin_allowed(headers, origin):
    if not origin or origin == "null":
        return False
    allowed = allowed_origins()
    if allowed:
        return origin in allowed
    host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").lower()
    return urlsplit(origin).netloc == host


def client_ip(headers, fallback):
    fwd = headers.get("X-Forwarded-For") or headers.get("X-Real-IP") or ""
    return fwd.split(",")[0].strip() or fallback


def cors_headers(origin):
    return [("Access-Control-Allow-Origin", origin), ("Vary", "Origin")] if origin else []


def preflight(headers):
    """Returns (status, headers) for an OPTIONS request."""
    origin = request_origin(headers)
    if not origin_allowed(headers, origin):
        return 403, []
    return 204, cors_headers(origin) + [
        ("Access-Control-Allow-Methods", "POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type"),
        ("Access-Control-Max-Age", CORS_MAX_AGE),
    ]


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


def handle_post(headers, read_body, fallback_ip):
    """Returns (status, payload_dict, extra_headers) for a POST request.
    read_body(n) must return n bytes of the request body."""
    origin = request_origin(headers)
    if not origin_allowed(headers, origin):
        log("blocked request from origin %r", origin or "-")
        return 403, {"error": "This origin is not allowed."}, []
    cors = cors_headers(origin)

    length = int(headers.get("Content-Length") or 0)
    if length <= 0 or length > MAX_BODY:
        return 413, {"error": "Request too large."}, cors
    try:
        data = json.loads(read_body(length))
        assert isinstance(data, dict)
    except Exception:
        return 400, {"error": "Invalid request."}, cors

    # Honeypot: real visitors never fill the hidden "company" field.
    if str(data.get("company") or "").strip():
        return 200, {"ok": True}, cors

    email = str(data.get("email") or "").strip()
    if len(email) > 254 or not EMAIL_RE.match(email):
        return 400, {"error": "Please enter a valid work email."}, cors
    page = str(data.get("page") or "")[:300].replace("\r", " ").replace("\n", " ")
    agent = (headers.get("User-Agent") or "")[:300]
    ip = client_ip(headers, fallback_ip)

    if not limiter.allow(ip, *RATE_PER_IP) or not limiter.allow("*", *RATE_GLOBAL):
        return 429, {"error": "Too many requests — please try again later."}, cors

    c = cfg()
    if not (c["host"] and c["from"] and c["to"]):
        log("not configured: set SMTP_USER / MAIL_TO")
        return 503, {"error": "The contact form isn't configured yet."}, cors
    try:
        send_notification(c, email, page, ip, agent)
    except smtplib.SMTPAuthenticationError:
        log("SMTP login rejected for %s — check SMTP_USER / SMTP_PASS", c["user"])
        return 502, {"error": "We couldn't send your request right now."}, cors
    except Exception as e:  # network / TLS / relay errors
        log("SMTP send failed: %s: %s", type(e).__name__, e)
        return 502, {"error": "We couldn't send your request right now."}, cors
    log("pilot request relayed for %s", email)
    return 200, {"ok": True}, cors
