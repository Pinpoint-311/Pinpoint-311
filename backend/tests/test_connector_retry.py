"""RetryTransport: safe, method-aware retries; generic connector pagination."""
import httpx
import pytest

import app.integrations.base as base
from app.integrations.base import RetryTransport
from app.integrations.registry import build_connector


def _fake(script, calls):
    async def fake(self, request):
        i = calls["n"]; calls["n"] += 1
        item = script[min(i, len(script) - 1)]
        if isinstance(item, Exception):
            raise item
        status, headers = item if isinstance(item, tuple) else (item, {})
        return httpx.Response(status, headers=headers, request=request)
    return fake


async def _run(method, script, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", _fake(script, calls))
    t = RetryTransport(max_retries=3, backoff_base=0.001, backoff_cap=0.002)
    req = httpx.Request(method, "https://vendor.test/requests")
    try:
        r = await t.handle_async_request(req)
        return r.status_code, calls["n"], None
    except Exception as e:  # noqa: BLE001
        return None, calls["n"], type(e).__name__


@pytest.mark.asyncio
async def test_get_429_then_200_retries(monkeypatch):
    status, n, _ = await _run("GET", [(429, {"Retry-After": "0"}), 200], monkeypatch)
    assert status == 200 and n == 2


@pytest.mark.asyncio
async def test_get_503_exhausts(monkeypatch):
    status, n, _ = await _run("GET", [503], monkeypatch)
    assert status == 503 and n == 4  # 1 + 3 retries


@pytest.mark.asyncio
async def test_post_500_not_retried(monkeypatch):
    status, n, _ = await _run("POST", [500, 200], monkeypatch)
    assert status == 500 and n == 1


@pytest.mark.asyncio
async def test_post_429_is_retried(monkeypatch):
    status, n, _ = await _run("POST", [(429, {"Retry-After": "0"}), 200], monkeypatch)
    assert status == 200 and n == 2


@pytest.mark.asyncio
async def test_post_read_error_not_retried(monkeypatch):
    err = httpx.ReadError("boom", request=httpx.Request("POST", "https://vendor.test/requests"))
    _, n, exc = await _run("POST", [err, 200], monkeypatch)
    assert exc == "ReadError" and n == 1


def test_retry_after_parsing():
    assert RetryTransport._parse_retry_after("5") == 5.0
    assert RetryTransport._parse_retry_after(None) is None
    assert RetryTransport._parse_retry_after("garbage") is None


@pytest.mark.asyncio
async def test_pagination_follows_next_and_dedupes(monkeypatch):
    monkeypatch.setattr(base, "_assert_public_url", lambda url: None)
    pages = {
        "p1": {"results": [{"id": "1"}, {"id": "2"}], "next": "https://api.test/v1/requests?page=2"},
        "p2": {"results": [{"id": "2"}, {"id": "3"}], "next": None},
    }

    async def paged(self, request):
        key = "p2" if "page=2" in str(request.url) else "p1"
        return httpx.Response(200, json=pages[key], request=request)

    monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", paged)
    conn = build_connector("sdl", {"base_url": "https://api.test/v1"}, {"api_key": "k"})
    recs = await conn.pull_updates()
    assert sorted(r.external_id for r in recs) == ["1", "2", "3"]
