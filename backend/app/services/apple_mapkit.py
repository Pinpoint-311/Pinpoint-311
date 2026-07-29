"""Mint the short-lived token Apple MapKit JS needs to load.

Apple is the one map provider that cannot be authenticated with a static key.
MapKit JS requires an ES256-signed JWT, and the private key that signs it must
stay on the server -- it is downloadable exactly once from Apple's developer
portal and grants map access for the whole team until revoked.

So the browser never receives the key. It receives a token that expires, minted
here on request, and it re-requests when that token runs out. This is also why
Apple's entry is the only one whose credentials are not returned by the map
config endpoint alongside everyone else's.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

TEAM_ID_KEY = "APPLE_MAPKIT_TEAM_ID"
KEY_ID_KEY = "APPLE_MAPKIT_KEY_ID"
PRIVATE_KEY_KEY = "APPLE_MAPKIT_PRIVATE_KEY"

# Apple permits up to a year. Short is better: a leaked token expires on its
# own, and the cost of re-minting is one cheap request. Half an hour comfortably
# outlives a session of someone placing a pin.
TOKEN_TTL_SECONDS = 30 * 60

# Re-mint slightly early so a token never expires mid-page-load.
REFRESH_MARGIN_SECONDS = 60

_cache: Optional[Tuple[str, float]] = None


def normalize_private_key(raw: str) -> str:
    """Accept a .p8 however a clerk managed to paste it.

    The file is PEM, and pasting it through a form or an environment variable
    routinely turns the newlines into literal backslash-n or strips them
    entirely. Signing fails cryptically on all of those, so repair what can be
    repaired rather than making someone debug whitespace.
    """
    key = (raw or "").strip()
    if not key:
        return ""
    key = key.replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")

    # Canonicalise rather than patch. Splitting on the dashes gives
    # ['', header, body, footer, trailing]; rebuilding from the body means every
    # equivalent paste -- escaped newlines, CRLF, no newlines at all, stray
    # indentation -- produces byte-identical output, and the function is
    # idempotent. Patching selectively is how the earlier version corrupted
    # perfectly good keys.
    parts = key.split("-----")
    if len(parts) >= 5 and "PRIVATE KEY" in parts[1].upper():
        header, footer = parts[1], parts[3]
        body = "".join(parts[2].split())
        wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
        return f"-----{header}-----\n{wrapped}\n-----{footer}-----"

    return key.strip()


def build_claims(team_id: str, *, now: Optional[int] = None, ttl: int = TOKEN_TTL_SECONDS) -> dict:
    """MapKit's required claim set.

    `origin` is deliberately absent: it pins a token to one domain, and a
    self-hosted deployment does not know its own public hostname reliably --
    behind Caddy, a reverse proxy, or a town's own CDN the Host header is not
    something to bet map loading on. The token is short-lived instead.
    """
    issued = int(now if now is not None else time.time())
    return {"iss": team_id, "iat": issued, "exp": issued + ttl}


def sign_token(team_id: str, key_id: str, private_key: str, *, now: Optional[int] = None) -> str:
    """ES256-sign a MapKit token. Raises if the key is unusable."""
    import jwt as jwt_lib

    key = normalize_private_key(private_key)
    if not key:
        raise ValueError("Apple MapKit private key is empty")
    if not team_id or not key_id:
        raise ValueError("Apple MapKit team id and key id are both required")

    return jwt_lib.encode(
        build_claims(team_id, now=now),
        key,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"},
    )


async def get_token(get_secret) -> Optional[str]:
    """A valid MapKit token, or None if Apple is not configured.

    Cached until shortly before expiry: signing is cheap but reading the private
    key out of a cloud Secret Manager is a network round trip, and this is
    called on every page load that shows a map.

    Returns None rather than raising. A misconfigured Apple deployment should
    surface as "map provider not configured" in the admin console, not as a 500
    on an endpoint every page hits.
    """
    global _cache

    if _cache and _cache[1] - REFRESH_MARGIN_SECONDS > time.time():
        return _cache[0]

    try:
        team_id = await get_secret(TEAM_ID_KEY)
        key_id = await get_secret(KEY_ID_KEY)
        private_key = await get_secret(PRIVATE_KEY_KEY)
    except Exception as exc:
        logger.warning("could not read Apple MapKit credentials: %s", exc)
        return None

    if not (team_id and key_id and private_key):
        return None

    try:
        token = sign_token(team_id, key_id, private_key)
    except Exception as exc:
        # Almost always a malformed .p8 -- wrong key type, truncated paste, or
        # an RSA key where an EC key was needed.
        logger.warning("could not sign Apple MapKit token: %s", exc)
        return None

    _cache = (token, time.time() + TOKEN_TTL_SECONDS)
    return token


def clear_cache() -> None:
    """Drop the cached token, so rotating the key takes effect immediately."""
    global _cache
    _cache = None
