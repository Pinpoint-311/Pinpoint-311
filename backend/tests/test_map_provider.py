"""Tests for map-provider selection.

The failure that matters here is a town ending up with no map. A settings row
written by a newer version, a typo, or a provider whose credentials were never
finished must all degrade to something that works rather than to a blank page.
"""

import pytest

mp = pytest.importorskip("app.services.map_provider")


# ---- choosing a provider ---------------------------------------------------

def test_google_is_the_default():
    """Least work for a clerk: one API key, no enrolment, familiar imagery."""
    assert mp.DEFAULT_PROVIDER == "google"
    assert mp.normalize_provider(None) == "google"
    assert mp.normalize_provider("") == "google"


def test_unknown_provider_falls_back_rather_than_failing():
    """A settings row from a newer version must not leave a town mapless."""
    for value in ("nonsense", "mapbox", "  ", "GOOGL"):
        assert mp.normalize_provider(value) == "google"


def test_provider_names_are_case_and_space_insensitive():
    assert mp.normalize_provider("  Esri ") == "esri"
    assert mp.normalize_provider("AZURE") == "azure"


@pytest.mark.parametrize("provider", ["google", "esri", "apple", "azure"])
def test_every_advertised_provider_resolves_to_itself(provider):
    assert mp.normalize_provider(provider) == provider


# ---- geocoding is chosen separately ----------------------------------------

def test_a_render_only_provider_would_get_the_backend_geocoder():
    """Every provider offered today can geocode, but the fallback has to work:
    a renderer-only provider defaulting to itself would leave address search
    silently dead, which is worse than any wrong answer."""
    assert mp.geocoder_for("some-render-only-provider", None) == "backend"


@pytest.mark.parametrize("provider", ["google", "esri", "apple", "azure"])
def test_a_capable_provider_geocodes_for_itself_by_default(provider):
    assert mp.geocoder_for(provider, None) == provider


def test_geocoding_can_be_pointed_somewhere_else_entirely():
    """Render with Esri from the county's basemap, geocode with Google. This
    mix is most of why the Esri adapter is worth building."""
    assert mp.geocoder_for("esri", "google") == "google"
    assert mp.geocoder_for("google", "esri") == "esri"
    assert mp.geocoder_for("google", "backend") == "backend"


def test_an_unknown_geocoder_falls_back_to_the_renderer():
    assert mp.geocoder_for("google", "nonsense") == "google"


# ---- credentials -----------------------------------------------------------

@pytest.mark.asyncio
async def test_only_the_selected_provider_s_secrets_are_read():
    """An Azure town must not receive a Google key just because one happens
    to be configured. Sending credentials a provider does not use leaks them to
    every browser that loads the page."""
    requested = []

    async def fake_get_secret(name):
        requested.append(name)
        return f"value-for-{name}"

    await mp.resolve_credentials("azure", fake_get_secret)
    assert not any("GOOGLE" in name for name in requested)


@pytest.mark.asyncio
async def test_credentials_are_returned_under_stable_field_names():
    async def fake_get_secret(name):
        return "secret"

    creds = await mp.resolve_credentials("google", fake_get_secret)
    assert creds["apiKey"] == "secret"


@pytest.mark.asyncio
async def test_a_secret_read_failure_is_reported_as_missing_not_raised():
    """A broken secret backend should show "not configured" in the admin
    console, not 500 the endpoint that every page calls on load."""
    async def failing(name):
        raise RuntimeError("secret manager unreachable")

    creds = await mp.resolve_credentials("google", failing)
    assert creds["apiKey"] is None
    assert mp.missing_requirements("google", creds) == ["apiKey"]


@pytest.mark.asyncio
async def test_unknown_provider_resolves_the_default_s_credentials():
    async def fake_get_secret(name):
        return name

    creds = await mp.resolve_credentials("nonsense", fake_get_secret)
    assert "apiKey" in creds


def test_every_credential_field_has_setup_help():
    """A clerk reading "ArcGIS API key" with no further instruction has to go
    and find out what that is. Every field says where to get it."""
    for provider, spec in mp.MAP_CATALOG.items():
        help_text = spec.get("field_help", {})
        for field in spec["credential_fields"]:
            assert help_text.get(field["key"]), f"{provider}.{field['key']} has no help"


def test_a_provider_with_no_required_secrets_is_never_blocked():
    """missing_requirements must return empty rather than inventing a
    requirement, or such a provider could never be selected."""
    assert mp.missing_requirements("google", {"apiKey": "k"}) == []


def test_a_provider_missing_its_key_is_reported():
    assert mp.missing_requirements("esri", {"apiKey": None}) == ["apiKey"]
    assert mp.missing_requirements("esri", {"apiKey": "k"}) == []


def test_apple_wants_a_signing_key_not_a_static_api_key():
    """MapKit JS authenticates with a short-lived JWT the server signs, so the
    town supplies a team id, a key id and a .p8 -- never an API key."""
    keys = {f["key"] for f in mp.MAP_CATALOG["apple"]["credential_fields"]}
    assert keys == {"APPLE_MAPKIT_TEAM_ID", "APPLE_MAPKIT_KEY_ID", "APPLE_MAPKIT_PRIVATE_KEY"}


@pytest.mark.asyncio
async def test_the_apple_private_key_is_never_sent_to_a_browser():
    """It signs tokens for the whole developer team and Apple lets you download
    it once. Only the signed token may leave the server."""
    async def fake_get_secret(name):
        return f"value-{name}"

    creds = await mp.resolve_credentials("apple", fake_get_secret)
    assert not any("PRIVATE" in str(v).upper() for v in creds.values())
    assert "APPLE_MAPKIT_PRIVATE_KEY" not in creds


# ---- the admin catalog -----------------------------------------------------

def test_catalog_puts_the_recommended_provider_first():
    catalog = mp.catalog()
    assert catalog[0]["id"] == "google"
    assert catalog[0]["recommended"] is True


def test_catalog_covers_every_provider_and_says_what_each_needs():
    catalog = mp.catalog()
    assert {e["id"] for e in catalog} == set(mp.MAP_CATALOG)
    for entry in catalog:
        assert entry["label"] and entry["setup"]
        assert isinstance(entry["requires"], list)


def test_catalog_reports_geocoding_capability():
    by_id = {e["id"]: e for e in mp.catalog()}
    assert by_id["google"]["can_geocode"] is True
    assert by_id["esri"]["can_geocode"] is True


def test_exactly_one_provider_is_recommended():
    """Two recommendations is no recommendation."""
    assert sum(1 for e in mp.catalog() if e["recommended"]) == 1
