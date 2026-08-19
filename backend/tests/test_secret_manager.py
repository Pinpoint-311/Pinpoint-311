"""Secret manager: TTL cache expiry and no-clobber bundle merge.

The stubs below used to be written straight into `sys.modules` at import time
and never taken out again. That is a process-global edit made by whichever test
module collects first, and it does not stay inside this file: a later module
importing `app.main` got this file's one-attribute fake of
`app.services.api_usage` instead of the real module and died at collection with
`ImportError: cannot import name 'get_usage_summary'`. A collection error
aborts the run, so `pytest tests` executed *zero* tests -- and the failure
looked like a bug in `app.main`.

So the fakes live in a fixture now. `secret_manager` imports all three of these
lazily, inside the functions that use them, so they only have to exist while a
test is running -- and `monkeypatch.setitem` restores `sys.modules` exactly as
it found it, including deleting a key that was not there before.
"""
import json
import os
import sys
import types

import pytest

import app.services.secret_manager as sm  # noqa: E402


def _stub_modules() -> dict:
    """Stub DB / tracking / sanitize so the merge path needs no real database."""
    san = types.ModuleType("app.core.sanitize")
    san.sanitize_for_log = lambda s: s

    class _Sess:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    dbs = types.ModuleType("app.db.session")
    dbs.SessionLocal = _Sess
    dbs.sync_engine = None

    au = types.ModuleType("app.services.api_usage")

    async def _track(*a, **k):
        return None

    au.track_api_usage = _track

    return {
        "app.core.sanitize": san,
        "app.db.session": dbs,
        "app.services.api_usage": au,
    }


@pytest.fixture(autouse=True)
def _isolated_stubs(monkeypatch):
    """Fakes for the duration of one test, and only where the real module is
    not already imported -- the old code used `setdefault` for that reason."""
    for name, fake in _stub_modules().items():
        if name not in sys.modules:
            monkeypatch.setitem(sys.modules, name, fake)
    yield


class FakeSM:
    def __init__(self): self.data = {}
    def access_secret_version(self, request):
        sid = request["name"].split("/secrets/")[1].split("/")[0]
        payload = self.data.get(sid)
        if payload is None:
            raise Exception("no version")
        return types.SimpleNamespace(payload=types.SimpleNamespace(data=payload))
    def get_secret(self, request):
        sid = request["name"].split("/secrets/")[1]
        if sid in self.data:
            return object()
        raise Exception("not found")
    def create_secret(self, request): self.data[request["secret_id"]] = None
    def add_secret_version(self, request):
        sid = request["parent"].split("/secrets/")[1]
        self.data[sid] = request["payload"]["data"]


def test_cache_ttl():
    os.environ["SECRET_CACHE_TTL_SECONDS"] = "100"
    sm._cache_put("secret-config", {"A": "1"})
    assert sm._cache_get("secret-config") == {"A": "1"}
    os.environ["SECRET_CACHE_TTL_SECONDS"] = "0"
    sm._cache_put("secret-config", {"A": "1"})
    assert sm._cache_get("secret-config") is None
    os.environ["SECRET_CACHE_TTL_SECONDS"] = "300"
    sm.clear_cache()


def test_no_clobber_merge(monkeypatch):
    fake = FakeSM()
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-proj")
    sm._config["use_gcp"] = True
    sm._sm_client = fake
    assert sm.set_secret_sync("TOWNSHIP_NAME", "Springfield") is True
    assert sm.set_secret_sync("SUPPORT_EMAIL", "help@town.gov") is True
    final = json.loads(fake.data["secret-config"].decode())
    assert final == {"TOWNSHIP_NAME": "Springfield", "SUPPORT_EMAIL": "help@town.gov"}
    # A stale cache must not cause a lost key on the next write.
    sm._cache_put("secret-config", {"TOWNSHIP_NAME": "STALE"})
    assert sm.set_secret_sync("PRIMARY_COLOR", "#111") is True
    final2 = json.loads(fake.data["secret-config"].decode())
    assert final2.get("SUPPORT_EMAIL") == "help@town.gov"
    assert final2.get("PRIMARY_COLOR") == "#111"
    sm.clear_cache()
