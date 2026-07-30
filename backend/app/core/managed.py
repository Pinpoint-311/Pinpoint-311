"""Managed-mode (state-hosted) helpers — ORCHESTRATOR_PLAN.md Part A.

Defines the platform/tenant secret split (A1) and the guard used to disable
infrastructure self-service endpoints in managed mode (A2). Everything here
is a no-op when MANAGED_MODE is off, so standalone/self-host behavior is
untouched.
"""

from fastapi import HTTPException

from app.core.config import get_settings

# The state owns infrastructure keys (injected by the orchestrator); the town
# owns provider/integration/branding keys. Must stay in sync with the
# orchestrator's secrets_policy module in the centralizedhosting repo.
#
# Written out by hand originally, and Google-shaped as a result: it named the
# GCP project, service account and KMS key path, and of Azure only the vault
# URL. Every AWS infrastructure key was absent, as were Azure's credentials and
# both provider selectors. On a state-hosted deployment running on AWS or Azure,
# a town admin could therefore overwrite AWS_KMS_KEY_ID, KMS_PROVIDER or
# SECRETS_PROVIDER and repoint the state's encryption and secret storage at
# something of their own. That is a privilege boundary, not a preference.
#
# So the infrastructure half is no longer hand-listed. DB_REQUIRED_KEYS is
# already the authoritative set of "credentials for the secret store, plus the
# KMS selection and key path", derived from the readers and pinned by
# test_secret_migration_safety. Anything that belongs to the platform's storage
# arrangement belongs to the platform in managed mode, and the two cannot drift
# apart again.
# Set at import. secret_manager imports nothing from app at module level, so
# there is no cycle -- and a plain frozenset is worth more than cleverness here:
# an earlier draft used a lazily-resolving frozenset subclass, which answered
# `in` correctly and returned empty for `set()` and iteration, because CPython
# reads the underlying storage directly for those. A guard that is right only
# for the operation you happened to test is worse than no guard.
from app.services.secret_manager import DB_REQUIRED_KEYS

PLATFORM_MANAGED_KEYS = frozenset({
    "SECRET_KEY",
    "DATABASE_URL",
    "DB_PASSWORD",
    "REDIS_URL",
    "PROVISIONING_TOKEN",
    "DOMAIN",
}) | frozenset(DB_REQUIRED_KEYS)

PLATFORM_MANAGED_PREFIXES = ("BACKUP_",)

MANAGED_BY_STATE_DETAIL = "Managed by your state"


def is_platform_managed(key_name: str) -> bool:
    key = (key_name or "").strip().upper()
    return key in PLATFORM_MANAGED_KEYS or key.startswith(PLATFORM_MANAGED_PREFIXES)


def reject_platform_key_writes(key_name: str) -> None:
    """A1 choke-point guard for secret writes. In managed mode the state owns
    platform keys — town admins may not overwrite them."""
    if get_settings().managed_mode and is_platform_managed(key_name):
        raise HTTPException(status_code=403, detail=MANAGED_BY_STATE_DETAIL)


def ensure_not_managed(feature: str = "This operation") -> None:
    """A2 gate for self-update / version-switch / runbook / domain endpoints.
    In hosted mode these arrive only via the orchestrator."""
    if get_settings().managed_mode:
        raise HTTPException(
            status_code=403, detail=f"{feature} is managed by your state"
        )


# ---- Lifecycle state (A7 suspend/resume, set by the orchestrator via A4) ----
#
# Silo tenancy = one process set per town, so a module-level cache is safe.
# Persisted in SystemSecret under this key and loaded at startup; the
# middleware in app.main consults the cache on every request.

LIFECYCLE_KEY = "INSTANCE_LIFECYCLE_STATE"
_lifecycle_state = "active"


def get_lifecycle_state() -> str:
    return _lifecycle_state


def set_lifecycle_state(state: str) -> None:
    global _lifecycle_state
    _lifecycle_state = state if state in ("active", "suspended") else "active"


async def load_lifecycle_state(db) -> str:
    """Load the persisted state into the cache (called from app startup)."""
    from sqlalchemy import select

    from app.core.encryption import decrypt_safe
    from app.models import SystemSecret

    try:
        result = await db.execute(
            select(SystemSecret).where(SystemSecret.key_name == LIFECYCLE_KEY)
        )
        row = result.scalar_one_or_none()
        if row and row.is_configured and row.key_value:
            set_lifecycle_state(decrypt_safe(row.key_value))
    except Exception:
        pass  # table may not exist yet on first boot
    return _lifecycle_state
