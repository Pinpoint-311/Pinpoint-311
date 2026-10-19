"""OIDC ID-token verification must check the issuer and expiry, not just the key.

PyJWT verifies `iss`, `aud` and `exp` only when it is told what to expect AND
the claim is present. Two gaps followed from that:

  * `issuer=meta.get("issuer")` -- a discovery document with no `issuer` passed
    None, and PyJWT reads None as "skip the issuer check". Entra signs every
    tenant's tokens with the same keys, so the issuer is the thing that says a
    token came from this town's tenant rather than someone else's.
  * no `require` -- a correctly signed token with no `exp` never expired.

Both are now refused.
"""

import json
import time

import pytest

pytest.importorskip("fastapi.routing")
pytest.importorskip("jwt.api_jwt")
pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.integrations import base as integrations_base  # noqa: E402
from app.services import identity  # noqa: E402

ISSUER = "https://login.example.test/tenant-a/v2.0"
CLIENT_ID = "pinpoint-client"
CONFIG = {"provider": "entra", "issuer_base": ISSUER, "client_id": CLIENT_ID}

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks():
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key()))
    jwk["kid"] = "k1"
    return {"keys": [jwk]}


def _token(**overrides):
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "u1", "email": "clerk@town.example",
              "iat": now, "exp": now + 300}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": "k1"})


class _FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return _jwks()


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _FakeResponse()


@pytest.fixture
def discovery(monkeypatch):
    meta = {"issuer": ISSUER, "jwks_uri": "https://login.example.test/keys"}

    async def _meta(config):
        return meta

    monkeypatch.setattr(identity, "get_oidc_metadata", _meta)
    monkeypatch.setattr(integrations_base, "_assert_public_url", lambda url: None)
    monkeypatch.setattr(identity.httpx, "AsyncClient", _FakeClient)
    return meta


@pytest.mark.asyncio
async def test_a_good_token_is_accepted(discovery):
    claims = await identity.verify_oidc_token(_token(), CONFIG)
    assert claims["sub"] == "u1"


@pytest.mark.asyncio
async def test_a_token_from_another_tenant_is_refused(discovery):
    with pytest.raises(HTTPException) as exc:
        await identity.verify_oidc_token(_token(iss="https://login.example.test/tenant-b/v2.0"), CONFIG)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_a_discovery_document_without_an_issuer_refuses_every_token(discovery):
    """The regression: this used to disable the issuer check, so the
    other-tenant token above was accepted."""
    discovery.pop("issuer")
    with pytest.raises(HTTPException) as exc:
        await identity.verify_oidc_token(_token(iss="https://login.example.test/tenant-b/v2.0"), CONFIG)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("claim", ["exp", "iss", "aud"])
async def test_a_token_missing_a_mandatory_claim_is_refused(discovery, claim):
    with pytest.raises(HTTPException) as exc:
        await identity.verify_oidc_token(_token(**{claim: None}), CONFIG)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_an_expired_token_is_refused(discovery):
    with pytest.raises(HTTPException) as exc:
        await identity.verify_oidc_token(_token(exp=int(time.time()) - 600), CONFIG)
    assert exc.value.status_code == 401
