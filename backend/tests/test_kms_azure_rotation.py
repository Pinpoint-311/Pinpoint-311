"""Rotating the Azure key must not lock residents' data.

Azure Key Vault's unwrap names a key version, or uses the current one. The
client used to call it without a version, and stored no version with the
wrapped data key -- so the first time a town rotated its key (a 90-day policy
is ordinary), every data key wrapped under the previous version would have
been sent to the new one and refused, and every resident's contact details
would have stopped decrypting while the version that could open them sat
enabled in the same vault.

These run the real `azure_keyvault` client against a fake vault that keeps
versions the way Key Vault does: a wrap uses the current version and says so
in `kid`; an unwrap with a version uses that one; an unwrap without a version
uses the current one; rotating adds a version and leaves the old one enabled.
"""
import base64
import importlib
import sys

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("cryptography.hazmat.primitives.ciphers.aead")

VAULT = "https://town.vault.azure.net"


class FakeVault:
    """Key Vault's key endpoints, versioned. 'Wrapping' is reversible tagging
    with the version, so a wrong-version unwrap fails the way Azure's does."""

    def __init__(self):
        self.versions = ["v1"]
        self.disabled = set()
        self.recovery_level = "Recoverable"
        self.exp = None
        self.calls = []

    @property
    def current(self):
        return self.versions[-1]

    def rotate(self):
        self.versions.append(f"v{len(self.versions) + 1}")

    def _resp(self, method, url, status, body):
        return httpx.Response(status, json=body, request=httpx.Request(method, url))

    def post(self, url, headers=None, json=None, timeout=None):
        path = url.split("?")[0][len(VAULT):]          # /keys/<name>[/<version>]/<op>
        parts = path.strip("/").split("/")
        op = parts[-1]
        version = parts[2] if len(parts) == 4 else self.current
        self.calls.append((op, parts[2] if len(parts) == 4 else None))
        if version in self.disabled:
            return self._resp("POST", url, 403, {"error": {"code": "Forbidden"}})
        if op == "wrapkey":
            token = base64.urlsafe_b64encode(f"{version}|{json['value']}".encode()).decode().rstrip("=")
            return self._resp("POST", url, 200, {"kid": f"{VAULT}/keys/pii/{version}", "value": token})
        raw = base64.urlsafe_b64decode(json["value"] + "==").decode()
        wrapped_by, value = raw.split("|", 1)
        if wrapped_by != version:
            return self._resp("POST", url, 400, {"error": {"code": "BadParameter", "message": "decryption failed"}})
        return self._resp("POST", url, 200, {"kid": f"{VAULT}/keys/pii/{version}", "value": value})

    def get(self, url, headers=None, timeout=None):
        path = url.split("?")[0][len(VAULT):]
        if path.endswith("/versions"):
            return self._resp("GET", url, 200, {"value": [
                {"kid": f"{VAULT}/keys/pii/{v}", "attributes": {"enabled": v not in self.disabled, "created": i}}
                for i, v in enumerate(self.versions)]})
        attrs = {"enabled": True, "recoveryLevel": self.recovery_level, "recoverableDays": 90,
                 "exportable": False}
        if self.exp:
            attrs["exp"] = self.exp
        return self._resp("GET", url, 200, {"key": {"kid": f"{VAULT}/keys/pii/{self.current}"},
                                            "attributes": attrs})


@pytest.fixture
def vault(monkeypatch):
    kv = importlib.import_module("app.core.azure_keyvault")
    pii = importlib.import_module("app.core.pii_crypto")
    enc = importlib.import_module("app.core.encryption")
    fake = FakeVault()
    cfg = {"AZURE_KEYVAULT_URL": VAULT, "AZURE_KEYVAULT_KEY": "pii"}
    monkeypatch.setattr(kv, "_cfg", lambda k: cfg.get(k))
    monkeypatch.setattr(kv, "_get_token", lambda: "t")
    monkeypatch.setattr(kv, "is_configured", lambda: True)
    monkeypatch.setattr(kv.httpx, "post", fake.post)
    monkeypatch.setattr(kv.httpx, "get", fake.get)
    kv._current_version_cache.clear()
    monkeypatch.setattr(enc, "_kms_provider", lambda: "azure")
    import app.core
    monkeypatch.setattr(app.core, "azure_keyvault", kv, raising=False)
    monkeypatch.setitem(sys.modules, "app.core.azure_keyvault", kv)
    pii.clear_caches()
    yield fake
    pii.clear_caches()
    kv._current_version_cache.clear()


def _forget(pii, kv):
    """A fresh process: no cached data keys, no cached current version."""
    pii.clear_caches()
    kv._current_version_cache.clear()


def test_a_wrap_records_the_key_version(vault):
    pii = importlib.import_module("app.core.pii_crypto")
    token = pii.encrypt("resident@example.gov")
    wrapped = base64.b64decode(token.split(":")[1])
    assert wrapped[:1] == b"A"
    assert wrapped[1:].split(b".", 1)[0] == b"v1"


def test_data_wrapped_before_a_rotation_still_decrypts_after_it(vault):
    pii = importlib.import_module("app.core.pii_crypto")
    kv = importlib.import_module("app.core.azure_keyvault")
    token = pii.encrypt("resident@example.gov")

    vault.rotate()
    _forget(pii, kv)
    assert pii.decrypt(token) == "resident@example.gov"
    assert ("unwrapkey", "v1") in vault.calls          # asked the version that wrapped it

    # And new data goes under the new version.
    new = pii.encrypt("other@example.gov")
    assert base64.b64decode(new.split(":")[1])[1:].split(b".", 1)[0] == b"v2"


def test_values_from_before_versions_were_recorded_survive_a_rotation(vault):
    """The 'a' format: no version stored. Current version first, then older ones."""
    pii = importlib.import_module("app.core.pii_crypto")
    kv = importlib.import_module("app.core.azure_keyvault")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    dek = AESGCM.generate_key(bit_length=256)
    _, token = kv.wrap_versioned(base64.b64encode(dek).decode())   # wrapped by v1
    legacy_wrapped = base64.b64encode(b"a" + token.encode()).decode()
    nonce = b"\x01" * 12
    ct = AESGCM(dek).encrypt(nonce, b"resident@example.gov", b"pinpoint-pii-v2")
    legacy = f"pii2:{legacy_wrapped}:{base64.b64encode(nonce).decode()}:{base64.b64encode(ct).decode()}"

    vault.rotate()
    vault.rotate()
    _forget(pii, kv)
    assert pii.decrypt(legacy) == "resident@example.gov"


def test_the_nightly_rewrap_sees_what_a_rotation_left_behind(vault):
    pii = importlib.import_module("app.core.pii_crypto")
    kv = importlib.import_module("app.core.azure_keyvault")
    old = pii.encrypt("resident@example.gov").split(":")[1]
    assert pii.wrapped_is_current(old, "azure")

    vault.rotate()
    _forget(pii, kv)
    assert not pii.wrapped_is_current(old, "azure")    # old version: re-wrap it
    new = pii.encrypt("resident@example.gov").split(":")[1]
    assert pii.wrapped_is_current(new, "azure")
    assert not pii.wrapped_is_current(base64.b64encode(b"a" + b"tok").decode(), "azure")   # unversioned: re-wrap
    assert not pii.wrapped_is_current(new, "aws")       # another backend


def test_a_running_process_moves_to_the_new_version(vault, monkeypatch):
    """No restart needed: within ten minutes new writes use the rotated key."""
    pii = importlib.import_module("app.core.pii_crypto")
    kv = importlib.import_module("app.core.azure_keyvault")
    first = pii.encrypt("a@example.gov").split(":")[1]
    vault.rotate()
    kv._current_version_cache.clear()
    assert pii.encrypt("b@example.gov").split(":")[1] == first      # inside the ten minutes
    monkeypatch.setattr(pii, "_active_checked", 0.0)                # ten minutes later
    later = pii.encrypt("c@example.gov").split(":")[1]
    assert later != first
    assert base64.b64decode(later)[1:].split(b".", 1)[0] == b"v2"


def test_an_authorisation_failure_is_not_retried_against_other_versions(vault):
    kv = importlib.import_module("app.core.azure_keyvault")
    _, token = kv.wrap_versioned("x")
    vault.rotate()
    vault.disabled.add("v2")          # current version refuses with 403
    vault.calls.clear()
    with pytest.raises(httpx.HTTPStatusError):
        kv.decrypt_any_version(token)
    assert vault.calls == [("unwrapkey", None)]


def test_health_flags_a_key_that_could_be_purged_or_is_about_to_expire(vault, monkeypatch):
    import time
    health = importlib.import_module("app.services.proactive_health")
    pii = importlib.import_module("app.core.pii_crypto")
    monkeypatch.setattr(pii, "probe_backend", lambda: "azure")

    def check():
        import asyncio
        return asyncio.run(health._kms_check())

    assert check()["status"] == "ok"
    assert "purge protection on" in check()["message"]

    vault.recovery_level = "Recoverable+Purgeable"
    assert check()["status"] == "warning"
    assert "purge protection is off" in check()["message"]

    vault.recovery_level = "Recoverable"
    vault.exp = time.time() + 3 * 86400
    assert check()["status"] == "critical"
