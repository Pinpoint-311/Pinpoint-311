"""Secret manager: TTL cache expiry and no-clobber bundle merge."""
import json
import os
import sys
import types

# Stub DB / tracking / sanitize so the merge path needs no real database.
_san = types.ModuleType("app.core.sanitize"); _san.sanitize_for_log = lambda s: s
sys.modules.setdefault("app.core.sanitize", _san)


class _Sess:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


_dbs = types.ModuleType("app.db.session"); _dbs.SessionLocal = _Sess; _dbs.sync_engine = None
sys.modules.setdefault("app.db.session", _dbs)
_au = types.ModuleType("app.services.api_usage")
async def _track(*a, **k): return None
_au.track_api_usage = _track
sys.modules.setdefault("app.services.api_usage", _au)

import app.services.secret_manager as sm  # noqa: E402


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
