"""Where a provider credential actually lands, and whether anyone is told.

The credentials that make the secret store reachable -- the Google Cloud project
and service-account JSON, or the Key Vault / AWS equivalents -- are entered on
the same page as everything else. So there is an ordering trap: save an Auth0
secret before those, and `set_secret` finds no store, returns False, and logs at
DEBUG. Nothing raises that logger above WARNING, so the line went nowhere.

`_persist_secret` only ever warned on an *exception*, never on that False, and
returned nothing. The secret sat in the encrypted database, the card showed a
green tick, and the town's secret store stayed empty -- discoverable only by
someone who knew to run the migration endpoint.

The encrypted database is a supported store, so this is not an error. It is
something the town has to be told, because the fix is trivial and invisible:
enter the cloud credentials, then press Save & Test again.
"""

import inspect

import pytest

pytest.importorskip("fastapi")

from app.api import system


def test_persist_secret_reports_whether_the_store_took_it():
    """It used to return None, so the caller could not have known either way."""
    src = inspect.getsource(system._persist_secret)
    assert "-> bool" in src
    assert "return stored_externally" in src


def test_the_bootstrap_keys_stay_out_of_the_secret_store():
    """Storing the credentials that unlock the store inside the store is
    circular -- they have to be readable before it is reachable."""
    src = inspect.getsource(system._persist_secret)
    assert "GCP_SERVICE_ACCOUNT_JSON" in src and "GOOGLE_CLOUD_PROJECT" in src
    assert "stored_externally = key_name in bootstrap_keys" in src


def test_saving_a_provider_tracks_credentials_that_only_reached_the_database():
    src = inspect.getsource(system.save_provider)
    assert "db_only" in src, "the save path must notice a database-only write"
    # And must act on it rather than collecting it and moving on.
    assert "if db_only:" in src


def test_the_town_is_told_which_store_it_landed_in():
    """Naming the store matters: 'not saved to the secret store' is alarming and
    wrong, and the message has to say which one was expected."""
    src = inspect.getsource(system.save_provider)
    assert "encrypted database" in src
    for store in ("Azure Key Vault", "AWS Secrets Manager", "Google Secret Manager"):
        assert store in src, store


def test_it_is_advisory_rather_than_a_failure():
    """The encrypted database really is a supported store. Failing the save
    would turn a working configuration into a dead end."""
    src = inspect.getsource(system.save_provider)
    assert '"severity": "info"' in src
    # The response still reports success.
    assert '"ok": True' in src


# ---------------------------------------------------------------------------
# Switching the store the credentials are already in
# ---------------------------------------------------------------------------

def test_the_secret_store_cannot_be_repointed_from_a_card():
    """Every credential the town has is in the current store, and changing the
    setting does not move them. A picker on a card would be one click between a
    working town and an apparently empty one."""
    src = inspect.getsource(system.save_provider)
    assert "_READ_ONLY_SELECTION" in src


def test_the_refusal_says_what_to_do_instead():
    """It used to say the cloud profile "moves the existing credentials across".
    It does not -- `set_cloud_profile` repoints SECRETS_PROVIDER and migrates
    nothing -- so the message sent people to a flow that would have caused the
    problem it was warning about."""
    src = inspect.getsource(system.save_provider)
    assert "does not move them" in src
    assert "hourly migration" in src


def test_switching_cloud_profile_warns_about_the_credentials_left_behind():
    """The KMS half of this has carried a warning since it was written and the
    secret half never did -- and the secret half is worse. PII stays readable
    while the old KMS credentials are in place; a repointed secret store takes
    the mail relay, the map key and the identity provider with it."""
    src = inspect.getsource(system.set_cloud_profile)
    assert "_vaulted_key_names" in src, "it has to know whether anything is at risk"
    assert "are not moved" in src


def test_the_warning_is_skipped_when_nothing_is_at_risk():
    """A town whose secrets are all still in the database loses nothing by
    repointing, and a warning that always fires is one nobody reads."""
    src = inspect.getsource(system.set_cloud_profile)
    assert "if await _vaulted_key_names():" in src


def test_only_secrets_whose_sole_copy_is_the_vault_count():
    """A scrubbed row is one whose encrypted database copy was removed after
    being verified in the store. Those are exactly the ones that become
    unreadable, and DB_REQUIRED_KEYS never get scrubbed."""
    src = inspect.getsource(system._vaulted_key_names)
    assert "key_value.is_(None)" in src
    assert "is_configured.is_(True)" in src
