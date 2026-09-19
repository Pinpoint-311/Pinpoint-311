"""`GET /api/gis/config` is public, so what it returns is published.

It has no authentication and cannot have one: a resident's map has to be
configured before the resident has done anything. It was answering the open
internet with `google_maps_api_key`, `ARCGIS_API_KEY` and `AZURE_MAPS_KEY` --
confirmed returning real values on the live site.

The Google key is the sharp end. The same secret is used for server-side billed
calls (services/geocode_dispatch, services/translation), so anyone who loaded
the town's website could copy it and spend the town's account from their own
machine, with nothing to notice it but the invoice.

A key delivered to a browser is public; that part is unavoidable and is not the
finding. The finding is that it was the SAME key as the server's. So /config now
reads only browser-scoped secret names, and a town that has configured only the
server key gets no key and a sentence saying which one to create -- a blank map
an admin can fix in ten minutes, rather than a rotation and an unknown bill.

These call the real handler with a stubbed secret reader; no app, no database.
"""

import pytest

# Submodule guard, per tests/test_migrate.py.
pytest.importorskip("fastapi.routing")
pytest.importorskip("sqlalchemy")

from app.api import gis


SERVER_KEY = "AIza-SERVER-BILLED-DO-NOT-PUBLISH"
BROWSER_KEY = "AIza-BROWSER-REFERRER-RESTRICTED"
ARCGIS_SERVER = "arcgis-server-secret"
AZURE_SERVER = "azure-server-secret"


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Db:
    """Enough AsyncSession for the handler: one SystemSettings row, or none."""

    def __init__(self, settings=None):
        self._settings = settings

    async def execute(self, _query):
        return _Result(self._settings)


def _secrets(store):
    async def get_secret(key):
        return store.get(key)

    return get_secret


async def _config(monkeypatch, store, provider="google"):
    """Run the real endpoint against a stubbed secret store."""
    store = dict(store)
    store.setdefault("MAP_PROVIDER", provider)
    monkeypatch.setattr(
        "app.services.secret_manager.get_secret", _secrets(store), raising=False
    )
    return await gis.get_maps_config(db=_Db())


def _flatten(value):
    """Every string anywhere in the response, so nothing hides in a nested dict."""
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _flatten(v)]
    return [value] if isinstance(value, str) else []


# ---------------------------------------------------------------------------
# the leak
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_server_google_key_is_never_published(monkeypatch):
    """The exact reproduction: only the server key exists, and it must not ship.

    Checked across the WHOLE response, not just the legacy field, because the
    same secret used to arrive twice -- once as `google_maps_api_key` and once
    inside `map_credentials`.
    """
    config = await _config(monkeypatch, {"GOOGLE_MAPS_API_KEY": SERVER_KEY})
    assert SERVER_KEY not in _flatten(config)
    assert config["google_maps_api_key"] is None
    assert config["has_google_maps"] is False


@pytest.mark.asyncio
async def test_the_server_arcgis_and_azure_keys_are_never_published(monkeypatch):
    """Neither has a browser-safe story, and both were being handed out."""
    esri = await _config(
        monkeypatch, {"ARCGIS_API_KEY": ARCGIS_SERVER}, provider="esri"
    )
    assert ARCGIS_SERVER not in _flatten(esri)

    azure = await _config(
        monkeypatch, {"AZURE_MAPS_KEY": AZURE_SERVER}, provider="azure"
    )
    assert AZURE_SERVER not in _flatten(azure)


@pytest.mark.asyncio
async def test_a_town_with_only_a_server_key_is_told_what_to_create(monkeypatch):
    """Fail safe, and say so. A blank map with no explanation is its own bug."""
    config = await _config(monkeypatch, {"GOOGLE_MAPS_API_KEY": SERVER_KEY})
    assert config["browser_key_needed"] == ["GOOGLE_MAPS_BROWSER_API_KEY"]
    assert "GOOGLE_MAPS_BROWSER_API_KEY" in (config["browser_key_note"] or "")
    # And the existing "you have not finished configuring this" channel agrees.
    assert "apiKey" in config["map_provider_missing"]


# ---------------------------------------------------------------------------
# and the map still works when it is set up correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_browser_key_is_published(monkeypatch):
    """The endpoint has a job; a fix that only ever returns None is not a fix."""
    config = await _config(
        monkeypatch,
        {"GOOGLE_MAPS_API_KEY": SERVER_KEY, "GOOGLE_MAPS_BROWSER_API_KEY": BROWSER_KEY},
    )
    assert config["google_maps_api_key"] == BROWSER_KEY
    assert config["has_google_maps"] is True
    assert config["map_credentials"]["apiKey"] == BROWSER_KEY
    assert config["browser_key_needed"] == []
    assert config["browser_key_note"] is None
    # The server key still must not be anywhere in the payload.
    assert SERVER_KEY not in _flatten(config)


@pytest.mark.asyncio
async def test_a_town_that_wants_one_key_for_both_can_say_so(monkeypatch):
    """Deliberate and recorded, which is the difference from publishing it."""
    config = await _config(
        monkeypatch,
        {"GOOGLE_MAPS_API_KEY": SERVER_KEY, "GOOGLE_MAPS_BROWSER_API_KEY": SERVER_KEY},
    )
    assert config["google_maps_api_key"] == SERVER_KEY


@pytest.mark.asyncio
async def test_nothing_configured_at_all_still_answers(monkeypatch):
    """A town mid-setup gets a usable, honest response rather than a 500."""
    config = await _config(monkeypatch, {})
    assert config["google_maps_api_key"] is None
    assert config["browser_key_needed"] == []  # nothing to migrate; nothing to warn about
    assert config["map_provider"] == "google"


@pytest.mark.asyncio
async def test_only_the_selected_provider_is_warned_about(monkeypatch):
    """A Google town must not be nagged about ArcGIS keys it does not use."""
    config = await _config(
        monkeypatch,
        {"GOOGLE_MAPS_API_KEY": SERVER_KEY, "ARCGIS_API_KEY": ARCGIS_SERVER},
    )
    assert config["browser_key_needed"] == ["GOOGLE_MAPS_BROWSER_API_KEY"]


# ---------------------------------------------------------------------------
# the substitution happens before the lookup, not as a filter afterwards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_endpoint_never_even_asks_for_a_billed_key_by_that_name():
    """A filter is one forgotten field away from leaking again.

    `browser_secret_reader` rewrites the NAME, so there is no path from the
    credential resolution to a server-side secret at all.
    """
    asked = []

    async def get_secret(key):
        asked.append(key)
        return None

    reader = gis.browser_secret_reader(get_secret)
    for server_name in gis.BROWSER_KEY_FOR:
        await reader(server_name)

    assert asked == list(gis.BROWSER_KEY_FOR.values())
    assert not set(asked) & set(gis.BROWSER_KEY_FOR)


def test_every_billed_map_key_has_a_browser_twin():
    """The map catalog and the split must not drift apart.

    A provider gaining a new secret credential field without an entry here
    would publish it, which is how this bug happened the first time.
    """
    from app.services import map_provider as mp

    billed = {
        field["key"]
        for spec in mp.MAP_CATALOG.values()
        for field in spec["credential_fields"]
        if field.get("secret") and not field["key"].endswith("PRIVATE_KEY")
        # A twin is the browser-safe key itself. Requiring it to have a twin of
        # its own would be asking the substitution to point somewhere past its
        # own destination.
        and not field.get("browser_twin")
    }
    assert billed <= set(gis.BROWSER_KEY_FOR), billed - set(gis.BROWSER_KEY_FOR)

    # And the other direction: every substitution must land on a key an admin
    # can actually set. The first version of this split named three browser
    # secrets that existed nowhere else in the product -- not seeded, not a
    # setup field, not in the UI -- so the endpoint withheld the map and left
    # no way to fix it from the console.
    settable = {
        field["key"]
        for spec in mp.MAP_CATALOG.values()
        for field in spec["credential_fields"]
    }
    unsettable = set(gis.BROWSER_KEY_FOR.values()) - settable
    assert not unsettable, (
        f"{sorted(unsettable)} is substituted in but has no credential field, so "
        f"the map stays blank and nobody can enter the key that would fix it")
