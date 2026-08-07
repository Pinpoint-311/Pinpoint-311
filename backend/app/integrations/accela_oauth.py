"""Accela OAuth2 authorization-code sign-in.

Accela's Construct API supports two OAuth2 grants (see
https://developer.accela.com/docs/construct-authCodeFlow.html):

  * **authorization_code** — the agency's own staff sign in at Accela and
    consent. We get back a short-lived access token *and* a refresh token that
    can be exchanged for new access tokens indefinitely. This is the path this
    module implements, and the one the admin UI now leads with.
  * **password** — we hold the agency's username and password and re-present
    them on every call. Still supported by the connector as a fallback for
    towns whose Accela administrator prefers a service account, but it means a
    government password lives in our vault, which most towns would rather avoid.

The developer-portal app (client id + secret) belongs to *Pinpoint*, not to each
town: one registered app serves every deployment, so its credentials are
deployment-level configuration (environment variables or the Secret Manager)
rather than something a clerk is asked to paste into a form. Only the per-town
refresh token goes through the integrations credential vault.

The ``state`` parameter is an HMAC-signed, short-lived, purpose-bound token
minted by the authenticated ``/oauth/start`` endpoint. Because Accela's callback
arrives as a plain browser redirect with no session of its own, that signature
is the only thing standing between us and an attacker who tricks an admin into
hitting the callback with *their* authorization code — which would silently bind
the town's integration to the attacker's Accela account.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

DEFAULT_AUTH_BASE = "https://auth.accela.com"

# Scope groups requested for the access token. "records" alone is what the
# password grant historically asked for, which leaves the nightly asset sync
# (GET /v4/assets) reaching for an endpoint the token was never authorized for.
DEFAULT_SCOPE = "records assets"

# How long an admin has to finish the Accela login before the state token — and
# with it the authorization attempt — expires.
STATE_TTL_SECONDS = 600

CALLBACK_PATH = "/api/integrations/accela/oauth/callback"


# ---------------------------------------------------------------------------
# Deployment-level app credentials
# ---------------------------------------------------------------------------

# Environment variables win over the Secret Manager so a container can be handed
# the app credentials at boot without a database round-trip; the Secret Manager
# entries are the durable, rotatable home for hosted deployments.
CLIENT_ID_KEY = "ACCELA_CLIENT_ID"
CLIENT_SECRET_KEY = "ACCELA_CLIENT_SECRET"
REDIRECT_URI_KEY = "ACCELA_REDIRECT_URI"


async def _deployment_value(key: str) -> Optional[str]:
    value = os.getenv(key)
    if value:
        return value.strip()
    try:
        from app.services.secret_manager import get_secret
    except Exception:
        return None
    try:
        value = await get_secret(key)
    except Exception as e:
        from app.core.sanitize import sanitize_for_log
        logger.warning("[Accela OAuth] Could not read %s: %s",
                       sanitize_for_log(key), sanitize_for_log(str(e)))
        return None
    return value.strip() if value else None


async def app_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Pinpoint's own Accela developer-portal app id and secret."""
    return await _deployment_value(CLIENT_ID_KEY), await _deployment_value(CLIENT_SECRET_KEY)


async def is_configured() -> bool:
    client_id, client_secret = await app_credentials()
    return bool(client_id and client_secret)


async def redirect_uri_for(db, request_base_url: Optional[str] = None) -> str:
    """The callback URL handed to Accela.

    It must match the value registered on the developer-portal app *exactly*,
    so it is resolved in order of how much the source actually knows:

    1. ``ACCELA_REDIRECT_URI`` — the explicit pin, for shared-host deployments
       or a registered redirect that differs from the town's own domain.
    2. The deployment's configured public origin (``public_origin``: the
       township's custom domain, else the ``DOMAIN`` env var) plus the callback
       path. This is the normal case: behind the TLS-terminating proxy,
       ``request.base_url`` is ``http://`` and never matches what Accela has
       registered.
    3. The request's own base URL, as a logged last resort for deployments
       that have configured nothing at all.
    """
    configured = await _deployment_value(REDIRECT_URI_KEY)
    if configured:
        return configured
    origin = None
    if db is not None:
        try:
            from app.api.system import public_origin
            origin = await public_origin(db)
        except Exception as e:
            from app.core.sanitize import sanitize_for_log
            logger.warning("[Accela OAuth] Could not look up the public origin: %s",
                           sanitize_for_log(str(e)))
    if origin:
        return f"{origin.rstrip('/')}{CALLBACK_PATH}"
    logger.warning(
        "[Accela OAuth] No ACCELA_REDIRECT_URI and no public origin (custom domain "
        "or DOMAIN) is configured; falling back to the request's own base URL %s. "
        "Behind a TLS-terminating proxy this is usually http:// and will not match "
        "the redirect URI registered with Accela.",
        request_base_url,
    )
    return f"{str(request_base_url or '').rstrip('/')}{CALLBACK_PATH}"


# ---------------------------------------------------------------------------
# CSRF state
# ---------------------------------------------------------------------------

def _signing_key() -> bytes:
    from app.core.config import get_settings
    return hashlib.sha256(
        f"accela-oauth-state:{get_settings().secret_key}".encode()
    ).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_state(integration_id: int, user_id: Any, redirect_uri: str) -> str:
    """Mint a state token binding this authorization attempt to one integration,
    one admin, one redirect URI, and one ten-minute window."""
    payload = {
        "iid": int(integration_id),
        "uid": str(user_id),
        "ru": redirect_uri,
        "iat": int(time.time()),
        "n": secrets.token_urlsafe(12),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_state(state: str, max_age: int = STATE_TTL_SECONDS) -> Optional[Dict[str, Any]]:
    """Return the state's payload, or None if it is forged, tampered with, or
    stale. Never raises — a bad state is an ordinary hostile input."""
    if not state or not isinstance(state, str) or state.count(".") != 1:
        return None
    body, sig = state.split(".", 1)
    try:
        expected = _b64(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
    except Exception:
        return None
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if not isinstance(payload, dict) or "iat" not in payload or "iid" not in payload:
        return None
    age = time.time() - float(payload.get("iat") or 0)
    if age < -60 or age > max_age:  # small negative tolerance for clock skew
        return None
    return payload


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------

class OAuthError(Exception):
    """Raised when Accela refuses a token request, or when the flow's own
    configuration is unusable."""


def auth_base(config: Optional[Dict[str, Any]] = None) -> str:
    """The Accela authorization server this flow talks to.

    Defaults to https://auth.accela.com. The override exists for Accela's
    non-production stacks — and only for them. The token exchange posts the
    *deployment-level* client secret to whatever host this returns, and
    ``auth_base`` is an admin-settable integration config key, so an arbitrary
    override would let one town's admin point the flow at their own server and
    collect the secret shared by every town on the host. An override must
    therefore pass the same public-URL guard as every connector request, and
    its host must be accela.com or a subdomain of it.
    """
    override = (config or {}).get("auth_base")
    if not override:
        return DEFAULT_AUTH_BASE
    base = str(override).strip().rstrip("/")
    host = (urlparse(base).hostname or "").lower()
    if host != "accela.com" and not host.endswith(".accela.com"):
        raise OAuthError(
            "Refusing the configured Accela auth_base: the sign-in flow only "
            "talks to accela.com hosts."
        )
    from app.integrations.base import ConnectorError, _assert_public_url
    try:
        _assert_public_url(base)
    except ConnectorError as e:
        raise OAuthError(f"Refusing the configured Accela auth_base: {e}")
    return base


def scope_for(config: Optional[Dict[str, Any]] = None) -> str:
    return ((config or {}).get("scope") or DEFAULT_SCOPE).strip()


def authorize_url(*, client_id: str, redirect_uri: str, state: str,
                  agency_name: str, environment: str = "PROD",
                  config: Optional[Dict[str, Any]] = None) -> str:
    """The Accela login/consent URL to send the admin's browser to."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "environment": (environment or "PROD").upper(),
        "agency_name": agency_name,
        "scope": scope_for(config),
        "state": state,
    }
    return f"{auth_base(config)}/oauth2/authorize?{urlencode(params)}"


async def exchange_code(*, code: str, redirect_uri: str,
                        config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Trade an authorization code for an access token + refresh token."""
    client_id, client_secret = await app_credentials()
    if not (client_id and client_secret):
        raise OAuthError(
            "This deployment has no Accela app configured. Set ACCELA_CLIENT_ID "
            "and ACCELA_CLIENT_SECRET before connecting Accela."
        )
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0),
                                 follow_redirects=False) as client:
        resp = await client.post(
            f"{auth_base(config)}/oauth2/token",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "x-accela-appid": client_id,
            },
        )
    if resp.status_code >= 400:
        from app.integrations.base import _redact_secrets
        raise OAuthError(
            f"Accela rejected the sign-in: HTTP {resp.status_code} — "
            f"{_redact_secrets(resp.text[:300])}"
        )
    tokens = resp.json()
    if not tokens.get("refresh_token"):
        raise OAuthError(
            "Accela returned no refresh token. Ask your Accela administrator to "
            "enable refresh tokens for the Pinpoint 311 app."
        )
    return tokens
