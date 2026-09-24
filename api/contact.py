"""Vercel Serverless Function: POST /api/contact (see _contact.py for config)."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _contact  # noqa: E402


class handler(BaseHTTPRequestHandler):
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

    def do_OPTIONS(self):
        status, headers = _contact.preflight(self.headers)
        self.reply(status, headers)

    def do_POST(self):
        status, payload, headers = _contact.handle_post(self.headers, self.rfile.read, self.client_address[0])
        self.reply(status, headers, payload)

    def do_GET(self):
        self.reply(405, [("Allow", "POST, OPTIONS")], {"error": "Method not allowed."})
