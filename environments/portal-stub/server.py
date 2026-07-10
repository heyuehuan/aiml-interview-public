#!/usr/bin/env python3
"""the workspace stack portal stub.

Stands in for the portal's session service (portal on :8000, routes `/`
and `/api/*`) so the workspace stack is runnable and viewable before the portal exists.

It does exactly two things:
  * serves the static home page shell for `/` and any non-API path;
  * answers the proxy's auth subrequest at `/api/authz` with 204 (always allow).

the portal replaces this wholesale with the real access-code-gated session service.
"""
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SRV_DIR = Path(os.environ.get("SRV_DIR", "/srv"))
PORT = int(os.environ.get("PORT", "8000"))


class Handler(BaseHTTPRequestHandler):
    server_version = "portal-stub/0.1"

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._send(200, b"ok")
        if path == "/api/authz":
            # Stub: always allow until the portal enforces real session auth.
            return self._send(204)
        if path.startswith("/api/"):
            return self._send(404, b'{"error":"not found"}', "application/json")
        # Everything else -> home page shell.
        index = SRV_DIR / "index.html"
        if index.exists():
            return self._send(200, index.read_bytes(), "text/html; charset=utf-8")
        return self._send(404, b"no home page")

    do_HEAD = do_GET

    def log_message(self, *args):  # keep the container log quiet
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
