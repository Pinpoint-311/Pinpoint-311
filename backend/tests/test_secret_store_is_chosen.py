"""No credential is written before somebody says where credentials go.

The reason is backups, not tidiness.

`_persist_secret` falls back to the encrypted database when the external store
is unreachable, and reports that it did. `vault_secrets` later sweeps those rows
into the store and scrubs the database copy -- on a schedule, and again after
every provider save -- so the live database heals itself and the whole thing
looks harmless.

Database backups taken inside that window do not heal. They keep the row
forever and they go off-site: a pg_dump of a Pinpoint instance contains
`COPY public.system_secrets (id, key_name, key_value, ...)`. Sweeping the live
row reaches nothing already dumped. So the credential has to not be written
until the destination has been decided.

The gate is on the choice, not on having a cloud vault. The encrypted database
is one of the answers -- test_secret_store_ordering has said it is a supported
store for a while -- with the backup consequence spelled out on screen. What
must not happen is a town landing there by accident, which an unset
`SECRETS_PROVIDER` quietly defaulting to "google" used to arrange.
"""

import asyncio

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException

from app.api import system
from app.services import secret_manager as sm


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def unset(monkeypatch):
    """A town that has not been asked."""
    monkeypatch.setattr(sm, "_secrets_provider", lambda: "")


@pytest.fixture
def chose(monkeypatch):
    def _choose(store):
        monkeypatch.setattr(sm, "_secrets_provider", lambda: store)
    return _choose


# ---------------------------------------------------------------------------
# Unset means unset
# ---------------------------------------------------------------------------

def test_an_unanswered_town_reports_no_store(monkeypatch):
    """It used to report "google", so nothing -- not the page, not the code --
    could tell a deliberate choice of Google Secret Manager from silence."""
    monkeypatch.delenv("SECRETS_PROVIDER", raising=False)
    monkeypatch.setattr("app.core.encryption._get_config_sync", lambda _k: None)

    assert sm._secrets_provider() == ""
    assert sm.store_chosen() is False


def test_the_encrypted_database_is_one_of_the_answers():
    """Not a fallback a town discovers it landed in. A named choice it can make,
    which is what stops the gate from dead-ending a town whose cloud
    procurement is unfinished."""
    assert "database" in sm.SECRET_STORES
    assert sm.SECRET_STORES == ("google", "azure", "aws", "database")


@pytest.mark.parametrize("store", ["google", "azure", "aws", "database"])
def test_every_named_store_counts_as_chosen(chose, store):
    chose(store)
    assert sm.store_chosen() is True


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def test_a_credential_is_refused_until_a_store_is_chosen(unset):
    with pytest.raises(HTTPException) as caught:
        system._require_a_secret_store()

    assert caught.value.status_code == 409
    # The refusal has to say what to do about it, and that the database is an
    # allowed answer -- otherwise it reads as "go and buy a cloud vault".
    assert "encrypted database is one of the answers" in caught.value.detail


def test_choosing_the_encrypted_database_lets_credentials_through(chose):
    """Accepted, and recorded as a deliberate choice. The gate is about consent,
    not capability."""
    chose("database")
    system._require_a_secret_store()  # does not raise


def test_a_vault_that_is_not_reachable_yet_still_opens_the_gate(chose, monkeypatch):
    """Choosing Azure before the Key Vault credentials arrive is a real state --
    and those credentials are entered on this same page, so gating on
    reachability would be a loop with no way in."""
    chose("azure")
    monkeypatch.setattr("app.core.azure_keyvault.is_configured", lambda: False)
    system._require_a_secret_store()  # does not raise


def test_both_doors_into_the_secret_table_are_gated():
    """The provider cards and the plain credential fields write through
    different endpoints. Gating one would leave backups, crash reporting and the
    Google account key going into an unchosen store."""
    import inspect

    for endpoint in (system.save_provider, system.create_or_update_secret):
        assert "_require_a_secret_store()" in inspect.getsource(endpoint), endpoint.__name__


# The three ways a credential reaches storage. `create_or_update_secret` uses
# none of `_persist_secret`'s helpers -- it encrypts and adds the row itself --
# which is why matching on one name would miss half the doors.
_WRITE_SIGNALS = ("_persist_secret(", "set_secret(", "SystemSecret(")


def _source_of(fn) -> str:
    import inspect

    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return ""


def _writes_to_secret_storage(src: str) -> bool:
    return any(signal in src for signal in _WRITE_SIGNALS)


# Handlers the scan finds that are deliberately not gated, and why.
#
# Each one either answers the question the gate asks -- gating those would leave
# no way through it -- or does not carry a credential at all.
_UNGATED_BY_DESIGN = {
    # The gate's own door. POST /providers/secret-store is where the choice is
    # recorded, so it cannot require the choice.
    "choose_secret_store",
    # Writes the PROVIDER selections for a cloud profile, `SECRETS_PROVIDER`
    # among them. Selections are vendor names, not credentials -- no secret is in
    # the body -- and this is the second way a town says which store it wants.
    "set_cloud_profile",
    # Seeds the placeholder rows from DEFAULT_SECRETS: key_name, description,
    # is_configured=False. It never sets `key_value`, so there is no credential
    # here to put in the wrong place.
    "sync_secrets",
}


def test_no_new_door_into_the_secret_table_opens_ungated():
    """Discovered rather than listed.

    The test above names its two endpoints. That was true when it was written and
    it is exactly the assertion that rots: a third credential-writing endpoint
    added next year passes it without ever being looked at. So this one finds
    every handler that writes to secret storage by any of the three routes, and
    requires each to pass the gate or be named above with a reason.

    Finding `sync_secrets` -- which the hand-written pair never mentioned -- is
    the argument for doing it this way.
    """
    import inspect

    offenders = []
    for name, fn in vars(system).items():
        if not inspect.isfunction(fn) or name.startswith("_"):
            continue
        src = _source_of(fn)
        if not _writes_to_secret_storage(src) or name in _UNGATED_BY_DESIGN:
            continue
        if "_require_a_secret_store()" not in src:
            offenders.append(name)

    assert not offenders, (
        f"these reach secret storage without asking where credentials go: "
        f"{sorted(offenders)}. Either call _require_a_secret_store(), or -- if "
        f"the endpoint records the choice itself or carries no credential -- add "
        f"it to _UNGATED_BY_DESIGN with the reason."
    )


def test_the_discovery_actually_discovers_something():
    """A scan whose signals have been renamed matches nothing and passes forever.
    This pins that both known doors are still found, so `_persist_secret` or
    `set_secret` being renamed fails loudly instead of quietly covering nothing.
    """
    import inspect

    found = {
        name
        for name, fn in vars(system).items()
        if inspect.isfunction(fn)
        and not name.startswith("_")
        and _writes_to_secret_storage(_source_of(fn))
    }
    assert {"save_provider", "create_or_update_secret"} <= found
    assert _UNGATED_BY_DESIGN <= found, (
        "an entry in the allowlist that the scan no longer finds is dead, and "
        "dead entries are how a real door gets excused later by accident"
    )


def test_recording_the_choice_is_not_itself_gated():
    """Otherwise nothing could ever get through it."""
    assert "SECRETS_PROVIDER" in system._STORE_CHOICE_KEYS

    import inspect

    src = inspect.getsource(system.create_or_update_secret)
    assert "if secret_data.key_name not in _STORE_CHOICE_KEYS" in src


def test_the_choice_is_never_written_into_the_store_it_names():
    """Circular, and it is how a town whose store became unreadable would lose
    the only record of which store that was. It used to go through the ordinary
    path and rely on DB_REQUIRED_KEYS to keep the database copy -- which worked,
    and still wrote the name of the store into the store."""
    import inspect

    src = inspect.getsource(system._persist_secret)
    assert "| _STORE_CHOICE_KEYS" in src
    # And the scrubber still has to leave it alone.
    assert "SECRETS_PROVIDER" in sm.DB_REQUIRED_KEYS


# ---------------------------------------------------------------------------
# What "database" does once chosen
# ---------------------------------------------------------------------------

def test_choosing_the_database_stops_reads_going_to_a_cloud_store(chose, monkeypatch):
    """A town that picked the database may still have Google Cloud credentials
    on file for AI or maps. Falling through to `_is_gcp_available()` would
    quietly start reading its keys out of Secret Manager -- a different store
    from the one it chose, whose contents nobody put there."""
    chose("database")
    monkeypatch.setattr(sm, "_is_gcp_available", lambda: pytest.fail("read the cloud store"))

    async def from_db(key):
        return "value-from-postgres"

    monkeypatch.setattr(sm, "_get_secret_from_db", from_db)
    assert _run(sm.get_secret("SMTP_PASSWORD")) == "value-from-postgres"


def test_choosing_the_database_stops_writes_going_to_a_cloud_store(chose, monkeypatch):
    chose("database")
    monkeypatch.setattr(sm, "_is_gcp_available", lambda: pytest.fail("wrote to the cloud store"))

    # False means "this is in the database", which is where the town asked for
    # it -- the caller's `db_only` reporting is already built on that.
    assert sm.set_secret_sync("SMTP_PASSWORD", "x") is False


def test_nothing_is_swept_out_of_the_database_that_was_meant_to_stay(chose):
    """`store_reachable` gates the migration. With the database chosen there is
    nothing to move and nothing to scrub, and with no store chosen there is
    nowhere anybody asked for it to go."""
    from app.services.storage_maintenance import store_reachable

    chose("database")
    assert store_reachable() is False
    chose("")
    assert store_reachable() is False


def test_the_card_says_no_store_rather_than_guessing_one(chose):
    """`effective_provider_for('secrets')` answered "database" for an unanswered
    town, which ticks the box the gate exists to hold open. Nothing chosen is
    None."""
    chose("")
    assert _run(system.effective_provider_for("secrets")) is None
    chose("database")
    assert _run(system.effective_provider_for("secrets")) == "database"


# ---------------------------------------------------------------------------
# Changing it
# ---------------------------------------------------------------------------

def test_the_store_cannot_be_repointed_once_it_holds_something(chose, monkeypatch):
    """Same reasoning that makes the secret store card read-only. Every
    credential the town has is in the current store, and changing this setting
    does not move them -- it would be one click that makes every other card
    unreadable."""
    chose("google")
    monkeypatch.delenv("SECRETS_PROVIDER", raising=False)

    with pytest.raises(HTTPException) as caught:
        _run(system.choose_secret_store(system.SecretStoreChoice(store="aws"), db=None, admin=None))

    assert caught.value.status_code == 409
    assert "does not move them" in caught.value.detail


def test_an_unknown_store_is_refused(unset):
    with pytest.raises(HTTPException) as caught:
        _run(system.choose_secret_store(
            system.SecretStoreChoice(store="dropbox"), db=None, admin=None))

    assert caught.value.status_code == 400


def test_a_host_pinned_store_is_not_editable_from_the_console(monkeypatch):
    """`SECRETS_PROVIDER` in the environment wins over the database, so
    accepting a write here would store an answer the reader goes on ignoring --
    the shape of every bug in this area."""
    monkeypatch.setenv("SECRETS_PROVIDER", "aws")

    with pytest.raises(HTTPException) as caught:
        _run(system.choose_secret_store(
            system.SecretStoreChoice(store="aws"), db=None, admin=None))

    assert caught.value.status_code == 409
    assert "pinned" in caught.value.detail


# ---------------------------------------------------------------------------
# The card beside the gate has to agree with it
# ---------------------------------------------------------------------------

def test_the_card_does_not_name_a_store_the_town_never_chose(unset, monkeypatch):
    """Two answers to one question, and the confident one was wrong.

    `normalize_provider` falls back to that capability's entry in `_DEFAULTS`,
    which for secrets is "google". So the provider card drew Google Secret
    Manager as the selected store on a town that had chosen nothing -- beside a
    gate asking where credentials should go, and above fields that answered every
    save with 409. Whichever the clerk believed, the page had told them the other.
    """
    from app.services import connector_health

    async def no_health(db):
        return {}

    async def nothing_configured(providers):
        return {}

    async def no_fields(providers):
        return {}

    async def no_secret(key):
        return None

    monkeypatch.setattr(connector_health, "snapshot", no_health)
    monkeypatch.setattr(system, "_configured_map", nothing_configured)
    monkeypatch.setattr(system, "_stored_fields", no_fields)
    monkeypatch.setattr("app.services.secret_manager.get_secret", no_secret)

    out = _run(system.get_capability_catalog("secrets", db=None, _=None))

    assert out["current_provider"] is None, (
        "nothing has been chosen, so the card must show nothing selected"
    )
    assert out["default_provider"] is None, (
        "a default here is the accidental-Google the gate exists to remove"
    )


def test_the_other_capabilities_keep_their_default(unset, monkeypatch):
    """The fix is scoped to the secret store. Email and the rest genuinely do
    have a sensible default, and blanking those would leave their cards with no
    selection at all."""
    from app.services import connector_health

    async def no_health(db):
        return {}

    async def nothing_configured(providers):
        return {}

    async def no_fields(providers):
        return {}

    async def no_secret(key):
        return None

    monkeypatch.setattr(connector_health, "snapshot", no_health)
    monkeypatch.setattr(system, "_configured_map", nothing_configured)
    monkeypatch.setattr(system, "_stored_fields", no_fields)
    monkeypatch.setattr("app.services.secret_manager.get_secret", no_secret)

    out = _run(system.get_capability_catalog("email", db=None, _=None))

    assert out["default_provider"] is not None
    assert out["current_provider"] is not None
