"""Keyed lookup fingerprints ("blind indexes") for resident email and name.

Resident PII is encrypted with AES-256-GCM and a fresh random nonce per value
(see pii_crypto), so two reports from the same address have unrelated
ciphertexts and the database cannot answer "which reports did this person
file?". That is a deliberate property and this module does not weaken it: the
ciphertext columns are untouched.

What it adds, only while a town has the "Resident history" module switched on,
is a separate column holding HMAC-SHA256(index_key, normalised value). Equal
inputs give equal fingerprints, so staff can look up a resident's earlier
reports, while a fingerprint reveals nothing about the value without the key.

Properties a government deployment relies on:

  * Opt-in data. Fingerprints exist only while the module is on. Turning it
    off erases every fingerprint (maintain(), below); turning it on rebuilds
    them. A town that never opts in never holds a linkable identifier.
  * The key is 256 random bits, generated once per town -- not derived from
    SECRET_KEY, which would let anyone holding the database plus that one
    setting test "did jane@example.com ever file a report?" offline.
  * The key is wrapped exactly as resident PII is (pii_crypto: the town's KMS
    when one is configured) with no silent fallback to a weaker scheme, and is
    re-wrapped when the town's key service changes, as PII is.
  * Nothing on the request path loads the key or touches the database: the
    model setters fingerprint only when the key is already in memory and the
    module is on, and otherwise leave the row for maintain() to fill.
  * Placeholder and retention addresses (anything at a `.local` domain) and
    "[ARCHIVED]" names have no fingerprint, so connector imports without an
    email are not lumped together as one "resident", and a retention scrub,
    which rewrites the fields through the setters, unlinks the record.
"""
import base64
import hashlib
import hmac
import logging
import os
import threading
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

# Bumped when normalisation or the key changes; rows below it are rebuilt.
#   1  initial
#   2  NFKC normalisation; `.local` placeholder addresses excluded
VERSION = 2

MODULE_KEY = "resident_history"
_ARCHIVED_NAME = "[archived]"
_LOCK_SQL_ID = "hashtext('pinpoint-resident-index')"

_lock = threading.Lock()
_key: Optional[bytes] = None
# This process's view of the module switch, refreshed by maintain(). Starts off,
# so nothing is fingerprinted until the switch has actually been read as on.
_enabled = False


class IndexKeyUnavailable(RuntimeError):
    """The index key could not be loaded or created (database or KMS down)."""


# ---- normalisation ----------------------------------------------------------

def _fold(value: Optional[str]) -> str:
    # NFKC first, so a composed "é" and an "e" plus combining accent agree.
    return " ".join(unicodedata.normalize("NFKC", value or "").split()).casefold()


def normalise_email(value: Optional[str]) -> Optional[str]:
    v = _fold(value).replace(" ", "")
    if not v or v.count("@") != 1:
        return None
    local, domain = v.split("@")
    # `.local` is never a resident's real address here: it is what intake writes
    # when there is none (manual-<id>@intake.local, integration-<platform>@
    # intake.local) and what retention writes over one (archived-<id>@
    # retention.local). Fingerprinting the shared connector placeholder would
    # make every connector import look like one resident's history.
    if not local or not domain or domain == "local" or domain.endswith(".local"):
        return None
    return v


def normalise_name(first: Optional[str], last: Optional[str]) -> Optional[str]:
    parts = []
    for part in (first, last):
        p = _fold(part)
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

def _decrypt_strict(token: str) -> str:
    """Decrypt or raise. decrypt_pii returns "" on failure, which here would
    read as "this resident has no email" and be written down as such."""
    from app.core import pii_crypto
    from app.core.encryption import decrypt_pii
    if token.startswith(pii_crypto.PII_V2_PREFIX):
        return pii_crypto.decrypt(token)
    plain = decrypt_pii(token)
    if not plain:
        raise ValueError("value could not be decrypted")
    return plain


def _wrap(secret_b64: str) -> str:
    # pii_crypto directly, not encrypt_pii: encrypt_pii falls back to a
    # SECRET_KEY-only scheme when the KMS call fails, and the key must never be
    # created under that silently.
    from app.core import pii_crypto
    return pii_crypto.encrypt(secret_b64)


def _wrap_tag(token: str) -> Optional[str]:
    from app.services.storage_status import WRAP_TAGS
    try:
        wrapped_b64 = token.split(":")[1]
        return WRAP_TAGS.get(base64.b64decode(wrapped_b64 + "==")[:1])
    except Exception:
        return None


def _load_or_create_key() -> bytes:
    from sqlalchemy import text
    from app.db.session import sync_engine

    with sync_engine.begin() as conn:
        row = conn.execute(text("SELECT wrapped_key FROM pii_index_keys ORDER BY id LIMIT 1")).first()
        if row is None:
            fresh = base64.b64encode(os.urandom(32)).decode("ascii")
            conn.execute(
                text("INSERT INTO pii_index_keys (id, wrapped_key) VALUES (1, :k) "
                     "ON CONFLICT (id) DO NOTHING"),
                {"k": _wrap(fresh)},
            )
            row = conn.execute(text("SELECT wrapped_key FROM pii_index_keys ORDER BY id LIMIT 1")).first()
    key = base64.b64decode(_decrypt_strict(row[0]))
    if len(key) != 32:
        raise IndexKeyUnavailable("index key has the wrong length")
    return key


def ensure_key() -> bytes:
    """Load (or create) the key. Blocking: call from a thread, never the loop."""
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
                raise IndexKeyUnavailable(type(exc).__name__) from exc
    return _key


def reset_key_cache() -> None:
    global _key
    with _lock:
        _key = None


def _rewrap_key_if_stale() -> None:
    """Move the key onto the town's current key service, as rewrap_pii does
    for resident PII, so adding a KMS later protects the index key too.

    Decided by re-wrapping and comparing: the wrap the current configuration
    produces is the truth, whatever the provider setting is called."""
    from sqlalchemy import text
    from app.db.session import sync_engine

    with sync_engine.begin() as conn:
        row = conn.execute(text("SELECT id, wrapped_key FROM pii_index_keys ORDER BY id LIMIT 1")).first()
        if row is None:
            return
        rewrapped = _wrap(_decrypt_strict(row[1]))
        if _wrap_tag(rewrapped) == _wrap_tag(row[1]):
            return
        conn.execute(text("UPDATE pii_index_keys SET wrapped_key = :k WHERE id = :id"),
                     {"k": rewrapped, "id": row[0]})
        logger.info("[ResidentIndex] re-wrapped the index key onto the current key service (%s)",
                    _wrap_tag(rewrapped))


def _mac(key: bytes, domain: bytes, value: str) -> str:
    return hmac.new(key, domain + b"\x00" + value.encode("utf-8"), hashlib.sha256).hexdigest()


# ---- fingerprints -----------------------------------------------------------

def email_index(value: Optional[str], key: Optional[bytes] = None) -> Optional[str]:
    norm = normalise_email(value)
    return _mac(key or ensure_key(), b"email", norm) if norm else None


def name_index(first: Optional[str], last: Optional[str], key: Optional[bytes] = None) -> Optional[str]:
    norm = normalise_name(first, last)
    return _mac(key or ensure_key(), b"name", norm) if norm else None


def name_index_from_full(full_name: Optional[str], key: Optional[bytes] = None) -> Optional[str]:
    """For a search box: "Jane  Q Doe" -> first token + the rest."""
    parts = (full_name or "").split()
    if len(parts) < 2:
        return None
    return name_index(parts[0], " ".join(parts[1:]), key=key)


def ready_key() -> Optional[bytes]:
    """The key, only if the module is on and the key is already in memory.

    What the model setters use: no I/O, no lock, no KMS call on the request
    path. None means "leave it for maintain()".
    """
    return _key if _enabled else None


# ---- maintenance ------------------------------------------------------------

def _read_enabled() -> bool:
    from sqlalchemy import text
    from app.db.session import sync_engine
    with sync_engine.connect() as conn:
        row = conn.execute(text("SELECT modules FROM system_settings ORDER BY id LIMIT 1")).first()
    modules = (row[0] if row else None) or {}
    if isinstance(modules, str):
        import json
        modules = json.loads(modules)
    return bool(modules.get(MODULE_KEY, False))


def maintain(batch_size: int = 200) -> dict:
    """Bring fingerprints in line with the module switch. Never raises.

    Off: erase every fingerprint. On: load the key, keep it on the current key
    service, and fingerprint rows missing one or below VERSION. Runs in a
    thread at startup, every few minutes, and right after an admin changes
    modules. A Postgres advisory lock keeps two processes from doing it at once.
    """
    global _enabled
    out = {"enabled": None, "indexed": 0, "cleared": 0}
    try:
        from sqlalchemy import text
        from app.db.session import sync_engine

        _enabled = _read_enabled()
        out["enabled"] = _enabled
        if _enabled:
            # Loaded before taking the lock, so a process that loses the race
            # for the lock still has the key for its own setters.
            ensure_key()

        with sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock_conn:
            if not lock_conn.execute(text(f"SELECT pg_try_advisory_lock({_LOCK_SQL_ID})")).scalar():
                return out
            try:
                if not _enabled:
                    with sync_engine.begin() as conn:
                        out["cleared"] = conn.execute(text(
                            "UPDATE service_requests SET resident_email_index = NULL, "
                            "resident_name_index = NULL, pii_index_version = NULL "
                            "WHERE resident_email_index IS NOT NULL OR resident_name_index IS NOT NULL "
                            "OR pii_index_version IS NOT NULL")).rowcount or 0
                    if out["cleared"]:
                        logger.info("[ResidentIndex] module off: erased fingerprints on %d reports", out["cleared"])
                    return out
                _rewrap_key_if_stale()
                out["indexed"] = _backfill(ensure_key(), batch_size)
            finally:
                lock_conn.execute(text(f"SELECT pg_advisory_unlock({_LOCK_SQL_ID})"))
    except Exception as exc:
        logger.warning("[ResidentIndex] maintenance stopped: %s", type(exc).__name__)
    return out


def _backfill(key: bytes, batch_size: int) -> int:
    """Fingerprint rows missing one. Stops, marking nothing further, at the
    first value that will not decrypt, so a key-service outage leaves the rest
    for the next run instead of recording them as having no email."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.db.session import sync_engine
    from app.models import ServiceRequest

    done = 0
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
                    return _decrypt_strict(raw) if raw else None
                email = plain("_email_encrypted")
                first = plain("_first_name_encrypted")
                last = plain("_last_name_encrypted")
                rec.resident_email_index = email_index(email, key=key)
                rec.resident_name_index = name_index(first, last, key=key)
                rec.pii_index_version = VERSION
            session.commit()
            done += len(rows)
    if done:
        logger.info("[ResidentIndex] fingerprinted %d reports", done)
    return done
