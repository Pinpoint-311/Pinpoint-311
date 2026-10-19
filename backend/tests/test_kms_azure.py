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
        def decrypt(token: str, version=None) -> str:
            blob = base64.urlsafe_b64decode(token.encode("ascii"))
            nonce, ct = blob[:12], blob[12:]
            return AESGCM(_kek).decrypt(nonce, ct, b"azurekv").decode("ascii")

        # The versioned calls pii_crypto makes (see test_kms_azure_rotation.py
        # for rotation itself): one key version here.
        @classmethod
        def wrap_versioned(cls, b64_plaintext: str):
            return "v1", cls.encrypt(b64_plaintext)

        @classmethod
        def decrypt_any_version(cls, token: str) -> str:
            return cls.decrypt(token)

        @staticmethod
        def current_key_version():
            return "v1"

    monkeypatch.setattr(enc, "_kms_provider", lambda: "azure")
    # Both the package attribute and sys.modules. `_wrap_dek` reaches the real
    # module via `from app.core import azure_keyvault`, which reads the
    # attribute off the already-imported package and never consults sys.modules
    # -- so patching sys.modules alone only worked while nothing earlier in the
    # run had imported it. Order-dependent, and it passed only by luck.
    import app.core
    monkeypatch.setitem(__import__("sys").modules, "app.core.azure_keyvault", _FakeAzureKeyVault)
    monkeypatch.setattr(app.core, "azure_keyvault", _FakeAzureKeyVault, raising=False)
    pii.clear_caches()

    token = pii.encrypt("resident@example.gov")
    assert token.startswith("pii2:")
    # The active DEK must be wrapped under the Azure backend (tag "A", versioned).
    assert pii.active_backend() == "azure"
    # And it must decrypt back to the original.
    assert pii.decrypt(token) == "resident@example.gov"

    pii.clear_caches()
