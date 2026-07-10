"""Tiny stdlib HTTP framework for the portal + admin services.

No third-party dependencies (minimal deps, server-rendered HTML). Just
enough router / request / response / cookie plumbing to serve a handful of routes and
HTML forms. Shared by portal.py (candidate, :8000) and admin.py (admin, :8001).
"""
from __future__ import annotations

import json as _json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie


class Request:
    def __init__(self, method, path, query, headers, body):
        self.method = method
        self.path = path
        self.query = query          # dict[str, str] (last value wins)
        self.headers = headers
        self.body = body            # bytes
        self._form_multi = None
        self._cookies = None

    def _parse_form(self):
        if self._form_multi is None:
            ctype = self.headers.get("Content-Type", "")
            if "application/x-www-form-urlencoded" in ctype:
                self._form_multi = urllib.parse.parse_qs(self.body.decode("utf-8"), keep_blank_values=True)
            else:
                self._form_multi = {}
        return self._form_multi

    @property
    def form(self):
        return {k: v[-1] for k, v in self._parse_form().items()}

    def getlist(self, name):
        return list(self._parse_form().get(name, []))

    def json_body(self):
        """Parse the request body as JSON; {} on empty/invalid (callers validate)."""
        try:
            return _json.loads(self.body.decode("utf-8")) if self.body else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    @property
    def cookies(self):
        if self._cookies is None:
            jar = SimpleCookie()
            raw = self.headers.get("Cookie", "")
            if raw:
                jar.load(raw)
            self._cookies = {k: m.value for k, m in jar.items()}
        return self._cookies


class Response:
    def __init__(self, status=200, body=b"", content_type="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.status = status
        self.body = body
        self.headers = list(headers or [])
        if content_type is not None:
            self.headers.append(("Content-Type", content_type))

    def set_cookie(self, name, value, *, max_age=None, http_only=True, path="/", same_site="Lax"):
        parts = [f"{name}={value}", f"Path={path}", f"SameSite={same_site}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if http_only:
            parts.append("HttpOnly")
        self.headers.append(("Set-Cookie", "; ".join(parts)))
        return self

    @classmethod
    def html(cls, markup, status=200):
        return cls(status, markup)

    @classmethod
    def text(cls, body, status=200):
        return cls(status, body, "text/plain; charset=utf-8")

    @classmethod
    def json(cls, obj, status=200):
        return cls(status, _json.dumps(obj), "application/json; charset=utf-8")

    @classmethod
    def redirect(cls, location, status=303):
        return cls(status, b"", None, [("Location", location)])

    @classmethod
    def no_content(cls):
        return cls(204, b"", None)

    @classmethod
    def unauthorized(cls, body="unauthorized"):
        return cls(401, body, "text/plain; charset=utf-8")

    @classmethod
    def not_found(cls, body="not found"):
        return cls(404, body, "text/plain; charset=utf-8")


class Router:
    """Routes with `<name>` path params, e.g. /admin/sessions/<sid>/close."""

    def __init__(self):
        self.routes = []          # (method, [segments], handler)
        self.fallback = None

    def add(self, method, pattern, handler):
        self.routes.append((method, _segments(pattern), handler))

    def route(self, method, pattern):
        def deco(fn):
            self.add(method, pattern, fn)
            return fn
        return deco

    def match(self, method, path):
        want = _segments(path)
        for m, pat, handler in self.routes:
            if m != method:
                continue
            params = _match_segments(pat, want)
            if params is not None:
                return handler, params
        return None, None


def _segments(path):
    path = path.split("?", 1)[0]
    stripped = path.strip("/")
    return stripped.split("/") if stripped else []


def _match_segments(pat, want):
    if len(pat) != len(want):
        return None
    params = {}
    for p, w in zip(pat, want):
        if p.startswith("<") and p.endswith(">"):
            params[p[1:-1]] = urllib.parse.unquote(w)
        elif p != w:
            return None
    return params


def serve(router, port, *, name="service"):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"{name}/1.0"

        def _dispatch(self, method):
            parsed = urllib.parse.urlparse(self.path)
            query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            req = Request(method, parsed.path, query, self.headers, body)
            handler, params = router.match(method if method != "HEAD" else "GET", parsed.path)
            try:
                if handler is None:
                    resp = router.fallback(req) if router.fallback else Response.not_found()
                else:
                    resp = handler(req, **params)
            except Exception as exc:  # never leak a stack trace to a candidate
                self.log_error("handler error: %s", exc)
                resp = Response(500, "internal error", "text/plain; charset=utf-8")
            self.send_response(resp.status)
            for k, v in resp.headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp.body)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(resp.body)

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        def log_message(self, *args):
            pass  # keep container logs quiet; audit lives in events.jsonl

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[{name}] listening on :{port}", flush=True)
    httpd.serve_forever()
