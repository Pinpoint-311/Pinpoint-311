"""Verify the Azure Key Vault DEK-wrapping branch actually round-trips.

Mirrors test_kms_aws.py for the Azure path: a stub azure_keyvault (reversible
AES-GCM over the ascii wrapped token) exercises the real pii_crypto wrap/unwrap
dispatch — the "a" tag, provider routing, and that a value wrapped under Azure
decrypts back — without a live Azure account.
"""
import base64
import importlib


def test_azure_kms_wrap_roundtrip(monkeypatch):
    pii = importlib.import_module("app.core.pii_crypto")
    enc = importlib.import_module("app.core.encryption")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _kek = b"\x22" * 32

    class _FakeAzureKeyVault:
        # pii_crypto's Azure branch calls encrypt(b64_str) -> str and
        # decrypt(str) -> b64_str; both must be ascii-safe strings.
        @staticmethod
        def is_configured():
            return True

        @staticmethod
        def encrypt(b64_plaintext: str) -> str:
            nonce = b"\x00" * 12
            ct = AESGCM(_kek).encrypt(nonce, b64_plaintext.encode("ascii"), b"azurekv")
            return base64.urlsafe_b64encode(nonce + ct).decode("ascii")

        @staticmethod
        def decrypt(token: str) -> str:
            blob = base64.urlsafe_b64decode(token.encode("ascii"))
            nonce, ct = blob[:12], blob[12:]
            return AESGCM(_kek).decrypt(nonce, ct, b"azurekv").decode("ascii")

    monkeypatch.setattr(enc, "_kms_provider", lambda: "azure")
    monkeypatch.setitem(__import__("sys").modules, "app.core.azure_keyvault", _FakeAzureKeyVault)
    pii.clear_caches()

    token = pii.encrypt("resident@example.gov")
    assert token.startswith("pii2:")
    # The active DEK must be wrapped under the Azure backend (tag "a").
    assert pii.active_backend() == "azure"
    # And it must decrypt back to the original.
    assert pii.decrypt(token) == "resident@example.gov"

    pii.clear_caches()
