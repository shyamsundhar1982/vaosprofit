"""Dependency-free local HTTP API and review dashboard for the pilot."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import InvalidData, backtest, connect, export_drafts, import_csv, recommendations, stores, summary, tenant_from_token

WEB_FILE = Path(__file__).parent / "static" / "index.html"
MAX_IMPORT_BYTES = 10 * 1024 * 1024


class RetailHandler(BaseHTTPRequestHandler):
    db_path: str = "retailpilot.sqlite3"

    def _send(self, status: int, data: bytes, mime: str = "application/json; charset=utf-8", extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, obj: object):
        self._send(status, json.dumps(obj, allow_nan=False).encode())

    def _auth(self, db: sqlite3.Connection) -> str | None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        return tenant_from_token(db, auth[7:])

    def _run(self, post: bool):
        parsed = urlsplit(self.path)
        if parsed.path == "/" and not post:
            return self._send(200, WEB_FILE.read_bytes(), "text/html; charset=utf-8")
        if parsed.path == "/api/health" and not post:
            return self._json(200, {"ok": True, "status": "pilot", "purchase_execution": False})
        if not parsed.path.startswith("/api/"):
            return self._json(404, {"error": "Not found"})
        with connect(self.db_path) as db:
            tenant = self._auth(db)
            if not tenant:
                return self._json(401, {"error": "A valid tenant API token is required"})
            try:
                q = parse_qs(parsed.query, keep_blank_values=True)
                store_id = q.get("store", ["main"])[0]
                as_of = q.get("as_of", [(date.today() - timedelta(days=1)).isoformat()])[0]
                review = int(q.get("review_days", ["7"])[0])
                if post:
                    if not parsed.path.startswith("/api/import/"):
                        return self._json(405, {"error": "Unsupported operation"})
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_IMPORT_BYTES:
                        return self._json(413, {"error": "CSV size must be between 1 byte and 10 MiB"})
                    if self.headers.get("Content-Type", "").split(";")[0].strip() != "text/csv":
                        return self._json(415, {"error": "Use Content-Type: text/csv"})
                    try:
                        data = self.rfile.read(length).decode("utf-8-sig")
                    except UnicodeDecodeError:
                        raise InvalidData("CSV must be UTF-8")
                    kind = parsed.path.rsplit("/", 1)[-1]
                    count = import_csv(db, tenant, kind, data)
                    return self._json(200, {"imported": count, "kind": kind, "tenant": tenant})
                if parsed.path == "/api/me":
                    name = db.execute("SELECT name FROM tenants WHERE id=?", (tenant,)).fetchone()["name"]
                    return self._json(200, {"tenant": tenant, "name": name, "stores": stores(db, tenant)})
                if parsed.path == "/api/stores":
                    return self._json(200, stores(db, tenant))
                if parsed.path in ("/api/recommendations", "/api/summary", "/api/drafts.csv"):
                    items = recommendations(db, tenant, store_id, as_of, review)
                    if parsed.path == "/api/recommendations":
                        return self._json(200, {"store": store_id, "as_of": as_of, "review_days": review, "items": items})
                    if parsed.path == "/api/summary":
                        return self._json(200, {"store": store_id, "as_of": as_of, **summary(items)})
                    return self._send(200, export_drafts(items).encode("utf-8-sig"), "text/csv; charset=utf-8", {
                        "Content-Disposition": 'attachment; filename="purchase-order-DRAFT.csv"'
                    })
                if parsed.path == "/api/backtest":
                    return self._json(200, backtest(db, tenant, store_id, as_of))
                return self._json(404, {"error": "Not found"})
            except (InvalidData, ValueError) as exc:
                return self._json(400, {"error": str(exc)})
            except sqlite3.IntegrityError:
                return self._json(400, {"error": "Invalid or missing tenant-scoped reference"})

    def do_GET(self):
        self._run(False)

    def do_POST(self):
        self._run(True)


def serve(db_path: str, host: str = "127.0.0.1", port: int = 8766):
    class BoundHandler(RetailHandler):
        pass

    BoundHandler.db_path = db_path
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Pilot server can only bind localhost; use a reviewed HTTPS proxy for external access")
    httpd = ThreadingHTTPServer((host, port), BoundHandler)
    print(f"RetailPilot local dashboard: http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
