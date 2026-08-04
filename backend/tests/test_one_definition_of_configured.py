""""Configured" has to mean one thing across this console.

Two answers were in circulation. The provider cards ask the store of record --
`get_secret`, right now -- through `_configured_map`. Everything without a
provider card, which is backups and crash reporting, read the `is_configured`
column on the secrets table, which records that a value was written once.

Those are different claims and they come apart exactly when it matters. A
secret that has been migrated into the vault keeps `is_configured = True` with
its encrypted database copy scrubbed, so when the vault is unreachable the
column still says yes about a value nothing can read. The cards said "we cannot
tell, so no". The settings with no card had only the column, so a town whose
vault was down saw a tick against backups whose credentials the backup task
could not load.
"""

import pytest

pytest.importorskip("fastapi")

from app.api import system


class _Row:
    def __init__(self, key_name, is_configured=True, key_value=None):
        self.id = 1
        self.key_name = key_name
        self.description = None
        self.is_configured = is_configured
        self.key_value = key_value


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *a, **kw):
        return _Result(self._rows)


def _listing(rows, store):
    import asyncio

    from app.services import secret_manager

    async def get_secret(key):
        value = store.get(key)
        if isinstance(value, Exception):
            raise value
        return value

    original = secret_manager.get_secret
    secret_manager.get_secret = get_secret
    try:
        return asyncio.run(system.list_secrets(db=_Db(rows), _=None))
    finally:
        secret_manager.get_secret = original


def test_a_stored_secret_reads_as_configured():
    out = _listing([_Row("SENTRY_DSN")], {"SENTRY_DSN": "https://x@sentry.io/1"})
    assert out[0].is_configured is True


def test_a_scrubbed_row_the_vault_cannot_serve_does_not_read_as_configured():
    """The exact divergence. The column says yes -- something was written here
    once -- and the value nothing can currently read is what decides."""
    out = _listing([_Row("BACKUP_S3_BUCKET", is_configured=True, key_value=None)],
                   {"BACKUP_S3_BUCKET": None})
    assert out[0].is_configured is False


def test_an_unreachable_store_does_not_claim_configured():
    """Same rule `_configured_map` follows: if we cannot tell, we do not tick
    it. The cost of being wrong this way is asking about something already
    done; the other way it is a green tick on an unreadable credential."""
    out = _listing([_Row("BACKUP_ENCRYPTION_KEY")],
                   {"BACKUP_ENCRYPTION_KEY": RuntimeError("vault unreachable")})
    assert out[0].is_configured is False


def test_whitespace_is_absent_here_too():
    """The definition of empty has to be the same one everywhere, or a value can
    be present for the badge and rejected by the vendor -- which is how a
    leading space in SMTP_USER survived."""
    out = _listing([_Row("SMTP_USER")], {"SMTP_USER": "   "})
    assert out[0].is_configured is False


def test_no_secret_value_is_ever_returned():
    """Four keys were exempted as "config choices, not secrets" and the
    exemption returned the *database* column -- ciphertext while a secret is in
    the database, None once it has been migrated and scrubbed. It returned null
    for every key it existed to expose, and would have leaked an encrypted blob
    if it had not. Nothing read it."""
    out = _listing(
        [_Row("SMS_PROVIDER", key_value="gAAAAAB..."),
         _Row("EMAIL_ENABLED", key_value="gAAAAAB..."),
         _Row("SMTP_PORT", key_value="gAAAAAB...")],
        {"SMS_PROVIDER": "twilio", "EMAIL_ENABLED": "true", "SMTP_PORT": "587"},
    )
    assert all(row.key_value is None for row in out)


def test_the_listing_and_the_cards_use_the_same_reader():
    """Not a style point. Two readers is how the two answers appeared."""
    import inspect

    src = inspect.getsource(system.list_secrets)
    assert "get_secret" in src
    assert "secret.is_configured" not in src, "the column must not decide"


# ---- per-field presence -------------------------------------------------------
#
# The form's "Saved" hint was per provider: once a provider counted as
# configured, every one of its boxes claimed to be saved, including an optional
# one nobody had filled in. The hint exists to say that leaving a box empty
# keeps the stored value rather than clearing it, and that promise is false
# where nothing is stored.

def _stored(providers, store):
    import asyncio

    from app.services import secret_manager

    async def get_secret(key):
        value = store.get(key)
        if isinstance(value, Exception):
            raise value
        return value

    original = secret_manager.get_secret
    secret_manager.get_secret = get_secret
    try:
        return asyncio.run(system._stored_fields(providers))
    finally:
        secret_manager.get_secret = original


def _provider(pid, *keys):
    return {"provider": pid, "credential_fields": [{"key": k, "label": k} for k in keys]}


def test_only_the_boxes_with_something_in_them_are_reported():
    got = _stored([_provider("google", "KEY", "OPTIONAL_ID")], {"KEY": "k"})
    assert got == {"KEY": True, "OPTIONAL_ID": False}


def test_whitespace_is_not_something():
    got = _stored([_provider("p", "KEY")], {"KEY": "  "})
    assert got == {"KEY": False}


def test_a_key_two_providers_share_is_asked_about_once():
    got = _stored([_provider("a", "AWS_REGION"), _provider("b", "AWS_REGION")], {"AWS_REGION": "us-east-1"})
    assert got == {"AWS_REGION": True}


def test_an_unreadable_key_is_reported_absent_rather_than_raising():
    """This decorates a form. It must never take the card down with it."""
    got = _stored([_provider("p", "KEY")], {"KEY": RuntimeError("vault down")})
    assert got == {"KEY": False}


@pytest.mark.asyncio
async def test_every_catalog_endpoint_reports_it():
    """A card whose catalog omits it falls back to hinting nothing, which is
    the safe direction but silently loses the feature."""
    import inspect

    for fn in (system.get_capability_catalog, system.get_ai_catalog,
               system.get_identity_catalog, system.get_translation_catalog,
               system.get_maps_catalog):
        assert "_stored_fields" in inspect.getsource(fn), fn.__name__
