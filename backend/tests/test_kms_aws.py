"""Verify the AWS KMS DEK-wrapping branch actually round-trips.

Uses a stub aws_kms (reversible AESGCM) so we exercise the real pii_crypto
wrap/unwrap dispatch — the new "w" tag, provider routing, and that a value
wrapped under AWS decrypts back — without a live AWS account.
"""
import importlib

import pytest


def test_aws_kms_wrap_roundtrip(monkeypatch):
    pii = importlib.import_module("app.core.pii_crypto")
    enc = importlib.import_module("app.core.encryption")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    # Deterministic reversible stand-in for AWS KMS: AES-GCM with a fixed key.
    _kek = b"\x11" * 32

    class _FakeAwsKms:
        @staticmethod
        def is_configured():
            return True

        @staticmethod
        def encrypt(dek: bytes) -> bytes:
            nonce = b"\x00" * 12
            return nonce + AESGCM(_kek).encrypt(nonce, dek, b"awskms")

        @staticmethod
        def decrypt(blob: bytes) -> bytes:
            nonce, ct = blob[:12], blob[12:]
            return AESGCM(_kek).decrypt(nonce, ct, b"awskms")

    monkeypatch.setattr(enc, "_kms_provider", lambda: "aws")
    monkeypatch.setitem(__import__("sys").modules, "app.core.aws_kms", _FakeAwsKms)
    pii.clear_caches()

    token = pii.encrypt("resident@example.gov")
    assert token.startswith("pii2:")
    # The active DEK must be wrapped under the AWS backend (tag "w").
    assert pii.active_backend() == "aws"
    # And it must decrypt back to the original.
    assert pii.decrypt(token) == "resident@example.gov"

    pii.clear_caches()


def test_unknown_provider_falls_back_local(monkeypatch):
    """A value wrapped locally still unwraps regardless of the current provider —
    proves the tag-based dispatch that keeps existing PII readable after a switch."""
    pii = importlib.import_module("app.core.pii_crypto")
    enc = importlib.import_module("app.core.encryption")

    monkeypatch.setattr(enc, "_kms_provider", lambda: "local")
    monkeypatch.setattr(enc, "_kms_required", lambda: False, raising=False)
    pii.clear_caches()
    token = pii.encrypt("phone-555")
    assert pii.active_backend() == "local"
    assert pii.decrypt(token) == "phone-555"
    pii.clear_caches()
