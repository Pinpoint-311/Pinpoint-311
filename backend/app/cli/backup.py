"""Take the instance's encrypted off-site backup and, with ``--verify``, prove it restores.

    python -m app.cli.backup [--verify] [--scratch-url URL]

Run by pinpoint-updater before every upgrade, in a one-off container from the
image the instance is running now. Prints exactly one JSON object as its last
line of stdout and exits 0 only when the backup was taken (and, with
``--verify``, restored and matched).

Verification repeats the 2026-10-18 restore drill: download the object just
uploaded, decrypt it, ``pg_restore`` it into a scratch database, and compare the
row count of every table with the live database. Counts are read just before
the dump and again just after; a restored table must fall between the two,
which tolerates residents filing reports while the dump runs but not a
truncated or missing table.

The scratch database is ``--scratch-url`` / ``PINPOINT_BACKUP_VERIFY_URL`` when
given (it must not be the live database). Otherwise a database named
``<live>_restore_verify_<timestamp>`` is created on the same server and dropped
afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from app.services import backup_service

logger = logging.getLogger("app.cli.backup")

SCRATCH_ENV = "PINPOINT_BACKUP_VERIFY_URL"


def plain_url(url: str) -> str:
    """postgresql+asyncpg://… → postgresql://… (what libpq tools accept)."""
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def same_database(a: str, b: str) -> bool:
    """Best effort on the URL alone (``DB.`` is ``db``). It cannot see that two
    hostnames reach one server, which is why a provided scratch database must
    also be empty (run)."""
    def key(url):
        p = urlparse(plain_url(url))
        return ((p.hostname or "localhost").rstrip("."), p.port or 5432, p.path.strip("/"))
    return key(a) == key(b)


def with_database(url: str, name: str) -> str:
    parsed = urlparse(plain_url(url))
    return urlunparse(parsed._replace(path=f"/{name}"))


def table_counts(url: str) -> Dict[str, int]:
    """Row count of every base table in the public schema."""
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(plain_url(url))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
            )
            names = [row[0] for row in cur.fetchall()]
            counts = {}
            for name in names:
                cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", name)))
                counts[name] = int(cur.fetchone()[0])
            return counts
    finally:
        conn.close()


def _admin(url: str, statement: str, name: str) -> None:
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(with_database(url, "postgres"))
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL(statement).format(sql.Identifier(name)))
    finally:
        conn.close()


def create_scratch(live_url: str) -> Tuple[str, str]:
    live_name = urlparse(plain_url(live_url)).path.strip("/") or "postgres"
    name = f"{live_name}_restore_verify_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"[:63]
    _admin(live_url, "CREATE DATABASE {}", name)
    return with_database(live_url, name), name


def drop_scratch(live_url: str, name: str) -> None:
    _admin(live_url, "DROP DATABASE IF EXISTS {}", name)


def restore_into(dump_path: str, url: str) -> Optional[str]:
    """pg_restore into ``url``; None on success, else the errors that matter
    (backup_service.restore_errors sets aside the known-harmless ones)."""
    result = subprocess.run(
        ["pg_restore", "--no-owner", "--no-privileges", "-d", plain_url(url), dump_path],
        capture_output=True, text=True, timeout=3600,
    )
    if result.returncode == 0:
        return None
    real = backup_service.restore_errors(result.stderr)
    return "; ".join(real[:5]) if real else None


def compare(before: Dict[str, int], after: Dict[str, int], restored: Dict[str, int]) -> list:
    mismatches = []
    for table in sorted(set(before) | set(after)):
        seen = [n for n in (before.get(table), after.get(table)) if n is not None]
        lo, hi = min(seen), max(seen)
        if table not in restored:
            mismatches.append({"table": table, "live": [lo, hi], "restored": None})
        elif not (lo <= restored[table] <= hi):
            mismatches.append({"table": table, "live": [lo, hi], "restored": restored[table]})
    return mismatches


async def run(verify: bool, scratch_url: Optional[str]) -> dict:
    live_url = os.environ.get("DATABASE_URL", "")
    if "postgresql" not in live_url:
        return {"status": "error", "message": "DATABASE_URL is not a PostgreSQL URL"}
    if scratch_url and same_database(scratch_url, live_url):
        return {"status": "error", "message": "the scratch database URL points at the live database; refusing"}

    before = table_counts(live_url) if verify else {}
    created = await backup_service.create_backup()
    if created.get("status") != "success":
        return {"status": "error", "message": created.get("message") or "backup failed"}
    name = created["backup_name"]
    report = {"status": "ok", "backup_name": name, "size_bytes": created.get("size_bytes"),
              "bucket": created.get("bucket"), "verified": False}
    if not verify:
        return report
    after = table_counts(live_url)

    config = await backup_service.get_backup_config()
    if not config:
        return {**report, "status": "error", "message": "backup configuration disappeared before verification"}
    scratch_name = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            encrypted = os.path.join(tmp, "backup.gpg")
            decrypted = os.path.join(tmp, "backup.dump")
            if not await backup_service.download_backup(name, encrypted):
                return {**report, "status": "error", "message": "could not download the backup just uploaded"}
            if not backup_service.decrypt_file(encrypted, decrypted, config["BACKUP_ENCRYPTION_KEY"]):
                return {**report, "status": "error", "message": "could not decrypt the backup just uploaded"}
            if scratch_url:
                # pg_restore into a database that has tables appends rows to
                # them. If an alias, an IP or a second hostname makes the
                # "scratch" URL the live database, this is what stops the
                # verification from writing duplicates into production.
                existing = table_counts(scratch_url)
                if existing:
                    return {**report, "status": "error",
                            "message": f"the scratch database is not empty ({len(existing)} tables); it must be an "
                                       "empty database, never the live one. Refusing to restore into it"}
            else:
                scratch_url, scratch_name = create_scratch(live_url)
            errors = restore_into(decrypted, scratch_url)
            if errors:
                return {**report, "status": "error", "message": f"restore into the scratch database failed: {errors}"}
            restored = table_counts(scratch_url)
    finally:
        if scratch_name:
            try:
                drop_scratch(live_url, scratch_name)
            except Exception as exc:  # reported, never fatal to an otherwise good backup
                report["scratch_cleanup_error"] = str(exc)[:200]

    mismatches = compare(before, after, restored)
    report.update({"tables": len(set(before) | set(after)), "rows": sum(after.values()),
                   "mismatches": mismatches, "scratch": "created and dropped" if scratch_name else "provided"})
    if mismatches:
        return {**report, "status": "error",
                "message": f"{len(mismatches)} table(s) did not restore to their live row counts"}
    report["verified"] = True
    return report


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.backup", description=__doc__.split("\n")[0])
    parser.add_argument("--verify", action="store_true", help="restore into a scratch database and compare table counts")
    parser.add_argument("--scratch-url", default=os.environ.get(SCRATCH_ENV), help=f"scratch database URL (or {SCRATCH_ENV})")
    args = parser.parse_args(argv)
    # Logs to stderr; stdout carries only the JSON report.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    try:
        report = asyncio.run(run(args.verify, args.scratch_url))
    except Exception as exc:
        # The class name, not the message: exception text can carry a URL with
        # credentials or a storage endpoint detail.
        report = {"status": "error", "message": f"backup stopped unexpectedly ({exc.__class__.__name__})"}
    print(json.dumps(report, sort_keys=True, default=str))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
