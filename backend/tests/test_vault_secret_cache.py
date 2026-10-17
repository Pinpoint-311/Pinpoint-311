"""Azure Key Vault / AWS Secrets Manager reads are cached per key.

They were not: every get_secret was a live HTTPS call made synchronously on the
event loop. Live, on a town that picked Azure Key Vault, that held DB sessions
until the pool ran out and pages took 20-30 s.
"""
import asyncio

import pytest

sm = pytest.importorskip("app.services.secret_manager")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def vault(monkeypatch):
    from app.core import azure_keyvault

    store = {"SMTP_HOST": "smtp.example.org"}
    calls = {"get": 0}
    state = {"fail": False}

    def get_secret(name):
        calls["get"] += 1
        if state["fail"]:
            raise RuntimeError("vault unreachable")
        return store.get(name)

    def set_secret(name, value):
        store[name] = value
        return True

    def delete_secret(name):
        return store.pop(name, None) is not None

    async def from_db(key):
        return None

    monkeypatch.setattr(sm, "_secrets_provider", lambda: "azure")
    monkeypatch.setattr(sm, "_get_secret_from_db", from_db)
    monkeypatch.setattr(azure_keyvault, "is_configured", lambda: True)
    monkeypatch.setattr(azure_keyvault, "get_secret", get_secret)
    monkeypatch.setattr(azure_keyvault, "set_secret", set_secret)
    monkeypatch.setattr(azure_keyvault, "delete_secret", delete_secret)
    sm.clear_cache()
    yield store, calls, state
    sm.clear_cache()


def test_a_second_read_does_not_go_back_to_the_vault(vault):
    _, calls, _ = vault
    assert _run(sm.get_secret("SMTP_HOST")) == "smtp.example.org"
    assert _run(sm.get_secret("SMTP_HOST")) == "smtp.example.org"
    assert calls["get"] == 1


def test_a_key_the_vault_does_not_have_is_remembered_too(vault):
    _, calls, _ = vault
    assert _run(sm.get_secret("NOT_SET")) is None
    assert _run(sm.get_secret("NOT_SET")) is None
    assert calls["get"] == 1


def test_a_write_is_seen_by_the_next_read(vault):
    _run(sm.get_secret("SMTP_HOST"))
    assert sm.set_secret_sync("SMTP_HOST", "smtp.new.org") is True
    assert _run(sm.get_secret("SMTP_HOST")) == "smtp.new.org"


def test_a_delete_is_seen_by_the_next_read(vault):
    _run(sm.get_secret("SMTP_HOST"))
    sm.delete_secret_sync("SMTP_HOST")
    assert _run(sm.get_secret("SMTP_HOST")) is None


def test_clear_cache_for_a_key_forgets_its_vault_value(vault):
    store, calls, _ = vault
    _run(sm.get_secret("SMTP_HOST"))
    store["SMTP_HOST"] = "rotated.example.org"
    sm.clear_cache(key_name="SMTP_HOST")
    assert _run(sm.get_secret("SMTP_HOST")) == "rotated.example.org"
    assert calls["get"] == 2


def test_a_failed_read_is_not_cached(vault):
    _, calls, state = vault
    state["fail"] = True
    assert _run(sm.get_secret("SMTP_HOST")) is None
    state["fail"] = False
    assert _run(sm.get_secret("SMTP_HOST")) == "smtp.example.org", \
        "a vault blip must not hide the key for the whole TTL"


def test_a_vault_that_could_not_be_asked_is_not_cached_as_not_set(vault, monkeypatch):
    """Live: one failed Key Vault token request made the AI key read as absent
    for the cache's whole lifetime, and new reports skipped AI analysis."""
    from app.core import azure_keyvault
    store, calls, _ = vault
    monkeypatch.setattr(azure_keyvault, "get_secret",
                        lambda name: (_ for _ in ()).throw(RuntimeError("no Key Vault access token")))
    assert _run(sm.get_secret("SMTP_HOST")) is None
    monkeypatch.setattr(azure_keyvault, "get_secret", lambda name: store.get(name))
    assert _run(sm.get_secret("SMTP_HOST")) == "smtp.example.org"


def test_the_azure_reader_raises_instead_of_answering_not_set(monkeypatch):
    from app.core import azure_keyvault
    monkeypatch.setattr(azure_keyvault, "_get_token", lambda: None)
    with pytest.raises(RuntimeError):
        azure_keyvault.get_secret("SMTP_HOST")
