"""A stand-in for the Pinpoint backend/frontend, for the updater's end-to-end test.

It honours the contracts the updater relies on and nothing else:

* ``backend``  — serves ``/api/health/quick`` (version from APP_VERSION, db_revision
  from the shared state volume) and ``/api/services/``;
* ``frontend`` — serves ``/`` and proxies ``/api/*`` to the backend;
* ``worker``   — idles; ``ping`` exits 0 while it is configured healthy;
* ``migrate``  — app/db/migrate.py's exit codes: 0 applied, 2 destructive and not
  approved (PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION), writes DB_REV to the state volume;
* ``backup``   — app/cli/backup.py's JSON contract.
"""

import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE = Path("/state/rev")
VERSION = os.environ.get("APP_VERSION", "dev")
DB_REV = os.environ.get("DB_REV", "rev0")
BROKEN = os.environ.get("BROKEN", "0") == "1"


def rev():
    try:
        return STATE.read_text().strip()
    except FileNotFoundError:
        return None


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/health/quick":
            return self._json(200, {"status": "ok", "version": VERSION, "db_revision": rev()})
        if self.path == "/api/services/":
            return self._json(500 if BROKEN else 200, [] if not BROKEN else {"detail": "boom"})
        return self._json(404, {})


class Frontend(Backend):
    def do_GET(self):
        if self.path.startswith("/api/"):
            try:
                with urllib.request.urlopen(f"http://backend:8000{self.path}", timeout=5) as r:
                    return self._json(r.status, json.loads(r.read()))
            except urllib.error.HTTPError as e:
                return self._json(e.code, {})
            except Exception:
                return self._json(502, {})
        raw = b"<html>Pinpoint</html>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main(cmd):
    if cmd == "backend":
        if rev() is None:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(DB_REV)
        ThreadingHTTPServer(("0.0.0.0", 8000), Backend).serve_forever()
    elif cmd == "frontend":
        ThreadingHTTPServer(("0.0.0.0", 8080), Frontend).serve_forever()
    elif cmd == "worker":
        while True:
            time.sleep(3600)
    elif cmd == "ping":
        sys.exit(1 if BROKEN else 0)
    elif cmd == "migrate":
        if os.environ.get("DESTRUCTIVE") == "1" and os.environ.get("PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION") != "1":
            print("[migrate] destructive revision pending: drop_column legacy", file=sys.stderr)
            sys.exit(2)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(DB_REV)
        print(f"[migrate] now at {DB_REV}", file=sys.stderr)
    elif cmd == "backup":
        verify = "--verify" in sys.argv
        print(json.dumps({"status": "ok", "backup_name": f"db_backup_e2e_{int(time.time())}.sql.gpg",
                          "verified": verify, "tables": 1}))
    else:
        sys.exit(f"unknown command {cmd}")


if __name__ == "__main__":
    main(sys.argv[1])
