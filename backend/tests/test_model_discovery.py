"""Live AI model discovery: merge logic, staleness, and per-provider dispatch.

The provider calls are stubbed (no live cloud), so we exercise the real merge,
staleness, and parsing/dispatch logic that keeps the model picker current.
"""
import importlib

import pytest

md = importlib.import_module("app.services.ai.model_discovery")


# ------------------------------- merge + staleness ---------------------------

def test_merge_keeps_curated_labels_and_appends_new():
    live = [
        {"id": "gemini-3.1-flash-lite", "label": "raw"},   # known → curated label wins
        {"id": "gemini-4.0-pro", "label": "Gemini 4.0 Pro"},  # new → appended
    ]
    merged = md.merge_models("vertex", live)
    ids = [m["id"] for m in merged]
    assert "gemini-4.0-pro" in ids
    # curated label preserved for the known id (not the raw "raw")
    known = next(m for m in merged if m["id"] == "gemini-3.1-flash-lite")
    assert "recommended" in known["label"].lower()
    # newly discovered flagged
    new = next(m for m in merged if m["id"] == "gemini-4.0-pro")
    assert new.get("discovered") is True


def test_merge_none_falls_back_to_curated():
    merged = md.merge_models("vertex", None)
    assert merged == md._curated("vertex")
    assert merged, "curated list should be non-empty"


def test_model_availability_staleness():
    models = [{"id": "a"}, {"id": "b"}]
    assert md.model_is_available(models, "a") is True
    assert md.model_is_available(models, "zzz-retired") is False
    # nothing pinned → treated as available (no false alarm)
    assert md.model_is_available(models, None) is True


# ------------------------------- provider dispatch ---------------------------

async def test_discover_unknown_provider_is_none():
    assert await md.discover_models("nope", {}) is None


async def test_discover_returns_none_on_error(monkeypatch):
    async def _boom(creds):
        raise RuntimeError("network down")
    monkeypatch.setitem(md._DISCOVERERS, "vertex", _boom)
    # discover_models swallows the error and returns None (→ curated fallback)
    assert await md.discover_models("vertex", {"VERTEX_AI_PROJECT": "p"}) is None


async def test_azure_discovery_parses_deployments(monkeypatch):
    import httpx

    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"data": [
                {"id": "gpt-4o-triage", "model": "gpt-4o"},
                {"id": "embed", "model": "text-embedding-3-large"},
            ]}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            assert "deployments" in url and headers.get("api-key") == "k"
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    models = await md.discover_models("azure", {
        "AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.us",
        "AZURE_OPENAI_API_KEY": "k",
    })
    ids = [m["id"] for m in models]
    assert "gpt-4o-triage" in ids  # deployment id is the addressable model
    # label carries the underlying model name
    assert any("gpt-4o" in m["label"] for m in models)


async def test_azure_discovery_needs_credentials():
    assert await md.discover_models("azure", {"AZURE_OPENAI_ENDPOINT": "https://x"}) is None


async def test_get_models_reports_source(monkeypatch):
    async def _fake(provider, creds):
        return [{"id": "gemini-9-flash", "label": "Gemini 9 Flash"}]
    monkeypatch.setattr(md, "discover_models", _fake)
    md._CACHE.clear()
    out = await md.get_models("vertex", {"VERTEX_AI_PROJECT": "p"}, force=True)
    assert out["source"] == "live"
    assert any(m["id"] == "gemini-9-flash" for m in out["models"])
    md._CACHE.clear()
