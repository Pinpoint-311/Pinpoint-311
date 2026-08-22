"""Whether the stored data matches the storage a town has chosen.

Three maintenance actions used to sit on the setup page as buttons a clerk had
to know when to press: "Vault Local Secrets to GCP Identity", "Re-encrypt All
PII Data (after key rotation)", and inventing a backup passphrase. Each is a
real operation, and each was phrased as a thing you do rather than a question
you can answer.

The system already knows the answer. A secret sitting in the database when a
store is configured is a fact you can count; PII wrapped with a key the town no
longer uses is a byte tag you can read. So the page can say "12 keys are still
in the database" and offer one button, instead of asking somebody to work out
whether "vaulting local secrets" applies to them.

Everything here is read-only and never raises: it drives an advisory panel, and
a status check that 500s would be worse than no panel at all.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# The first byte of a wrapped data key records which service wrapped it. Kept in
# step with pii_crypto's _WRAP_* constants.
WRAP_TAGS = {b"g": "google", b"a": "azure", b"w": "aws", b"l": "local"}


async def secrets_outside_the_store(db) -> Dict[str, Any]:
    """How many secrets still have a database copy that could be moved.

    Excludes the keys that must keep one -- the credentials for the store
    itself, and the KMS settings whose only readers look at the database. Those
    are not work outstanding; they are supposed to be there.
    """
    result: Dict[str, Any] = {"count": 0, "store": None, "reachable": False,
                              "unreadable": 0, "unreadable_keys": []}
    try:
        from sqlalchemy import select

        from app.core.encryption import decrypt_safe
        from app.models import SystemSecret
        from app.services.secret_manager import DB_REQUIRED_KEYS, _secrets_provider
        from app.services.storage_maintenance import store_reachable

        # None rather than "", so the panel can say "not chosen yet" instead of
        # rendering an empty store name.
        result["store"] = _secrets_provider() or None
        # The same check the migration gates on, so the page cannot say work is
        # pending that the scheduled job has already decided it cannot do.
        result["reachable"] = store_reachable()

        rows = (await db.execute(
            select(SystemSecret.key_name, SystemSecret.key_value)
            .where(SystemSecret.key_value.isnot(None))
        )).all()
        result["count"] = sum(1 for key, _ in rows if key not in DB_REQUIRED_KEYS)

        # Credentials that are in the database and cannot be read out of it.
        #
        # `decrypt_safe` returns "" for a value that looks encrypted and will
        # not decrypt, which is exactly what a SECRET_KEY rotation leaves
        # behind. Every reader downstream treats "" as absent, so the card goes
        # back to showing an empty box and the town's reasonable conclusion is
        # that the credential was never saved. It was saved; it is stuck, and
        # re-entering it is the fix -- but only if somebody says so.
        #
        # The migration already works this out: `migrate_to_secret_manager`
        # files precisely these under `unreadable`. But `vault_secrets` returns
        # early when `store_reachable()` is false, so a town keeping its
        # credentials in the encrypted database -- a supported choice, and the
        # one every managed tenancy is given -- had no surface anywhere that
        # named SECRET_KEY as the cause. This is that surface. It costs one
        # decrypt per row, on an endpoint that already exists to be advisory.
        #
        # Names only, deliberately: the point is to say which credentials to
        # re-enter, and the values are the part that cannot be read anyway.
        unreadable = []
        for key, value in rows:
            if not value:
                continue
            try:
                if not decrypt_safe(value):
                    unreadable.append(key)
            except Exception:
                unreadable.append(key)
        result["unreadable"] = len(unreadable)
        result["unreadable_keys"] = sorted(unreadable)
    except Exception as exc:
        logger.debug("storage status: could not count database secrets: %s", exc)
    return result


async def pii_wrapped_with_other_keys(db) -> Dict[str, Any]:
    """How many records are wrapped with a key other than the one in use.

    A stored value looks like `pii2:<wrapped-dek>:<nonce>:<ciphertext>`, and the
    first byte inside that base64 wrapped-dek records which service wrapped it.
    Every row encrypted under the same key shares the same wrapped-dek string,
    so this groups by that segment rather than reading every row -- a town with
    a hundred thousand requests has two or three distinct values, not a hundred
    thousand.

    `local` is counted separately because it is the state a town reaches without
    choosing it: a KMS that was unreachable when a report came in falls back to
    the application key silently, and this is the only place that becomes
    visible.
    """
    out: Dict[str, Any] = {"total": 0, "stale": 0, "on_application_key": 0,
                           "legacy": 0, "current": None}
    try:
        import base64

        from sqlalchemy import func, select

        from app.core.encryption import _kms_provider
        from app.models import ServiceRequest

        current = _kms_provider()
        out["current"] = current

        for column in (ServiceRequest._email_encrypted, ServiceRequest._phone_encrypted):
            # split_part is 1-indexed: part 2 is the wrapped DEK.
            segment = func.split_part(column, ":", 2)
            rows = (await db.execute(
                select(segment, func.count())
                .where(column.isnot(None))
                .group_by(segment)
            )).all()

            for wrapped_b64, count in rows:
                out["total"] += count
                if not wrapped_b64:
                    # No pii2: prefix -- the older Fernet format, which
                    # re-encrypting migrates.
                    out["legacy"] += count
                    out["stale"] += count
                    continue
                try:
                    tag = WRAP_TAGS.get(base64.b64decode(wrapped_b64 + "==")[:1])
                except Exception:
                    tag = None
                if tag is None:
                    out["legacy"] += count
                    out["stale"] += count
                    continue
                if tag == "local":
                    out["on_application_key"] += count
                if tag != current:
                    out["stale"] += count
    except Exception as exc:
        logger.debug("storage status: could not count wrapped PII: %s", exc)
    return out


async def summary(db) -> Dict[str, Any]:
    """Everything the setup page needs to decide whether to say anything."""
    secrets = await secrets_outside_the_store(db)
    pii = await pii_wrapped_with_other_keys(db)
    return {
        "secrets": secrets,
        "pii": pii,
        # The page shows nothing at all unless one of these is true, so a town
        # with nothing outstanding is never asked to think about any of it.
        #
        # `unreadable` counts here even though nothing scheduled will clear it.
        # That is the reason it counts: the other two resolve themselves
        # overnight, and this one waits for a person who currently has no way
        # to learn it is waiting.
        "needs_attention": bool(
            (secrets["count"] and secrets["reachable"])
            or pii["stale"]
            or secrets["unreadable"]
        ),
    }
