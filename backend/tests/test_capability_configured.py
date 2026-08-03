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


def provider(pid, *fields, **kw):
    return {"provider": pid, "name": pid, "credential_fields": list(fields), **kw}


@pytest.fixture(autouse=True)
def no_attached_identity(monkeypatch):
    """No cloud instance role, unless a test says otherwise.

    `_configured_map` asks whether the host has an identity that supplies some
    of these credentials. Left real, every assertion here would depend on a
    metadata-server probe from wherever the suite happens to run.
    """
    import app.services.cloud_identity as ci
    monkeypatch.setattr(ci, "detect", lambda: None)


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


# ---- credentials collected on another card ------------------------------------

@pytest.mark.asyncio
async def test_a_borrowed_credential_is_required_even_though_no_box_asks_for_it(store):
    got = await _configured_map([provider(
        "google",
        field("TOGGLE", "Blur faces", required=False),
        requires=[{"key": "SA_JSON", "label": "Service account", "where": "the AI card"}],
    )])
    assert got == {"google": False}


@pytest.mark.asyncio
async def test_a_borrowed_credential_that_is_stored_counts(store):
    store.update({"SA_JSON": "{...}"})
    got = await _configured_map([provider(
        "google",
        field("TOGGLE", "Blur faces", required=False),
        requires=[{"key": "SA_JSON", "label": "Service account", "where": "the AI card"}],
    )])
    assert got == {"google": True}


# ---- either/or credential sets ------------------------------------------------
#
# Azure photo redaction needs an AI Face resource for faces and a separate AI
# Vision resource for plates. Having one of the two is a working setup, so
# neither pair can be flagged required and leaving both unflagged is what let an
# Azure card with four empty boxes report itself ready.

@pytest.mark.asyncio
async def test_one_satisfied_group_is_enough(store):
    store.update({"FACE_URL": "https://face", "FACE_KEY": "k"})
    got = await _configured_map([provider(
        "azure",
        field("FACE_URL", "Face endpoint", required=False),
        field("FACE_KEY", "Face key", required=False),
        field("VISION_URL", "Vision endpoint", required=False),
        field("VISION_KEY", "Vision key", required=False),
        requires_any=[["FACE_URL", "FACE_KEY"], ["VISION_URL", "VISION_KEY"]],
    )])
    assert got == {"azure": True}


@pytest.mark.asyncio
async def test_a_half_finished_group_does_not_count(store):
    """An endpoint with no key against it cannot call anything."""
    store.update({"FACE_URL": "https://face"})
    got = await _configured_map([provider(
        "azure",
        field("FACE_URL", "Face endpoint", required=False),
        field("FACE_KEY", "Face key", required=False),
        field("VISION_URL", "Vision endpoint", required=False),
        field("VISION_KEY", "Vision key", required=False),
        requires_any=[["FACE_URL", "FACE_KEY"], ["VISION_URL", "VISION_KEY"]],
    )])
    assert got == {"azure": False}


@pytest.mark.asyncio
async def test_no_group_satisfied_is_not_configured(store):
    got = await _configured_map([provider(
        "azure",
        field("FACE_URL", "Face endpoint", required=False),
        field("FACE_KEY", "Face key", required=False),
        requires_any=[["FACE_URL", "FACE_KEY"]],
    )])
    assert got == {"azure": False}


@pytest.mark.asyncio
async def test_a_group_does_not_excuse_a_flat_required_field(store):
    """Both rules apply. The AWS card carries a required region *and* could
    carry alternatives; satisfying one must not waive the other."""
    store.update({"FACE_URL": "https://face", "FACE_KEY": "k"})
    got = await _configured_map([provider(
        "azure",
        field("REGION", "Region", required=True),
        field("FACE_URL", "Face endpoint", required=False),
        field("FACE_KEY", "Face key", required=False),
        requires_any=[["FACE_URL", "FACE_KEY"]],
    )])
    assert got == {"azure": False}


# ---- credentials an attached cloud identity supplies --------------------------

@pytest.mark.asyncio
async def test_an_attached_identity_satisfies_the_key_it_replaces(store, monkeypatch):
    """The credential form already draws these boxes as "nothing to enter". The
    badge used to disagree with the box directly above it -- form says there is
    nothing to supply, badge says not set up because it was not supplied."""
    import app.services.cloud_identity as ci
    monkeypatch.setattr(ci, "detect", lambda: {"provider": "google", "identity": "sa@example"})

    store.update({"GOOGLE_CLOUD_PROJECT": "p"})
    got = await _configured_map([provider(
        "google",
        field("GOOGLE_CLOUD_PROJECT", "Project", required=True),
        field("GCP_SERVICE_ACCOUNT_JSON", "Service account JSON", required=True),
    )])
    assert got == {"google": True}


@pytest.mark.asyncio
async def test_an_attached_identity_does_not_supply_which_resource_to_use(store, monkeypatch):
    """An instance role proves who is asking. It does not name a project, a
    region or a key, so those still have to be entered."""
    import app.services.cloud_identity as ci
    monkeypatch.setattr(ci, "detect", lambda: {"provider": "google", "identity": "sa@example"})

    got = await _configured_map([provider(
        "google",
        field("GOOGLE_CLOUD_PROJECT", "Project", required=True),
        field("GCP_SERVICE_ACCOUNT_JSON", "Service account JSON", required=True),
    )])
    assert got == {"google": False}


@pytest.mark.asyncio
async def test_a_failing_identity_probe_is_treated_as_no_identity(store, monkeypatch):
    """A metadata probe that throws must not decide anything. It must certainly
    not throw out of the catalog endpoint."""
    import app.services.cloud_identity as ci

    def boom():
        raise RuntimeError("no metadata server here")

    monkeypatch.setattr(ci, "detect", boom)
    store.update({"A": "x"})
    assert await _configured_map([provider("p", field("A", "A"))]) == {"p": True}


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


@pytest.mark.asyncio
async def test_a_cloud_detector_needs_a_cloud_account(store):
    """The bug this pass fixes, in the catalog it happened in.

    Every photo-redaction provider declared the two blur toggles and nothing
    else, both toggles are optional, and a provider with no required fields
    counts as configured -- so a deployment with no AWS and no Azure account
    read `{'google': True, 'aws': True, 'azure': True, 'local': True}`. The
    Azure card said "configured" while `resolve_provider` found no Azure
    credentials and quietly ran OpenCV instead.

    Only the on-server detector may claim to be ready with nothing stored,
    because it is the only one that genuinely needs nothing.
    """
    from app.services.delivery_providers import catalog_for_api

    got = await _configured_map(catalog_for_api("redaction"))
    assert got == {"google": False, "aws": False, "azure": False, "local": True}


@pytest.mark.asyncio
async def test_a_cloud_key_service_needs_a_cloud_account(store):
    """Same shape on the KMS card. Its three fields only *name* a key and all
    three have defaults, so Google Cloud KMS reported itself configured on a
    town with no Google account -- while `_wrap_dek` fell through to wrapping
    resident PII with the application's own SECRET_KEY."""
    from app.services.delivery_providers import catalog_for_api

    got = await _configured_map(catalog_for_api("kms"))
    assert got["google"] is False
    assert got["local"] is True


# ---- what Save tells you is still missing -------------------------------------

class _NoBackground:
    def add_task(self, *a, **kw):
        pass


async def _save(capability, provider, store, monkeypatch, settings=None):
    from app.api import system

    async def fake_persist(db, key_name, value):
        store[key_name] = value
        return True

    monkeypatch.setattr(system, "_persist_secret", fake_persist)
    body = system.ProviderSaveRequest(provider=provider, settings=settings or {})
    return await system.save_provider(capability, body, _NoBackground(), db=None, _=None)


@pytest.mark.asyncio
async def test_saving_a_detector_with_no_cloud_account_does_not_claim_it_is_ready(store, monkeypatch):
    """Selecting Amazon Rekognition on a town with no AWS account used to
    answer configured: true, because the card collected only the blur
    toggles."""
    out = await _save("redaction", "aws", store, monkeypatch)
    assert out["configured"] is False
    assert out["missing"] == ["AWS Region (on any AWS card — email, text messages or encryption)"]


@pytest.mark.asyncio
async def test_the_missing_credential_says_which_card_to_enter_it_on(store, monkeypatch):
    """There is no box for it here, so the name alone is a dead end."""
    out = await _save("redaction", "google", store, monkeypatch)
    assert out["missing"] == ["Google service account (on the AI card)"]


@pytest.mark.asyncio
async def test_alternatives_are_reported_as_a_choice_not_as_four_empty_boxes(store, monkeypatch):
    out = await _save("redaction", "azure", store, monkeypatch)
    assert out["configured"] is False
    assert out["missing"] == [
        "either Face endpoint + Face key, or Vision endpoint + Vision key"
    ]


@pytest.mark.asyncio
async def test_one_azure_pair_is_enough_to_be_configured(store, monkeypatch):
    store.update({"AZURE_VISION_ENDPOINT": "https://v", "AZURE_VISION_KEY": "k"})
    out = await _save("redaction", "azure", store, monkeypatch)
    assert out["configured"] is True
    assert out["missing"] == []


@pytest.mark.asyncio
async def test_on_server_detection_is_ready_with_nothing_entered(store, monkeypatch):
    """It is the fallback everything degrades to. If it ever reported itself
    unconfigured there would be no configured detector at all."""
    out = await _save("redaction", "local", store, monkeypatch)
    assert out["configured"] is True
    assert out["missing"] == []


@pytest.mark.asyncio
async def test_the_save_endpoint_still_refuses_a_key_the_provider_does_not_declare(store, monkeypatch):
    """`requires` names credentials collected elsewhere. It must not become a
    second allow-list for writing them through this endpoint."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await _save("redaction", "google", store, monkeypatch,
                    settings={"VERTEX_AI_SERVICE_ACCOUNT_KEY": "{}"})
    assert exc.value.status_code == 400
    assert "VERTEX_AI_SERVICE_ACCOUNT_KEY" in exc.value.detail


@pytest.mark.asyncio
async def test_the_save_endpoint_still_accepts_the_keys_it_declares(store, monkeypatch):
    out = await _save("redaction", "local", store, monkeypatch,
                      settings={"REDACT_FACES": "true", "REDACT_PLATES": "false"})
    assert out["ok"] is True
    assert store["REDACT_FACES"] == "true"
    assert store["REDACTION_PROVIDER"] == "local"


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
    """If a new check is added, the allow-list must admit it, or the capability
    becomes unreachable behind a 400.

    This used to scrape `if capability == "` lines out of test_provider's
    source. That broke the day the endpoint was refactored into a dispatch
    table -- the property it cared about got *stronger*, and the test failed
    anyway, because it was asserting the shape of the code rather than the
    thing the code has to be true about. Reads the table now.
    """
    from app.api import system

    handled = set(system._CAPABILITY_TESTS)
    assert handled, "expected to find the per-capability checks"
    assert handled <= set(system._PROVIDER_SELECT_KEY), handled - set(system._PROVIDER_SELECT_KEY)
