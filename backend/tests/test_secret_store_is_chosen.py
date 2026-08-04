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
