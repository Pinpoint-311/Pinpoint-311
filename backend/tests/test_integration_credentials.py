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


async def test_store_refuses_a_caller_supplied_reference(monkeypatch):
    """References are minted by this module when it vaults a value -- never
    accepted from a caller. A stored reference is a pointer resolve_credentials
    follows and the disconnect path deletes, so accepting one from an admin is
    accepting "read (and later destroy) any vault entry I can name":
    @secret:GCP_SERVICE_ACCOUNT_JSON aimed at an attacker-controlled base_url
    exfiltrates the platform key, and Disconnect then deletes it -- around the
    reject_platform_key_writes gate, because this path talks to the vault
    directly."""
    async def _boom(name, value):  # must never be reached
        raise AssertionError("set_secret must not be called for a reference")

    monkeypatch.setattr(sm, "set_secret", _boom)
    monkeypatch.setattr(sm, "clear_cache", lambda: None)

    with pytest.raises(ValueError) as caught:
        await creds_mod.store_credentials(
            "sdl", {"api_key": "@secret:GCP_SERVICE_ACCOUNT_JSON"})
    # Names the field so the error is actionable; never echoes the target name.
    assert "api_key" in str(caught.value)
    assert "GCP_SERVICE_ACCOUNT_JSON" not in str(caught.value)
    # Even a reference in this module's own namespace is refused -- the module
    # re-mints it on a genuine save, so there is no honest reason to send one.
    with pytest.raises(ValueError):
        await creds_mod.store_credentials(
            "sdl", {"api_key": creds_mod.make_reference("INTEGRATION_SDL_API_KEY")})


async def test_the_no_vault_fallback_also_refuses_references(monkeypatch):
    """The import-failure path used to pass references through raw, which is
    the same injection with the vault switched off."""
    import builtins

    real_import = builtins.__import__

    def _no_sm(name, *args, **kwargs):
        if name == "app.services.secret_manager":
            raise ImportError("no vault here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_sm)
    with pytest.raises(ValueError):
        await creds_mod.store_credentials(
            "sdl", {"api_key": "@secret:GCP_SERVICE_ACCOUNT_JSON"})


def test_disconnect_only_owns_the_names_it_would_have_minted():
    """The disconnect cleanup deletes what owned_secret_names returns, so this
    is the second half of the injection fix: even if a foreign reference is
    already sitting on a row (written before the store-side rejection), the
    delete must not follow the pointer."""
    names = creds_mod.owned_secret_names("accela", {
        "client_secret": creds_mod.make_reference("INTEGRATION_ACCELA_CLIENT_SECRET"),
        # A pointer at the platform key: never ours to delete.
        "api_key": "@secret:GCP_SERVICE_ACCOUNT_JSON",
        # Another integration's entry, smuggled under the wrong field.
        "password": creds_mod.make_reference("INTEGRATION_TYLER_API_KEY"),
        # Raw fallback value, not a reference at all.
        "username": "clerk@town.gov",
    })
    assert names == {"INTEGRATION_ACCELA_CLIENT_SECRET"}


async def test_forget_vault_secrets_never_deletes_outside_the_namespace(monkeypatch):
    """End to end through the API helper: only this integration's own vault
    entries are deleted on disconnect, whatever the row's references claim."""
    pytest.importorskip("fastapi")
    from app.api import integrations as api_mod

    deleted = []

    async def _delete(name):
        deleted.append(name)
        return True

    monkeypatch.setattr(sm, "delete_secret", _delete)
    monkeypatch.setattr(sm, "clear_cache", lambda **kw: None)

    await api_mod._forget_vault_secrets("accela", {
        "client_secret": creds_mod.make_reference("INTEGRATION_ACCELA_CLIENT_SECRET"),
        "api_key": "@secret:GCP_SERVICE_ACCOUNT_JSON",
    })
    assert deleted == ["INTEGRATION_ACCELA_CLIENT_SECRET"]


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


async def test_resolve_refuses_to_pretend_an_unreadable_vault_is_a_blank_field(monkeypatch):
    """An unresolvable reference used to be silently omitted.

    The connector then reported "credentials missing", which the admin API
    translates for a clerk as "Some required fields are still blank — go back one
    step and fill them in". The fields are not blank; the vault is unreachable.
    Following that instruction retypes credentials over working `@secret:`
    references, so an outage that would have cleared on its own becomes
    permanent loss of the reference.

    So this raises, and the exception names the fields without carrying a value.
    """
    async def _missing(name):
        return None

    monkeypatch.setattr(sm, "get_secret", _missing)

    with pytest.raises(creds_mod.CredentialsUnavailable) as caught:
        await creds_mod.resolve_credentials({
            "api_key": creds_mod.make_reference("INTEGRATION_GHOST_API_KEY"),
            "base_url_token": "kept",
        })
    assert caught.value.fields == ["api_key"]
    assert "Secret Manager" in str(caught.value)
    # Never the literal "@secret:..." string, and never a value.
    assert "@secret:" not in str(caught.value)


async def test_the_unreadable_vault_message_does_not_tell_anyone_to_retype(monkeypatch):
    """The friendly translation has to branch before the "fields are blank" one,
    or the fix above changes nothing that a clerk can see."""
    pytest.importorskip("fastapi")
    from app.api.integrations import _friendly_test_error

    advice = _friendly_test_error(str(creds_mod.CredentialsUnavailable(["api_key"])))
    assert "nothing here needs re-entering" in advice.lower()
    assert "fill them in" not in advice.lower()


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
