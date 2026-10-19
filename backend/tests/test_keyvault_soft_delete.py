"""A secret name that was deleted can be written again.

Key Vault soft-delete is on by default: a deleted secret keeps its name for the
retention period and a PUT to it answers 409 ObjectIsDeletedButRecoverable. The
secret-store self-test deletes its probe key every run, so live, every test
after the first said "Azure Key Vault ... would not accept a test write".
"""
import pytest

pytest.importorskip("httpx")
from app.core import azure_keyvault as kv  # noqa: E402


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeVault:
    """live / deleting / deleted states, as Azure reports them."""

    def __init__(self, deleting_polls=0):
        self.state = {}
        self.deleting_polls = deleting_polls
        self.recovered = 0

    def _name(self, url):
        return url.split("?")[0].rstrip("/").split("/")[-1]

    def put(self, url, **_):
        name = self._name(url)
        st = self.state.get(name)
        if st == "deleting":
            return _Resp(409, {"error": {"code": "Conflict",
                                         "innererror": {"code": "ObjectIsBeingDeleted"}}})
        if st == "deleted":
            return _Resp(409, {"error": {"code": "Conflict",
                                         "innererror": {"code": "ObjectIsDeletedButRecoverable"}}})
        self.state[name] = "live"
        return _Resp(200)

    def get(self, url, **_):
        parts = url.split("?")[0].split("/")
        name = parts[-1]
        st = self.state.get(name)
        if "deletedsecrets" in parts:
            if st == "deleting":
                self.deleting_polls -= 1
                if self.deleting_polls <= 0:
                    self.state[name] = "deleted"
                return _Resp(404)
            return _Resp(200 if st == "deleted" else 404)
        return _Resp(200, {"value": "v"}) if st == "live" else _Resp(404)

    def post(self, url, **_):
        name = url.split("?")[0].split("/")[-2]
        if self.state.get(name) != "deleted":
            return _Resp(409)
        self.state[name] = "live"
        self.recovered += 1
        return _Resp(200)


@pytest.fixture
def vault(monkeypatch):
    fake = _FakeVault()
    monkeypatch.setattr(kv, "_get_token", lambda: "t")
    monkeypatch.setattr(kv, "_vault_url", lambda: "https://v.vault.azure.net")
    monkeypatch.setattr(kv, "_api_version", lambda: "7.4")
    monkeypatch.setattr(kv.httpx, "put", fake.put)
    monkeypatch.setattr(kv.httpx, "get", fake.get)
    monkeypatch.setattr(kv.httpx, "post", fake.post)
    monkeypatch.setattr(kv.time, "sleep", lambda s: None)
    return fake


def test_a_deleted_name_is_recovered_and_written(vault):
    vault.state["pinpoint-selftest-write-check"] = "deleted"
    assert kv.set_secret("PINPOINT_SELFTEST_WRITE_CHECK", "x") is True
    assert vault.recovered == 1
    assert vault.state["pinpoint-selftest-write-check"] == "live"


def test_a_name_still_being_deleted_is_waited_for(vault):
    vault.state["smtp-password"] = "deleting"
    vault.deleting_polls = 2
    assert kv.set_secret("SMTP_PASSWORD", "x") is True
    assert vault.recovered == 1


def test_a_fresh_name_is_written_without_recovery(vault):
    assert kv.set_secret("SMTP_HOST", "x") is True
    assert vault.recovered == 0
