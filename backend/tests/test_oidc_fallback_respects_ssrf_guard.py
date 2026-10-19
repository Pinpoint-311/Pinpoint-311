"""The Auth0 discovery fallback must not undo the SSRF guard.

get_oidc_metadata guards the discovery URL with _assert_public_url and, for
Auth0, falls back to Auth0's fixed endpoint scheme when discovery fails. The
fallback caught every exception -- including the guard's own refusal -- and
rebuilt the endpoints from the same domain, so an AUTH0_DOMAIN pointing at an
internal address produced a token_endpoint on that address anyway.

A refusal now propagates. A lookup or network failure still falls back, which
is what the fallback is for.
"""

import pytest

pytest.importorskip("fastapi.routing")
pytest.importorskip("httpx")

from app.integrations import base as integrations_base  # noqa: E402
from app.services import identity  # noqa: E402


def _config(domain):
    return {"provider": "auth0", "domain": domain, "issuer_base": f"https://{domain}"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    identity.clear_discovery_cache()
    yield
    identity.clear_discovery_cache()


@pytest.mark.asyncio
async def test_an_internal_auth0_domain_is_refused_not_rebuilt():
    with pytest.raises(integrations_base.UnsafeURLRefused):
        await identity.get_oidc_metadata(_config("127.0.0.1"))


@pytest.mark.asyncio
async def test_metadata_address_is_refused_not_rebuilt():
    with pytest.raises(integrations_base.UnsafeURLRefused):
        await identity.get_oidc_metadata(_config("169.254.169.254"))


@pytest.mark.asyncio
async def test_an_unreachable_public_domain_still_falls_back(monkeypatch):
    """A DNS failure is not a refusal: the fallback is still allowed."""

    def unresolvable(url):
        raise integrations_base.ConnectorError("Could not resolve host tenant.auth0.com")

    monkeypatch.setattr(integrations_base, "_assert_public_url", unresolvable)
    meta = await identity.get_oidc_metadata(_config("tenant.auth0.com"))
    assert meta["token_endpoint"] == "https://tenant.auth0.com/oauth/token"
    assert meta["issuer"] == "https://tenant.auth0.com/"


def test_refusal_is_still_a_connector_error():
    """Existing `except ConnectorError` handlers keep catching refusals."""
    assert issubclass(integrations_base.UnsafeURLRefused, integrations_base.ConnectorError)
