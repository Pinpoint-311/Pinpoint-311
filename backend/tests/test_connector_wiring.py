"""Proof that every advertised credential actually reaches a working client.

The admin UI offers a set of credential fields per provider. Nothing previously
checked that filling those fields in produces a usable connector -- a provider
could advertise three keys, store all three, show a green badge, and be wired to
nothing. A clerk would have no way to tell.

Grep cannot answer this. Credentials are read three different ways: literally
(`get_secret("ENTRA_TENANT_ID")`), by computed name (`f"{prefix}_ISSUER"` for
Okta and OIDC), and out of a resolved dict (`creds.get("AZURE_OPENAI_DEPLOYMENT")`).
A first pass of this audit searched for literals and reported 18 of 35 keys
unwired; every one was a false positive. So these tests drive the real resolver
for each capability with a fully-populated fake secret store and assert it
produces something, then empty it and assert it does not.

What this catches: a provider added to a catalog whose resolver was never
extended. That provider will advertise fields, accept them, badge itself
configured, and return None here.
"""

import pytest


def fake_store(monkeypatch, values: dict):
    """Point the secret manager at a dict."""
    async def get_secret(key, *a, **kw):
        return values.get(key)

    import app.services.secret_manager as sm
    monkeypatch.setattr(sm, "get_secret", get_secret)
    return get_secret


def all_fields(catalog_entry) -> list:
    return [f["key"] for f in catalog_entry["credential_fields"]]


def filled(keys, extra=None):
    """A plausible value for every key. URLs need to parse as URLs."""
    out = {}
    for k in keys:
        if "ISSUER" in k or "ENDPOINT" in k or "URL" in k:
            out[k] = "https://example.gov"
        else:
            out[k] = f"value-for-{k}"
    out.update(extra or {})
    return out


# ---- identity ---------------------------------------------------------------

@pytest.mark.parametrize("provider", ["auth0", "entra", "okta", "oidc"])
@pytest.mark.asyncio
async def test_every_identity_provider_resolves_when_filled(monkeypatch, provider):
    """Staff sign-in is the one capability where being wired to nothing locks
    everyone out, and it is the one where three of four providers are reached by
    a computed key name rather than a literal."""
    from app.services.identity import IDENTITY_CATALOG, IDENTITY_PROVIDER_KEY, resolve_identity_config

    values = filled(all_fields(IDENTITY_CATALOG[provider]))
    values[IDENTITY_PROVIDER_KEY] = provider
    fake_store(monkeypatch, values)

    config = await resolve_identity_config()
    assert config is not None, f"{provider} advertises fields but resolves to nothing"
    assert config["provider"] == provider
    assert config["client_id"] and config["client_secret"]
    assert config["issuer_base"].startswith("http")


@pytest.mark.parametrize("provider", ["auth0", "entra", "okta", "oidc"])
@pytest.mark.asyncio
async def test_an_unconfigured_identity_provider_resolves_to_none(monkeypatch, provider):
    """None is how the caller knows to fall back rather than half-configure a
    login flow."""
    from app.services.identity import IDENTITY_PROVIDER_KEY, resolve_identity_config

    fake_store(monkeypatch, {IDENTITY_PROVIDER_KEY: provider})
    assert await resolve_identity_config() is None


@pytest.mark.asyncio
async def test_every_identity_provider_in_the_catalog_is_reachable(monkeypatch):
    """The guard that matters: a provider added to the catalog without extending
    the resolver returns None here even fully populated."""
    from app.services.identity import IDENTITY_CATALOG, IDENTITY_PROVIDER_KEY, resolve_identity_config

    for provider, meta in IDENTITY_CATALOG.items():
        values = filled(all_fields(meta))
        values[IDENTITY_PROVIDER_KEY] = provider
        fake_store(monkeypatch, values)
        assert await resolve_identity_config() is not None, \
            f"{provider} is in the catalog but the resolver does not handle it"


# ---- translation ------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_translation_provider_builds(monkeypatch):
    from app.services import translation_providers as tp

    for entry in tp.catalog_for_api():
        provider = entry["provider"]
        values = filled([f["key"] for f in entry["credential_fields"]])
        values[tp.TRANSLATION_PROVIDER_KEY] = provider
        # AWS reaches for a region that is not one of its advertised fields.
        values.setdefault("AWS_REGION", "us-east-1")
        fake_store(monkeypatch, values)
        assert await tp.get_translation_provider() is not None, \
            f"translation/{provider} advertises fields but builds nothing"


# ---- maps -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_map_provider_resolves_its_own_credentials():
    """Maps resolves through the catalog, so a new provider is wired the moment
    it is listed -- but the private key must never come back, because it is
    signed server-side and the resolved dict reaches a browser."""
    from app.services.map_provider import MAP_CATALOG, resolve_credentials

    for provider, spec in MAP_CATALOG.items():
        keys = [f["key"] for f in spec["credential_fields"]]
        values = filled(keys)

        async def get_secret(key, *a, **kw):
            return values.get(key)

        resolved = await resolve_credentials(provider, get_secret)
        # Asserted by value, not by key: the resolver deliberately renames
        # secrets to the client-facing names each SDK expects (apiKey, styleId),
        # so checking for GOOGLE_MAPS_API_KEY in the output tests the wrong
        # contract -- which is how this test first failed.
        arrived = {v for v in resolved.values() if v}
        for key in keys:
            if key.endswith("PRIVATE_KEY"):
                assert values[key] not in arrived, \
                    f"{provider}: {key} must never reach a browser payload"
            else:
                assert values[key] in arrived, \
                    f"maps/{provider}: {key} advertised but never resolved"


# ---- ai ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_ai_provider_constructs():
    """Each provider's advertised credentials must reach a real client object.

    Driven through build_ai_provider directly, which is the pure half of the
    factory -- get_ai_provider wraps it in secret lookups and a database
    session, and neither is the thing under test here.
    """
    from app.services.ai.registry import AI_CATALOG, build_ai_provider

    for provider, meta in AI_CATALOG.items():
        creds = filled(all_fields(meta))
        creds.setdefault("AWS_REGION", "us-east-1")
        built = build_ai_provider(provider, None, creds)
        assert built is not None, \
            f"ai/{provider} advertises credentials but build_ai_provider returns nothing"


def test_no_ai_provider_builds_without_its_credentials():
    """The other direction. Returning a client with no key would defer the
    failure to the first resident report instead of the admin console."""
    from app.services.ai.registry import AI_CATALOG, build_ai_provider

    for provider in AI_CATALOG:
        assert build_ai_provider(provider, None, {}) is None, \
            f"ai/{provider} built a client from nothing"
