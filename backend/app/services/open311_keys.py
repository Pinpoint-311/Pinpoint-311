"""Open311 API keys: minting, verifying, rate limiting, and the Open311 switches.

What a key is for
-----------------
GeoReport v2 makes `api_key` a required parameter of POST requests.json. A key
identifies an integrator (a vendor app, a regional aggregator), gives that
integrator its own request budget, and can be revoked without touching anyone
else. It is not a resident credential -- residents have no account -- and the
town's own portal does not use one (see the first-party note in
app/api/open311.py).

Storage
-------
Only `sha256(key)` is kept. Keys are 32 random bytes, so an unsalted fast hash
is the right tool: there is no dictionary to attack, and a slow KDF would only
make every POST slower. The first eight characters are stored separately as a
display label and as an index to narrow the lookup; the final comparison is
`hmac.compare_digest` on the hashes, so match time does not depend on how many
leading characters an attacker guessed.

Rate limits
-----------
Per key (default 60/minute, overridable per key) and per client address for
anonymous submissions (10/minute, the limit the endpoint always had). In-memory
moving windows, the same storage the rest of the API's slowapi limits use.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

from limits import parse as parse_limit
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from sqlalchemy import select

logger = logging.getLogger(__name__)

PREFIX_LENGTH = 8
DEFAULT_KEY_LIMIT_PER_MINUTE = 60
MAX_KEY_LIMIT_PER_MINUTE = 600
ANONYMOUS_LIMIT = "10/minute"

_limiter = MovingWindowRateLimiter(MemoryStorage())


def generate_key() -> Tuple[str, str, str]:
    """(plaintext, prefix, sha256 hex). The plaintext must never be persisted."""
    plaintext = secrets.token_urlsafe(32)
    return plaintext, plaintext[:PREFIX_LENGTH], hash_key(plaintext)


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def authenticate(db, presented: Optional[str]):
    """The live (non-revoked) key row matching `presented`, or None.

    Candidates are narrowed by prefix and then compared by hash in constant
    time. Every candidate is compared, even after a match, so the loop's
    duration does not say which one matched.
    """
    from app.models import Open311ApiKey

    if not presented or not isinstance(presented, str):
        return None
    presented = presented.strip()
    # A real key is 43 characters; anything far outside that is not one, and
    # refusing it early keeps a megabyte "key" from being hashed.
    if len(presented) < PREFIX_LENGTH or len(presented) > 128:
        return None
    wanted = hash_key(presented)
    rows = (
        await db.execute(
            select(Open311ApiKey).where(Open311ApiKey.key_prefix == presented[:PREFIX_LENGTH])
        )
    ).scalars().all()
    match = None
    for row in rows:
        if hmac.compare_digest(str(row.key_hash or ""), wanted) and match is None:
            match = row
    if match is None or match.revoked_at is not None:
        return None
    return match


async def touch(db, key) -> None:
    """Record that a key was just used. Never fails the request it belongs to."""
    try:
        key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("could not record Open311 key use: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass


def key_limit_per_minute(key) -> int:
    value = getattr(key, "rate_limit_per_minute", None)
    if not value or value < 1:
        return DEFAULT_KEY_LIMIT_PER_MINUTE
    return min(int(value), MAX_KEY_LIMIT_PER_MINUTE)


def hit_key_limit(key) -> bool:
    """Count one request against a key. False when the key is over its limit."""
    item = parse_limit(f"{key_limit_per_minute(key)}/minute")
    return _limiter.hit(item, "open311-key", str(key.id))


def hit_anonymous_limit(client: str) -> bool:
    """Count one anonymous submission against a client address."""
    return _limiter.hit(parse_limit(ANONYMOUS_LIMIT), "open311-anon", client or "unknown")


def reset_limits() -> None:
    """Tests only: forget every counted request."""
    _limiter.storage.reset()


@dataclass
class Open311Config:
    allow_anonymous_submissions: bool = False
    jurisdiction_id: Optional[str] = None


async def read_settings(db) -> Open311Config:
    """The Open311 switches, defaulting closed.

    A missing row is the normal state of a deployment nobody has configured. A
    read FAILURE also answers "anonymous submissions off": failing open would
    turn a database hiccup into an unauthenticated write path.
    """
    from app.models import Open311Settings

    try:
        row = (
            await db.execute(select(Open311Settings).order_by(Open311Settings.id).limit(1))
        ).scalar_one_or_none()
    except Exception as exc:
        logger.error("Open311 settings read failed; treating anonymous submissions as off: %s", exc)
        return Open311Config()
    if row is None:
        return Open311Config()
    return Open311Config(
        allow_anonymous_submissions=bool(row.allow_anonymous_submissions),
        jurisdiction_id=(row.jurisdiction_id or "").strip() or None,
    )


def jurisdiction_matches(configured: Optional[str], presented: Optional[str]) -> bool:
    """A presented jurisdiction_id is fine when nothing is configured or it matches.

    Absent is always fine: GeoReport v2 only requires the parameter of
    endpoints that serve several jurisdictions, and this one serves one.
    """
    if presented is None or str(presented).strip() == "":
        return True
    if not configured:
        return True
    return hmac.compare_digest(str(presented).strip().lower(), configured.strip().lower())
