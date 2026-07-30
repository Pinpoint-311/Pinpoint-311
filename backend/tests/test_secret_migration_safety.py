"""Secrets the migration must never scrub out of the database.

`migrate_to_secret_manager` writes every configured secret to Secret Manager,
verifies it reads back, and then clears the encrypted database copy. That is the
right shape -- except that it excluded only the two Google bootstrap keys, and
two other groups cannot survive it.

Circularity. `AZURE_KEYVAULT_CLIENT_SECRET`, `AWS_ACCESS_KEY_ID` and the rest
are the credentials *for* the secret store. Moving them into the store they
unlock leaves nothing able to open it. Google's pair was already excluded for
exactly this reason; the other two clouds' equivalents were not.

Reader mismatch, which is the worse one. KMS configuration is read by
`encryption._get_config_sync` and `aws_kms._cfg` -- both look at the environment,
then the database, and never consult Secret Manager. So migrating `KMS_KEY_ID`
succeeded, verified against GCP, and then scrubbed the only copy anything could
actually read. `pii_crypto` would fall back to wrapping the data key with the
application SECRET_KEY: no exception, nothing logged above DEBUG, and no
indication on the page that the KMS a town had selected was no longer in use.

This was reachable only by hand until photo redaction and PII encryption got
cards, which is what makes it worth a test rather than a comment.
"""

import re

import pytest

from app.services.secret_manager import DB_REQUIRED_KEYS

SYNC_READER_SOURCES = (
    "app/core/encryption.py",
    "app/core/aws_kms.py",
    "app/core/azure_keyvault.py",
    "app/core/aws_secretsmanager.py",
)


def _keys_read_synchronously():
    """Every key fetched through a reader that cannot see Secret Manager."""
    keys = set()
    for path in SYNC_READER_SOURCES:
        try:
            source = open(path).read()
        except OSError:
            continue
        keys |= set(re.findall(r'(?:_get_config_sync|_cfg)\("([A-Z0-9_]+)"\)', source))
    return keys


def test_every_synchronously_read_key_keeps_its_database_copy():
    """The migration cannot move a key whose only reader looks in the database.

    Written against the readers rather than a hand-listed set, so adding a
    `_cfg("NEW_KEY")` to the KMS code fails here instead of silently becoming
    scrubbable.
    """
    sync_keys = _keys_read_synchronously()
    assert sync_keys, "expected to find synchronously-read config keys"
    unprotected = sync_keys - DB_REQUIRED_KEYS
    assert not unprotected, (
        "these are read only from env/database but would be scrubbed after "
        f"migration: {sorted(unprotected)}"
    )


def test_the_secret_stores_own_credentials_are_protected():
    """Storing the key to the safe inside the safe."""
    for key in (
        "GCP_SERVICE_ACCOUNT_JSON", "GOOGLE_CLOUD_PROJECT",
        "AZURE_KEYVAULT_URL", "AZURE_KEYVAULT_CLIENT_SECRET", "AZURE_TENANT_ID",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    ):
        assert key in DB_REQUIRED_KEYS, key


def test_the_kms_selection_and_key_path_are_protected():
    """Losing these does not fail loudly -- it downgrades PII encryption to the
    application key without saying so."""
    for key in ("KMS_PROVIDER", "KMS_LOCATION", "KMS_KEY_RING", "KMS_KEY_ID", "AWS_KMS_KEY_ID"):
        assert key in DB_REQUIRED_KEYS, key


def test_ordinary_provider_secrets_are_still_migrated():
    """The point of the migration survives: things with an async reader move."""
    for key in (
        "AUTH0_CLIENT_SECRET", "TWILIO_AUTH_TOKEN", "SMTP_PASSWORD",
        "GOOGLE_MAPS_API_KEY", "ACS_ACCESS_KEY",
    ):
        assert key not in DB_REQUIRED_KEYS, key


def test_the_migration_consults_the_set_in_both_places():
    """It has to skip the write *and* the scrub. Skipping only the write would
    still leave the scrub loop clearing a key it had not migrated."""
    pytest.importorskip("sqlalchemy")
    import inspect

    from app.services import secret_manager

    src = inspect.getsource(secret_manager.migrate_to_secret_manager)
    assert "bootstrap_keys = set(DB_REQUIRED_KEYS)" in src
    assert "not in DB_REQUIRED_KEYS" in src, "the scrub loop must check it too"
