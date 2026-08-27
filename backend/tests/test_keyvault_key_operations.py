"""The client asks for the operation the template's key actually permits.

A Key Vault key carries a `keyOps` list, and wrapKey/unwrapKey are separate
entries from encrypt/decrypt even though RSA-OAEP performs the identical
operation for both. Our ARM template creates the key with
["wrapKey", "unwrapKey"] -- correct, and tighter than it needs to be -- while
this client called /encrypt and /decrypt. So a vault built by our own template
refused every call:

    403 "Operation encrypt is not permitted on this key." (KeyOperationForbidden)

Nothing surfaced. pii_crypto falls back to the application key when a KMS
refuses, so resident data was encrypted with the wrong key and the deployment
looked healthy. The two halves are written in different languages in different
directories by different people; nothing made them agree. This does.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARM = ROOT / "deploy/templates/azure/pinpoint-311.json"
CLIENT = ROOT / "backend/app/core/azure_keyvault.py"


def _template_key_ops():
    if not ARM.exists():
        pytest.skip("ARM template not present in this checkout")
    for resource in json.loads(ARM.read_text())["resources"]:
        if resource.get("type", "").endswith("vaults/keys"):
            return [op.lower() for op in resource["properties"]["keyOps"]]
    pytest.fail("the template no longer creates a key")


def _client_operations():
    source = CLIENT.read_text()
    return set(re.findall(r'_key_op\(\s*"([a-z]+)"', source))


def test_every_operation_the_client_asks_for_is_one_the_key_allows():
    allowed = _template_key_ops()
    asked = _client_operations()

    assert asked, "no key operations found in the client — did _key_op move?"
    for operation in asked:
        assert operation in allowed, (
            f"the client calls /{operation} but the template's key permits "
            f"{allowed}. Key Vault answers 403 KeyOperationForbidden and "
            f"pii_crypto silently falls back to the application key."
        )


def test_the_client_wraps_rather_than_encrypts():
    """Stated directly, so replacing _key_op with something else does not
    quietly reintroduce the pairing that failed."""
    asked = _client_operations()
    assert asked == {"wrapkey", "unwrapkey"}, asked


def test_the_template_key_is_not_widened_to_paper_over_it():
    """The fix belonged in the client. Adding encrypt/decrypt to the key would
    also have worked, and would have made every future deployment's key more
    capable than the software needs."""
    allowed = _template_key_ops()
    assert "encrypt" not in allowed
    assert "decrypt" not in allowed


class TestTheRequestItself:
    def _client(self, monkeypatch, captured):
        httpx = pytest.importorskip("httpx")
        from app.core import azure_keyvault as akv

        monkeypatch.setattr(akv, "_get_token", lambda: "token")
        monkeypatch.setattr(akv, "_cfg", lambda key: "pinpoint-311-pii")
        monkeypatch.setattr(akv, "_vault_url", lambda: "https://v.vault.azure.net")
        monkeypatch.setattr(akv, "_api_version", lambda: "7.4")

        class Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"value": "d3JhcHBlZA"}

        def post(url, **kwargs):
            captured.append(url)
            return Resp()

        monkeypatch.setattr(akv.httpx, "post", post)
        return akv

    def test_wrapping_hits_the_wrapkey_endpoint(self, monkeypatch):
        captured = []
        akv = self._client(monkeypatch, captured)

        akv.encrypt("secret")

        assert "/wrapkey" in captured[0]
        assert "/encrypt" not in captured[0]

    def test_unwrapping_hits_the_unwrapkey_endpoint(self, monkeypatch):
        captured = []
        akv = self._client(monkeypatch, captured)

        akv.decrypt("d3JhcHBlZA")

        assert "/unwrapkey" in captured[0]
        assert "/decrypt" not in captured[0]
