"""Single-use credentials: sign-in exchange codes and burned tokens.

Two different stores, picked for what a failure costs:

* **Exchange codes** (``issue_login_code`` / ``redeem_login_code``). The SSO
  callback used to redirect to ``/login?token=<jwt>``, which left an eight-hour
  bearer token in the browser history, the proxy access log and the Referer
  header of whatever the login page loaded next. It now redirects with a
  random code that is good for one redemption within ``LOGIN_CODE_TTL_SECONDS``,
  and the page trades it for the token over ``POST /api/auth/exchange``.
  Redis holds the codes (shared across workers, atomic GETDEL); the in-process
  dict is the fallback, as for the login state. Losing a code is harmless --
  the user signs in again -- so a Redis outage fails closed, never open. The
  store holds the claims to mint, not a token: nothing in Redis is a bearer
  credential on its own.

* **Burned tokens** (``burn``). Break-glass tokens and Accela OAuth states are
  signed and time-boxed, but a signature cannot say "already used". They are
  recorded in ``system_secrets`` -- the same durable table the onboarding link
  already burns its jti in -- under a unique key, so a second redemption hits
  the unique constraint on any worker, after any restart, with Redis up or
  down. Only a digest of the identifier is stored.
"""
import hashlib
import json
import logging
import secrets
import time
from typing import Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

LOGIN_CODE_TTL_SECONDS = 60

_CODE_PREFIX = "auth:login_code:"

# code -> (claims json, expires_at)
_memory: Dict[str, Tuple[str, float]] = {}


def _client():
    # One pooled client for every short-lived auth record.
    from app.services.login_state import _client as shared_client

    return shared_client()


def _prune(now: Optional[float] = None) -> None:
    cutoff = now if now is not None else time.time()
    for code in [c for c, (_, exp) in _memory.items() if exp <= cutoff]:
        _memory.pop(code, None)


async def issue_login_code(claims: dict) -> str:
    """Store the session claims to mint and return a single-use code for them."""
    code = secrets.token_urlsafe(32)
    value = json.dumps(claims, separators=(",", ":"))
    client = _client()
    if client is not None:
        try:
            await client.setex(_CODE_PREFIX + code, LOGIN_CODE_TTL_SECONDS, value)
            return code
        except Exception as exc:
            logger.warning("login code: redis write failed, using memory (%s)", exc)
    _prune()
    _memory[code] = (value, time.time() + LOGIN_CODE_TTL_SECONDS)
    return code


async def redeem_login_code(code: str) -> Optional[dict]:
    """Return the claims for this code and invalidate it, or None.

    Single use: GETDEL is atomic, so two racing redemptions cannot both win.
    """
    if not code or not isinstance(code, str) or len(code) > 128:
        return None
    client = _client()
    if client is not None:
        try:
            value = await client.getdel(_CODE_PREFIX + code)
            if value is not None:
                return json.loads(value)
        except Exception as exc:
            logger.warning("login code: redis read failed, using memory (%s)", exc)
    _prune()
    entry = _memory.pop(code, None)
    if entry is None:
        return None
    value, expires_at = entry
    if expires_at <= time.time():
        return None
    return json.loads(value)


def _burn_key(kind: str, ident: str) -> str:
    digest = hashlib.sha256(f"{kind}:{ident}".encode("utf-8")).hexdigest()
    return f"USED_{kind.upper()}_{digest}"[:100]


async def burn(db, kind: str, ident: str) -> bool:
    """Mark ``ident`` used. True the first time, False on every later call.

    Commits on its own: the mark has to be durable before the caller hands out
    whatever the token was worth. Call it before staging other changes.
    """
    from app.models import SystemSecret

    if not ident:
        return False
    db.add(SystemSecret(
        key_name=_burn_key(kind, ident),
        key_value=None,
        is_configured=True,
        description=f"Redeemed single-use {kind.replace('_', ' ')}",
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return False
    return True
