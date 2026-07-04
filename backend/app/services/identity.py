"""Generic OIDC identity layer (Auth0 / Microsoft Entra ID / Okta / any OIDC).

The app already authenticates over OpenID Connect, so supporting multiple IdPs
is a matter of resolving each provider's issuer and using standard OIDC
**discovery** (`.well-known/openid-configuration`) for the authorize/token/
jwks/userinfo endpoints. Auth0 remains the default and behaves identically
(its discovery document yields the same endpoints the app used before, with a
hardcoded fallback if discovery is briefly unreachable).

Switching a live deployment to Entra or Okta is config-only, but the
interactive login/callback should be validated against a real tenant before
production (token verification here is standards-based and unit-tested).
"""

import logging
from typing import Any, Dict, Optional

import httpx
import jwt

logger = logging.getLogger(__name__)

IDENTITY_PROVIDER_KEY = "IDENTITY_PROVIDER"

# cache of issuer_base -> discovery document
_discovery_cache: Dict[str, Dict[str, Any]] = {}

IDENTITY_CATALOG: Dict[str, Dict[str, Any]] = {
    "auth0": {
        "name": "Auth0",
        "description": "Auth0 by Okta — the default. Works with any Auth0 tenant.",
        "credential_fields": [
            {"key": "AUTH0_DOMAIN", "label": "Auth0 Domain", "secret": False},
            {"key": "AUTH0_CLIENT_ID", "label": "Client ID", "secret": False},
            {"key": "AUTH0_CLIENT_SECRET", "label": "Client Secret", "secret": True},
        ],
        "field_help": {
            "AUTH0_DOMAIN": "e.g. yourorg.us.auth0.com",
            "AUTH0_CLIENT_ID": "From your Auth0 Regular Web Application.",
            "AUTH0_CLIENT_SECRET": "From the same Auth0 application.",
        },
    },
    "entra": {
        "name": "Microsoft Entra ID",
        "description": "Azure AD / Entra ID — ideal for states already on Microsoft 365.",
        "credential_fields": [
            {"key": "ENTRA_TENANT_ID", "label": "Directory (tenant) ID", "secret": False},
            {"key": "ENTRA_CLIENT_ID", "label": "Application (client) ID", "secret": False},
            {"key": "ENTRA_CLIENT_SECRET", "label": "Client Secret", "secret": True},
            {"key": "ENTRA_AUTHORITY", "label": "Authority host (optional; Gov = login.microsoftonline.us)", "secret": False},
        ],
        "field_help": {
            "ENTRA_TENANT_ID": "Directory (tenant) ID from the Entra admin center.",
            "ENTRA_CLIENT_ID": "App registration's Application (client) ID.",
            "ENTRA_CLIENT_SECRET": "A client secret from the app registration.",
            "ENTRA_AUTHORITY": "Leave blank for commercial cloud; use login.microsoftonline.us for Azure Government.",
        },
    },
    "okta": {
        "name": "Okta",
        "description": "Okta / Okta for Government (FedRAMP).",
        "credential_fields": [
            {"key": "OKTA_ISSUER", "label": "Issuer URL", "secret": False},
            {"key": "OKTA_CLIENT_ID", "label": "Client ID", "secret": False},
            {"key": "OKTA_CLIENT_SECRET", "label": "Client Secret", "secret": True},
        ],
        "field_help": {
            "OKTA_ISSUER": "e.g. https://your-org.okta.com/oauth2/default",
            "OKTA_CLIENT_ID": "From your Okta OIDC Web app.",
            "OKTA_CLIENT_SECRET": "From the same Okta app.",
        },
    },
    "oidc": {
        "name": "Generic OIDC",
        "description": "Any OpenID Connect provider via its issuer URL.",
        "credential_fields": [
            {"key": "OIDC_ISSUER", "label": "Issuer URL", "secret": False},
            {"key": "OIDC_CLIENT_ID", "label": "Client ID", "secret": False},
            {"key": "OIDC_CLIENT_SECRET", "label": "Client Secret", "secret": True},
        ],
        "field_help": {
            "OIDC_ISSUER": "The provider's issuer (must serve /.well-known/openid-configuration).",
            "OIDC_CLIENT_ID": "OAuth client id.",
            "OIDC_CLIENT_SECRET": "OAuth client secret.",
        },
    },
}


def catalog_for_api():
    return [{"provider": k, **v} for k, v in IDENTITY_CATALOG.items()]


async def resolve_identity_config(db=None) -> Optional[Dict[str, Any]]:
    """Resolve the active identity provider + its OIDC parameters from secrets.
    Returns None if the selected provider isn't configured."""
    from app.services.secret_manager import get_secret

    provider = (await get_secret(IDENTITY_PROVIDER_KEY)) or "auth0"
    provider = provider.strip().lower()

    if provider == "auth0":
        domain = await get_secret("AUTH0_DOMAIN")
        cid = await get_secret("AUTH0_CLIENT_ID")
        secret = await get_secret("AUTH0_CLIENT_SECRET")
        if not all([domain, cid, secret]):
            return None
        return {
            "provider": "auth0", "domain": domain, "client_id": cid, "client_secret": secret,
            "issuer_base": f"https://{domain}",
            "extra_authorize_params": {"audience": f"https://{domain}/api/v2/"},
        }
    if provider == "entra":
        tenant = await get_secret("ENTRA_TENANT_ID")
        cid = await get_secret("ENTRA_CLIENT_ID")
        secret = await get_secret("ENTRA_CLIENT_SECRET")
        if not all([tenant, cid, secret]):
            return None
        authority = (await get_secret("ENTRA_AUTHORITY")) or "login.microsoftonline.com"
        return {
            "provider": "entra", "client_id": cid, "client_secret": secret,
            "issuer_base": f"https://{authority}/{tenant}/v2.0",
            "extra_authorize_params": {},
        }
    if provider in ("okta", "oidc"):
        prefix = provider.upper()
        issuer = await get_secret(f"{prefix}_ISSUER")
        cid = await get_secret(f"{prefix}_CLIENT_ID")
        secret = await get_secret(f"{prefix}_CLIENT_SECRET")
        if not all([issuer, cid, secret]):
            return None
        return {
            "provider": provider, "client_id": cid, "client_secret": secret,
            "issuer_base": issuer.rstrip("/"),
            "extra_authorize_params": {},
        }
    return None


async def get_oidc_metadata(config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch (and cache) the OIDC discovery document for this provider.
    Falls back to Auth0's conventional endpoints if discovery is unreachable."""
    issuer_base = config["issuer_base"]
    if issuer_base in _discovery_cache:
        return _discovery_cache[issuer_base]
    url = f"{issuer_base}/.well-known/openid-configuration"
    try:
        # SSRF guard: the issuer is admin-supplied — refuse URLs that resolve
        # to internal/loopback/metadata addresses (same policy as connectors).
        from app.integrations.base import _assert_public_url
        _assert_public_url(url)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            meta = resp.json()
    except Exception as e:
        if config["provider"] == "auth0":
            # Backward-compatible fallback: Auth0's fixed endpoint scheme
            domain = config["domain"]
            meta = {
                "authorization_endpoint": f"https://{domain}/authorize",
                "token_endpoint": f"https://{domain}/oauth/token",
                "jwks_uri": f"https://{domain}/.well-known/jwks.json",
                "userinfo_endpoint": f"https://{domain}/userinfo",
                "issuer": f"https://{domain}/",
            }
        else:
            raise
    _discovery_cache[issuer_base] = meta
    return meta


def clear_discovery_cache():
    _discovery_cache.clear()


async def verify_oidc_token(token: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Standards-based OIDC token verification: RS256 via the provider's JWKS,
    audience = client_id, issuer from discovery."""
    from fastapi import HTTPException

    meta = await get_oidc_metadata(config)
    # SSRF guard: jwks_uri comes from the discovery doc of an admin-supplied
    # issuer — refuse internal/loopback/metadata targets before fetching keys.
    from app.integrations.base import _assert_public_url
    _assert_public_url(meta["jwks_uri"])
    async with httpx.AsyncClient(timeout=10.0) as client:
        jwks_resp = await client.get(meta["jwks_uri"])
        jwks_resp.raise_for_status()
        jwks = jwks_resp.json()

    kid = jwt.get_unverified_header(token).get("kid")
    key = None
    for jwk in jwks.get("keys", []):
        if jwk.get("kid") == kid:
            key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
            break
    if not key:
        raise HTTPException(status_code=401, detail="Unable to find appropriate signing key")

    try:
        return jwt.decode(
            token, key, algorithms=["RS256"],
            audience=config["client_id"],
            issuer=meta.get("issuer"),
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Invalid token issuer")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token validation failed: {str(e)}")
