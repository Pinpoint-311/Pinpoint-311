"""Secret Manager–of–record credential handling for govtech integrations.

Exercises the real store/resolve dispatch in app/integrations/credentials.py
with a stubbed Secret Manager so we prove:
  * with a vault, raw secrets are written there and the row keeps only
    @secret: references (no raw value persisted);
  * without a vault, values fall back to raw (encrypted-in-DB) so the platform
    still works standalone;
  * references resolve back to live values at connector-build time;
  * an unresolved reference is omitted, not passed through as a bogus token.
"""
import importlib

import pytest


creds_mod = importlib.import_module("app.integrations.credentials")
sm = importlib.import_module("app.services.secret_manager")


def test_secret_key_for_and_reference_helpers():
    assert creds_mod.secret_key_for("accela", "client_secret") == "INTEGRATION_ACCELA_CLIENT_SECRET"
    ref = creds_mod.make_reference("INTEGRATION_ACCELA_CLIENT_SECRET")
    assert creds_mod.is_reference(ref)
    assert not creds_mod.is_reference("a-real-value")
    assert creds_mod.reference_name(ref) == "INTEGRATION_ACCELA_CLIENT_SECRET"


async def test_store_writes_to_vault_and_keeps_only_references(monkeypatch):
    """When an external vault accepts the write, the row stores references and
    the raw secret never appears in what we persist."""
    written = {}

    async def _fake_set_secret(name, value):
        written[name] = value
        return True  # vault of record accepted it

    monkeypatch.setattr(sm, "set_secret", _fake_set_secret)
    monkeypatch.setattr(sm, "clear_cache", lambda: None)

    stored = await creds_mod.store_credentials("accela", {
        "client_id": "public-id",
        "client_secret": "s3cr3t",
        "password": "hunter2",
    })

    # Every field became a reference — no raw secret persisted on the row.
    for field, val in stored.items():
        assert creds_mod.is_reference(val), f"{field} should be a reference, got {val!r}"
    assert "s3cr3t" not in stored.values()
    assert "hunter2" not in stored.values()
    # The raw values were written to the vault under the namespaced keys.
    assert written["INTEGRATION_ACCELA_CLIENT_SECRET"] == "s3cr3t"
    assert written["INTEGRATION_ACCELA_PASSWORD"] == "hunter2"


async def test_store_falls_back_to_raw_when_no_vault(monkeypatch):
    """No external vault (set_secret returns False) → keep raw values so the
    model's encrypted-DB column still holds them and nothing is lost."""
    async def _no_vault(name, value):
        return False

    monkeypatch.setattr(sm, "set_secret", _no_vault)
    monkeypatch.setattr(sm, "clear_cache", lambda: None)

    stored = await creds_mod.store_credentials("cityworks", {"api_key": "raw-token"})
    assert stored == {"api_key": "raw-token"}
    assert not creds_mod.is_reference(stored["api_key"])


async def test_store_passes_through_existing_reference(monkeypatch):
    async def _boom(name, value):  # should not be called for an existing ref
        raise AssertionError("set_secret must not be called for a reference")

    monkeypatch.setattr(sm, "set_secret", _boom)
    monkeypatch.setattr(sm, "clear_cache", lambda: None)

    ref = creds_mod.make_reference("INTEGRATION_SDL_API_KEY")
    stored = await creds_mod.store_credentials("sdl", {"api_key": ref})
    assert stored == {"api_key": ref}


async def test_resolve_references_to_live_values(monkeypatch):
    vault = {"INTEGRATION_ACCELA_CLIENT_SECRET": "s3cr3t"}

    async def _fake_get_secret(name):
        return vault.get(name)

    monkeypatch.setattr(sm, "get_secret", _fake_get_secret)

    resolved = await creds_mod.resolve_credentials({
        "client_id": "public-id",  # plain, passes through
        "client_secret": creds_mod.make_reference("INTEGRATION_ACCELA_CLIENT_SECRET"),
    })
    assert resolved == {"client_id": "public-id", "client_secret": "s3cr3t"}


async def test_resolve_omits_unresolvable_reference(monkeypatch):
    async def _missing(name):
        return None

    monkeypatch.setattr(sm, "get_secret", _missing)

    resolved = await creds_mod.resolve_credentials({
        "api_key": creds_mod.make_reference("INTEGRATION_GHOST_API_KEY"),
        "base_url_token": "kept",
    })
    # The dangling reference is dropped so the connector sees a missing key,
    # never the literal "@secret:..." string.
    assert "api_key" not in resolved
    assert resolved == {"base_url_token": "kept"}


async def test_store_then_resolve_roundtrip(monkeypatch):
    vault = {}

    async def _set(name, value):
        vault[name] = value
        return True

    async def _get(name):
        return vault.get(name)

    monkeypatch.setattr(sm, "set_secret", _set)
    monkeypatch.setattr(sm, "get_secret", _get)
    monkeypatch.setattr(sm, "clear_cache", lambda: None)

    stored = await creds_mod.store_credentials("tyler", {"api_key": "live-key"})
    assert creds_mod.is_reference(stored["api_key"])
    resolved = await creds_mod.resolve_credentials(stored)
    assert resolved == {"api_key": "live-key"}
