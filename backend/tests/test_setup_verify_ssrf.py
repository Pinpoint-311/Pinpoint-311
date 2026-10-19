"""The setup check's Auth0 probe must not reach internal addresses.

POST /api/setup/verify fetched https://{AUTH0_DOMAIN}/.well-known/openid-configuration
with whatever AUTH0_DOMAIN held. The /auth0/configure route pins the domain to
*.auth0.com, but the generic secrets form only shape-checks it and never blocks,
so the stored value could name the metadata service or a host on the private
network -- and the response said whether it answered, plus the connection error.
The probe now goes through the same public-address guard as OIDC discovery.
"""

import pytest

pytest.importorskip("fastapi.routing")
pytest.importorskip("httpx")

from app.api import setup as setup_api  # noqa: E402
from app.integrations.base import ConnectorError  # noqa: E402


class _NoNetwork:
    def __init__(self, *a, **k):
        raise AssertionError("an internal address must be refused before any request is made")


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", [
    "127.0.0.1",
    "169.254.169.254",
    "10.0.0.5:8443",
    "attacker@127.0.0.1",
    "[::1]",
])
async def test_internal_auth0_domain_is_refused(monkeypatch, domain):
    monkeypatch.setattr(setup_api.httpx, "AsyncClient", _NoNetwork)
    with pytest.raises(ConnectorError):
        await setup_api._auth0_discovery_reachable(domain)


@pytest.mark.asyncio
async def test_public_auth0_domain_is_probed(monkeypatch):
    from app.integrations import base as integrations_base

    seen = []
    monkeypatch.setattr(integrations_base, "_assert_public_url", lambda url: seen.append(url))

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            seen.append(url)
            return _Resp()

    monkeypatch.setattr(setup_api.httpx, "AsyncClient", _Client)
    assert await setup_api._auth0_discovery_reachable("town.us.auth0.com") is True
    assert seen == ["https://town.us.auth0.com/.well-known/openid-configuration"] * 2
