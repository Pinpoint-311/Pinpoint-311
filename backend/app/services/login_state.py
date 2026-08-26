"""Short-lived CSRF state for the OIDC login round-trip.

The state token has to survive the redirect out to the identity provider and
back, which lasts as long as the operator takes to find their password and
answer an MFA prompt. It used to live in a module-level dict, so any restart of
the backend in that window -- a deploy, a crash, a `compose up` -- dropped every
login already in flight. The operator came back from a successful sign-in to
"Invalid or expired state token" with nothing actually wrong at either end.

Redis holds it across restarts. The in-memory dict remains as the fallback for
deployments that have no Redis: no worse than the behaviour it replaces, and it
now expires entries instead of retaining every state token until the process
exits.
"""
import logging
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Long enough for a slow MFA prompt, short enough that a leaked state token is
# not useful. Providers give the authorization code its own, shorter lifetime.
TTL_SECONDS = 600

_KEY_PREFIX = "auth:login_state:"

# state -> (redirect_uri, expires_at)
_memory: Dict[str, Tuple[str, float]] = {}


def _prune(now: Optional[float] = None) -> None:
    cutoff = now if now is not None else time.time()
    for state in [s for s, (_, exp) in _memory.items() if exp <= cutoff]:
        _memory.pop(state, None)


_client_singleton = None
_client_failed = False


def _client():
    """Return a pooled Redis client, or None if Redis is unavailable.

    Every caller treats None as "use the fallback"; a login must not fail
    because the cache is down.
    """
    global _client_singleton, _client_failed
    if _client_singleton is not None or _client_failed:
        return _client_singleton
    try:
        import redis.asyncio as redis

        from app.core.config import get_settings

        _client_singleton = redis.from_url(
            get_settings().redis_url, decode_responses=True)
    except Exception as exc:
        # Warning, not debug: this fell back silently once already, and the
        # fallback works well enough that nothing else reports the difference.
        logger.warning("login state: redis unavailable, using in-memory store (%s)", exc)
        _client_failed = True
    return _client_singleton


async def remember(state: str, redirect_uri: str) -> None:
    """Store the redirect URI a login started from, keyed by its state token."""
    client = _client()
    if client is not None:
        try:
            await client.setex(_KEY_PREFIX + state, TTL_SECONDS, redirect_uri)
            return
        except Exception as exc:
            logger.warning("login state: redis write failed, using memory (%s)", exc)

    _prune()
    _memory[state] = (redirect_uri, time.time() + TTL_SECONDS)


async def consume(state: str) -> Optional[str]:
    """Return the redirect URI for this state token and invalidate it.

    Single use: a state token that has already been redeemed must not open a
    second callback. Returns None if the token is unknown or expired.
    """
    client = _client()
    if client is not None:
        try:
            key = _KEY_PREFIX + state
            value = await client.get(key)
            if value is not None:
                await client.delete(key)
                return value
        except Exception as exc:
            logger.warning("login state: redis read failed, using memory (%s)", exc)

    _prune()
    entry = _memory.pop(state, None)
    if entry is None:
        return None
    redirect_uri, expires_at = entry
    return redirect_uri if expires_at > time.time() else None
