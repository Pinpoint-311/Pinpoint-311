"""The auth/admin audit log's hash chain (``audit_logs``), version 2.

Version 1 hashed a timestamp taken in Python while the row stored the
database's own ``now()``, so no entry could ever be recomputed from what was
stored and verification could only ever report tampering. Version 2 is built
so that verification needs nothing but the stored rows:

* Every value that is hashed is first written to the row in exactly the form
  that will be read back: the timestamp is set in Python (UTC, microseconds)
  rather than left to the server default, and ``details`` is round-tripped
  through JSON so a tuple, a datetime or an int key cannot hash one way and
  store another.
* The canonical record is JSON with sorted keys, no whitespace, explicit
  nulls, ASCII escaping and no NaN.
* ``entry_hash = SHA-256(previous_hash + "\\n" + canonical)``, where
  ``previous_hash`` is the stored ``entry_hash`` of the row immediately before
  it by id ("" for the very first row). Editing any hashed field breaks that
  row; deleting or reordering rows breaks the next row's link.

``ip_address`` and ``user_agent`` are deleted after 90 days by the retention
task (the Privacy Impact Assessment's commitment) while the rest of the row is
kept for seven years, so they cannot be hashed directly -- the purge would look
exactly like tampering. They are committed to instead: a random per-row salt
and ``context_digest = SHA-256(salt + "|" + [ip, user_agent])``. The digest is
in the chain; the salt is deleted together with the IP. While the salt exists,
an edited IP or user agent is detected; once it is gone the digest reveals
nothing (a 128-bit salt, unlike a bare hash of an IPv4 address, cannot be
brute-forced).

The chain is unkeyed on purpose: it verifies from the database alone and
survives a SECRET_KEY rotation. Its defence against someone who can rewrite
the table and recompute every hash is the nightly anchor (``AuditAnchor``),
which also goes to the shipped application log.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

CHAIN_VERSION = 2
LEGACY_CHAIN_VERSION = 1

# pg_advisory_xact_lock key serialising writers of audit_logs. A fixed,
# arbitrary signed 64-bit constant ("PP311AU1" as ASCII), so it cannot collide
# with a lock taken elsewhere for a different purpose by accident.
CHAIN_LOCK_KEY = 0x5050333131415531
# The same, for request_audit_logs (the per-report timeline chain). A separate
# key so the two chains never wait on each other.
REQUEST_CHAIN_LOCK_KEY = 0x5050333131415532


def normalize_timestamp(value: Optional[datetime]) -> datetime:
    """UTC-aware datetime, defaulting to now. Naive values are taken as UTC
    (that is how SQLite hands a timestamptz back)."""
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def timestamp_text(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return normalize_timestamp(value).isoformat(timespec="microseconds")


def normalize_json(value: Any) -> Any:
    """The value exactly as a JSON column will hand it back."""
    if value is None:
        return None
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def new_context_salt() -> str:
    return secrets.token_hex(16)


def context_digest(salt: str, ip_address: Optional[str], user_agent: Optional[str]) -> str:
    return hashlib.sha256(
        (salt + "|" + _dumps([ip_address, user_agent])).encode("utf-8")
    ).hexdigest()


def canonical(row: Any) -> str:
    """Canonical v2 serialization of an ``audit_logs`` row (ORM object or a
    result row: anything with these attributes)."""
    return _dumps({
        "chain_version": CHAIN_VERSION,
        "timestamp": timestamp_text(row.timestamp),
        "event_type": row.event_type,
        "success": bool(row.success) if row.success is not None else None,
        "failure_reason": row.failure_reason,
        "username": row.username,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "details": row.details,
        "context_digest": row.context_digest,
    })


def compute_hash(row: Any, previous_hash: Optional[str]) -> str:
    return hashlib.sha256(
        ((previous_hash or "") + "\n" + canonical(row)).encode("utf-8")
    ).hexdigest()


def seal(row: Any, previous_hash: Optional[str]) -> None:
    """Normalise a new row's hashed fields in place, then chain it."""
    row.chain_version = CHAIN_VERSION
    row.timestamp = normalize_timestamp(row.timestamp)
    row.details = normalize_json(row.details)
    if row.ip_address is not None or row.user_agent is not None:
        row.context_salt = new_context_salt()
        row.context_digest = context_digest(row.context_salt, row.ip_address, row.user_agent)
    else:
        row.context_salt = None
        row.context_digest = None
    row.previous_hash = previous_hash
    row.entry_hash = compute_hash(row, previous_hash)
