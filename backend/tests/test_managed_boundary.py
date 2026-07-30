"""What the state owns, and what the town owns, on a hosted deployment.

Managed mode is the answer to "can a town do no setup at all" -- a state agency
runs the infrastructure and the town gets an instance. That only holds if the
boundary is real: the town's admin has full rights over their own instance, so
the guard on platform keys is the only thing standing between them and the
state's encryption.

It was hand-listed, and Google-shaped as a result. It named the GCP project,
service account and KMS key path, and of Azure only the vault URL. Every AWS
infrastructure key was missing, as were Azure's credentials and both provider
selectors -- so on a state-hosted deployment running on AWS or Azure, a town
admin could overwrite AWS_KMS_KEY_ID, KMS_PROVIDER or SECRETS_PROVIDER and
repoint the state's encryption at a key of their own.

Derived from DB_REQUIRED_KEYS now rather than listed, so it cannot drift again.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from app.core.managed import PLATFORM_MANAGED_KEYS, is_platform_managed
from app.services.secret_manager import DB_REQUIRED_KEYS


def test_every_storage_key_belongs_to_the_platform():
    """DB_REQUIRED_KEYS is the authoritative set of "credentials for the secret
    store, plus the KMS selection and key path", derived from the readers. In
    managed mode the state owns the storage arrangement, so it owns all of
    them -- there is no member of that set a town admin should be able to
    change."""
    assert not (DB_REQUIRED_KEYS - PLATFORM_MANAGED_KEYS)


@pytest.mark.parametrize("key", [
    "AWS_KMS_KEY_ID", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION",
    "AZURE_KEYVAULT_CLIENT_SECRET", "AZURE_TENANT_ID", "AZURE_KEYVAULT_KEY",
    "KMS_PROVIDER", "SECRETS_PROVIDER",
])
def test_the_keys_that_were_missing(key):
    """Named individually because each was a live hole, and because a
    regression here is silent: the write succeeds and the state finds out when
    its own key stops being used."""
    assert is_platform_managed(key), key


@pytest.mark.parametrize("key", [
    "SECRET_KEY", "DATABASE_URL", "DB_PASSWORD", "REDIS_URL",
    "PROVISIONING_TOKEN", "DOMAIN",
])
def test_the_platform_still_owns_the_host_level_settings(key):
    assert is_platform_managed(key), key


@pytest.mark.parametrize("key", [
    "TWILIO_AUTH_TOKEN", "GOOGLE_MAPS_API_KEY", "AUTH0_CLIENT_SECRET",
    "SMTP_PASSWORD", "ACS_ACCESS_KEY", "REDACT_FACES",
])
def test_the_town_still_owns_its_own_services(key):
    """The point of managed mode is that the state runs the plumbing and the
    town runs its 311 service. Locking a town out of its own Twilio account
    would make the arrangement useless."""
    assert not is_platform_managed(key), key


def test_backups_belong_to_the_platform():
    """Prefix rule, not a listed key: the state takes the backups on a hosted
    deployment, and a town pointing them at its own bucket would move resident
    PII outside the arrangement the state is accountable for."""
    assert is_platform_managed("BACKUP_S3_BUCKET")
    assert is_platform_managed("BACKUP_ENCRYPTION_KEY")


def test_the_set_answers_the_same_way_however_it_is_read():
    """An earlier draft made this a lazily-resolving frozenset subclass. It
    answered `in` correctly and returned empty for `set()` and iteration,
    because CPython reads the underlying storage directly for those. A guard
    that is right only for the operation you happened to test is worse than no
    guard, so this checks the other readings too."""
    assert len(PLATFORM_MANAGED_KEYS) == len(set(PLATFORM_MANAGED_KEYS))
    assert len(list(PLATFORM_MANAGED_KEYS)) == len(PLATFORM_MANAGED_KEYS)
    assert "AWS_KMS_KEY_ID" in set(PLATFORM_MANAGED_KEYS)


def test_the_guard_is_off_when_managed_mode_is_off():
    """Self-hosted is the default and must be untouched: a town running its own
    instance owns every key on the page."""
    from app.core.managed import reject_platform_key_writes
    from app.core.config import get_settings

    if get_settings().managed_mode:
        pytest.skip("this environment has managed mode on")
    reject_platform_key_writes("AWS_KMS_KEY_ID")  # must not raise
