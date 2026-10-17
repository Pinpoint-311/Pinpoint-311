"""Keyed lookup fingerprints ("blind indexes") for resident email and name.

Resident PII is encrypted with AES-256-GCM and a fresh random nonce per value
(see pii_crypto), so two reports from the same address have unrelated
ciphertexts and the database cannot answer "which reports did this person
file?". That is a deliberate property and this module does not weaken it: the
ciphertext columns are untouched.

What it adds is a separate column holding HMAC-SHA256(index_key, normalised
value). Equal inputs give equal fingerprints, so staff can look up a resident's
earlier reports (the opt-in "Resident history" module), while the fingerprint
itself reveals nothing about the value without the key.

The key is the part that matters for a government deployment:

  * It is 256 random bits, generated once per town -- not derived from
    SECRET_KEY. A derived key would let anyone holding the database plus that
    one setting test "did jane@example.com ever file a report?" offline, even
    on a town whose PII is otherwise protected by a cloud KMS.
  * It is stored in its own table, wrapped by the same envelope encryption as
    resident PII (encrypt_pii), so on a town with Azure Key Vault, Google KMS or
    AWS KMS it cannot be read without that key service.
  * It is only ever held in this process's memory once unwrapped.

Retention: a scrubbed record's values are sentinels ("[ARCHIVED]" names,
"archived-<id>@retention.local" email). Those normalise to None here, so the
scrub that rewrites the fields also clears the fingerprints through the model
setters -- a scrubbed report cannot be linked back to the resident.
"""
import base64
import hashlib
import hmac
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Bumped if normalisation or the key ever changes; rows below it are rebuilt by
# backfill().
VERSION = 1

_RETENTION_EMAIL_DOMAIN = "@retention.local"
_ARCHIVED_NAME = "[archived]"

_lock = threading.Lock()
_key: Optional[bytes] = None


class IndexKeyUnavailable(RuntimeError):
    """The index key could not be loaded or created (database or KMS down)."""


# ---- normalisation ----------------------------------------------------------

def normalise_email(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip().casefold()
    if not v or "@" not in v or v.endswith(_RETENTION_EMAIL_DOMAIN):
        return None
    return v


def normalise_name(first: Optional[str], last: Optional[str]) -> Optional[str]:
    parts = []
    for part in (first, last):
        p = " ".join((part or "").split()).casefold()
        if p == _ARCHIVED_NAME:
            return None
        if p:
            parts.append(p)
    # A full name only. One part alone ("john") would group every John in town
    # under one fingerprint, which is a profile of nobody in particular.
    if len(parts) < 2:
        return None
    return " ".join(parts)


# ---- key --------------------------------------------------------------------

def _load_or_create_key() -> bytes:
    from sqlalchemy import text
    from app.db.session import sync_engine
    from app.core.encryption import decrypt_pii, encrypt_pii

    with sync_engine.begin() as conn:
        row = conn.execute(text("SELECT wrapped_key FROM pii_index_keys ORDER BY id LIMIT 1")).first()
        if row is None:
            fresh = base64.b64encode(os.urandom(32)).decode("ascii")
            conn.execute(
                text("INSERT INTO pii_index_keys (id, wrapped_key) VALUES (1, :k) "
                     "ON CONFLICT (id) DO NOTHING"),
                {"k": encrypt_pii(fresh)},
            )
            row = conn.execute(text("SELECT wrapped_key FROM pii_index_keys ORDER BY id LIMIT 1")).first()
    key = base64.b64decode(decrypt_pii(row[0]))
    if len(key) != 32:
        raise IndexKeyUnavailable("index key has the wrong length")
    return key


def _get_key() -> bytes:
    global _key
    if _key is not None:
        return _key
    with _lock:
        if _key is None:
            try:
                _key = _load_or_create_key()
            except IndexKeyUnavailable:
                raise
            except Exception as exc:
                raise IndexKeyUnavailable(str(exc)) from exc
    return _key


def reset_key_cache() -> None:
    global _key
    with _lock:
        _key = None


def _mac(domain: bytes, value: str) -> str:
    return hmac.new(_get_key(), domain + b"\x00" + value.encode("utf-8"), hashlib.sha256).hexdigest()


# ---- public -----------------------------------------------------------------

def email_index(value: Optional[str]) -> Optional[str]:
    norm = normalise_email(value)
    return _mac(b"email", norm) if norm else None


def name_index(first: Optional[str], last: Optional[str]) -> Optional[str]:
    norm = normalise_name(first, last)
    return _mac(b"name", norm) if norm else None


def name_index_from_full(full_name: Optional[str]) -> Optional[str]:
    """For a search box: "Jane  Q Doe" -> first token + the rest."""
    parts = (full_name or "").split()
    if len(parts) < 2:
        return None
    return name_index(parts[0], " ".join(parts[1:]))


def backfill(batch_size: int = 200) -> int:
    """Fingerprint every report that predates the index. Returns rows done.

    Runs at startup in a thread. A Postgres advisory lock keeps the API and the
    worker from both doing it. Stops -- without marking anything -- the moment a
    value cannot be decrypted, so a key-service outage leaves rows to retry next
    start rather than marking them indexed with nothing in them.
    """
    try:
        return _backfill(batch_size)
    except Exception as exc:
        # Database unreachable at startup, most likely. Nothing was marked, so
        # the next start picks the rows up.
        logger.warning("[ResidentIndex] backfill skipped: %s", type(exc).__name__)
        return 0


def _backfill(batch_size: int) -> int:
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from app.db.session import sync_engine
    from app.models import ServiceRequest
    from app.core.encryption import decrypt_pii

    done = 0
    with sync_engine.connect() as lock_conn:
        got = lock_conn.execute(text("SELECT pg_try_advisory_lock(hashtext('pinpoint-resident-index'))")).scalar()
        if not got:
            return 0
        try:
            _get_key()
            while True:
                with Session(sync_engine) as session:
                    rows = session.execute(
                        select(ServiceRequest)
                        .where((ServiceRequest.pii_index_version.is_(None))
                               | (ServiceRequest.pii_index_version < VERSION))
                        .order_by(ServiceRequest.id)
                        .limit(batch_size)
                    ).scalars().all()
                    if not rows:
                        break
                    for rec in rows:
                        def plain(col):
                            raw = getattr(rec, col)
                            return decrypt_pii(raw) if raw else None
                        email = plain("_email_encrypted")
                        first = plain("_first_name_encrypted")
                        last = plain("_last_name_encrypted")
                        rec.resident_email_index = email_index(email)
                        rec.resident_name_index = name_index(first, last)
                        rec.pii_index_version = VERSION
                    session.commit()
                    done += len(rows)
        except Exception as exc:
            logger.warning("[ResidentIndex] backfill stopped after %d rows: %s", done, type(exc).__name__)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(hashtext('pinpoint-resident-index'))"))
            lock_conn.commit()
    if done:
        logger.info("[ResidentIndex] fingerprinted %d existing reports", done)
    return done
