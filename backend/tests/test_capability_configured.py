"""Tests for "is this provider set up".

The badge this drives had been lying. Three of the four capability catalogs --
identity, translation and maps -- returned no `configured` map at all, so the
admin UI read undefined for every one of them and rendered "Not configured" on
connectors that were saved and working.

That direction matters. A false negative on a working connector is worse than no
badge: it sends a clerk off to re-paste credentials that were already correct,
and it makes the setup checklist permanently incomplete.
"""

import pytest

pytest.importorskip("fastapi")  # system.py pulls in the whole API stack

from app.api.system import _configured_map, _field_required


def field(key, label, **kw):
    return {"key": key, "label": label, "secret": True, **kw}


def provider(pid, *fields):
    return {"provider": pid, "name": pid, "credential_fields": list(fields)}


@pytest.fixture
def store(monkeypatch):
    """Swap the secret store for a dict."""
    secrets = {}

    async def get_secret(key):
        return secrets.get(key)

    import app.services.secret_manager as sm
    monkeypatch.setattr(sm, "get_secret", get_secret)
    return secrets


# ---- which fields count ------------------------------------------------------

def test_an_explicit_required_flag_wins():
    assert _field_required(field("K", "Key", required=True))
    assert not _field_required(field("K", "Key", required=False))


def test_a_label_ending_in_optional_is_optional():
    """The older catalogs encode optionality only in the label."""
    assert not _field_required(field("K", "Map ID (optional)"))
    assert not _field_required(field("K", "Authority host (optional)  "))
    assert _field_required(field("K", "Client Secret"))


def test_the_flag_beats_the_label_when_they_disagree():
    """A field labelled "(optional)" but flagged required is required. The flag
    is the deliberate statement; the label is prose."""
    assert _field_required(field("K", "Thing (optional)", required=True))


def test_a_label_merely_containing_the_word_optional_is_still_required():
    assert _field_required(field("K", "Optional feature toggle"))


# ---- the map ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_required_present_is_configured(store):
    store.update({"A": "x", "B": "y"})
    got = await _configured_map([provider("p", field("A", "A"), field("B", "B"))])
    assert got == {"p": True}


@pytest.mark.asyncio
async def test_one_missing_required_is_not_configured(store):
    store.update({"A": "x"})
    got = await _configured_map([provider("p", field("A", "A"), field("B", "B"))])
    assert got == {"p": False}


@pytest.mark.asyncio
async def test_a_missing_optional_does_not_block(store):
    """The regression that started this: Apple, Esri and Google all carry
    optional fields, and requiring them marked working setups as broken."""
    store.update({"A": "x"})
    got = await _configured_map([
        provider("p", field("A", "A"), field("B", "B (optional)"), field("C", "C", required=False)),
    ])
    assert got == {"p": True}


@pytest.mark.asyncio
async def test_an_empty_string_secret_is_not_present(store):
    """A cleared credential is stored as "" rather than removed."""
    store.update({"A": ""})
    assert await _configured_map([provider("p", field("A", "A"))]) == {"p": False}


@pytest.mark.asyncio
async def test_a_provider_needing_nothing_is_configured(store):
    """Nothing to supply means nothing missing -- a provider using ambient cloud
    credentials must not read as unconfigured forever."""
    assert await _configured_map([provider("p")]) == {"p": True}


@pytest.mark.asyncio
async def test_every_provider_gets_an_answer(store):
    """The UI indexes this by provider id. A missing key is undefined on the
    client, which renders as "not configured" -- the exact false negative."""
    store.update({"A": "x"})
    got = await _configured_map([
        provider("one", field("A", "A")),
        provider("two", field("B", "B")),
        provider("three"),
    ])
    assert set(got) == {"one", "two", "three"}


@pytest.mark.asyncio
async def test_an_unreachable_secret_store_does_not_claim_configured(monkeypatch):
    """If the vault is down we do not know. Claiming "configured" would hide a
    real outage behind a green badge."""
    async def boom(key):
        raise RuntimeError("vault unreachable")

    import app.services.secret_manager as sm
    monkeypatch.setattr(sm, "get_secret", boom)
    assert await _configured_map([provider("p", field("A", "A"))]) == {"p": False}


# ---- the real catalogs --------------------------------------------------------

@pytest.mark.asyncio
async def test_every_shipped_capability_reports_every_provider(store):
    """A regression guard on the actual catalogs, so a new provider added
    without a required-field review cannot silently become unbadgeable."""
    from app.services.identity import catalog_for_api as identity
    from app.services.map_provider import catalog_for_api as maps
    from app.services.translation_providers import catalog_for_api as translation

    for name, catalog in (("identity", identity()), ("maps", maps()), ("translation", translation())):
        providers = catalog
        got = await _configured_map(providers)
        assert set(got) == {p["provider"] for p in providers}, name
        # Nothing is stored, so nothing requiring a credential may claim to be set up.
        for p in providers:
            if any(_field_required(f) for f in p["credential_fields"]):
                assert got[p["provider"]] is False, f"{name}/{p['provider']}"


# ---- the test endpoint's allow-list -------------------------------------------
#
# `POST /providers/{capability}/test` took the path segment unvalidated and
# handed it to connector_health, whose _row() creates a row for whatever name it
# is given. So any admin request could insert arbitrary rows into the table the
# setup page renders, named from the URL. save_provider had always validated;
# test_provider had not.

def test_the_test_endpoint_validates_capability_before_using_it():
    import inspect

    from app.api import system

    src = inspect.getsource(system.test_provider)
    guard = src.index("capability not in _PROVIDER_SELECT_KEY")
    # Before the first thing that would persist a row under that name.
    assert guard < src.index("_remember"), "validation must precede any recording"


def test_the_rejection_does_not_echo_the_path_segment():
    """The 400 body used to interpolate the raw segment straight back."""
    import inspect

    from app.api import system

    src = inspect.getsource(system.test_provider)
    assert 'detail=f"Test not supported for: {capability}"' not in src
    assert 'f"Unknown capability. Expected one of:' in src


def test_the_allow_list_covers_every_capability_the_endpoint_handles():
    """If a new branch is added to test_provider, the allow-list must admit it,
    or the capability becomes unreachable behind a 400."""
    import inspect

    from app.api import system

    src = inspect.getsource(system.test_provider)
    handled = {line.split('"')[1] for line in src.splitlines()
               if line.strip().startswith('if capability == "')}
    assert handled, "expected to find the per-capability branches"
    assert handled <= set(system._PROVIDER_SELECT_KEY), handled - set(system._PROVIDER_SELECT_KEY)
