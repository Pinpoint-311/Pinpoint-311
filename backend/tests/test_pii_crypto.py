"""Envelope PII encryption: round-trip, tamper detection, DEK amortization,
REQUIRE_KMS enforcement, and backward-compatible legacy decryption."""
import base64
import os

import pytest

from app.core import pii_crypto
from app.core import encryption as enc


def setup_function(_):
    os.environ.pop("REQUIRE_KMS", None)
    os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    os.environ.pop("KMS_PROVIDER", None)
    pii_crypto.clear_caches()


def test_round_trip():
    tok = pii_crypto.encrypt("Jane Q. Resident")
    assert tok.startswith("pii2:")
    assert pii_crypto.decrypt(tok) == "Jane Q. Resident"


def test_tamper_detected():
    tok = pii_crypto.encrypt("resident@example.com")
    p, w, n, c = tok.split(":", 3)
    raw = bytearray(base64.b64decode(c))
    raw[0] ^= 0x01
    bad = f"{p}:{w}:{n}:{base64.b64encode(bytes(raw)).decode()}"
    with pytest.raises(Exception):
        pii_crypto.decrypt(bad)


def test_single_dek_amortized_across_many_encrypts():
    toks = [pii_crypto.encrypt(f"v{i}") for i in range(50)]
    wraps = {t.split(":", 3)[1] for t in toks}
    assert len(wraps) == 1
    assert len(pii_crypto._unwrap_cache) == 1


def test_encrypt_pii_helpers_and_is_encrypted():
    e = enc.encrypt_pii("resident@example.com")
    assert e.startswith("pii2:")
    assert enc.is_encrypted(e)
    assert enc.decrypt_pii(e) == "resident@example.com"
    assert enc.decrypt_safe(e) == "resident@example.com"


def test_legacy_fernet_still_decrypts():
    legacy = enc.encrypt("legacy-value")
    assert legacy.startswith("gAAAA")
    assert enc.decrypt_safe(legacy) == "legacy-value"
    assert enc.is_encrypted(legacy)


def test_empty_passthrough():
    assert enc.encrypt_pii("") == ""
    assert enc.decrypt_pii("") == ""


def test_require_kms_refuses_local_fallback():
    os.environ["REQUIRE_KMS"] = "1"
    pii_crypto.clear_caches()
    with pytest.raises(Exception):
        enc.encrypt_pii("must-be-hsm")
    os.environ.pop("REQUIRE_KMS", None)
    pii_crypto.clear_caches()
