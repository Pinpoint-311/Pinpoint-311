"""The configurable REST connector, driven against a fake vendor API.

It had no tests at all. These cover the round trip a town actually depends on:
the create body and its auth, the status update, the poll with pagination, and
reading one record back -- with the defaults and with a vendor that differs.
"""

import json
from datetime import datetime, timezone

import httpx
import pytest

import app.integrations.base as base
from app.integrations.base import ConnectorError
from app.integrations.registry import build_connector

BASE = "https://api.vendor.test/v1"

PAYLOAD = {
    "service_request_id": "REQ-7",
    "service_code": "PTH",
    "service_name": "Pothole",
    "description": "Deep pothole",
    "address": "12 Main St",
    "lat": 40.73,
    "long": -74.17,
    "status": "open",
    "media_urls": [],
}


@pytest.fixture
def vendor(monkeypatch):
    monkeypatch.setattr(base, "_assert_public_url", lambda url: None)

    def serve(routes):
        seen = []

        async def handle(_transport, request):
            await request.aread()
            seen.append(request)
            key = f"{request.method} {request.url.path}"
            for route, responder in routes.items():
                if key == route:
                    return responder(request)
            return httpx.Response(404, json={"error": "not found"}, request=request)

        monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", handle)
        return seen

    return serve


def ok(body, status=200):
    return lambda request: httpx.Response(status, json=body, request=request)


def generic(config=None, credentials=None):
    return build_connector("generic_rest", {"base_url": BASE, **(config or {})},
                           {"api_key": "k-123", **(credentials or {})})


@pytest.mark.asyncio
async def test_push_posts_the_mapped_body_with_bearer_auth(vendor):
    seen = vendor({"POST /v1/requests": ok({"id": "V-1", "status": "new"}, 201)})
    record = await generic().push_request(PAYLOAD)
    assert record.external_id == "V-1"
    assert record.status == "open"
    request = seen[-1]
    assert request.headers["authorization"] == "Bearer k-123"
    body = json.loads(request.content)
    assert body["external_reference"] == "REQ-7"
    assert body["category_code"] == "PTH"
    assert body["description"] == "Deep pothole"
    assert body["latitude"] == 40.73 and body["longitude"] == -74.17


@pytest.mark.asyncio
async def test_push_uses_the_vendor_category_code_and_custom_field_names(vendor):
    seen = vendor({"POST /v1/tickets": ok({"ticketId": 55})})
    conn = generic({
        "create_path": "/tickets", "id_field": "ticketId",
        "field_map": {"service_code": "TypeCode", "description": "Notes"},
        "service_code_map_out": {"PTH": "ROAD-01"},
        "auth_style": "api_key_header", "auth_header": "X-Token",
    })
    record = await conn.push_request(PAYLOAD)
    assert record.external_id == "55"
    body = json.loads(seen[-1].content)
    assert body["TypeCode"] == "ROAD-01"
    assert body["Notes"] == "Deep pothole"
    assert seen[-1].headers["x-token"] == "k-123"


@pytest.mark.asyncio
async def test_a_create_without_an_id_is_a_failure(vendor):
    vendor({"POST /v1/requests": ok({"message": "queued"})})
    with pytest.raises(ConnectorError, match="had no 'id' field"):
        await generic().push_request(PAYLOAD)


@pytest.mark.asyncio
async def test_status_push_sends_the_mapped_word(vendor):
    seen = vendor({"PUT /v1/requests/V-1/status": ok({})})
    await generic({"status_map_out": {"in_progress": "WORKING"}}).push_status("V-1", "in_progress", "Crew out")
    assert json.loads(seen[-1].content) == {"status": "WORKING", "notes": "Crew out"}


@pytest.mark.asyncio
async def test_pull_follows_pagination_and_dedupes(vendor):
    pages = {
        None: {"results": [{"id": "1", "status": "assigned", "updated_at": "2026-08-01T10:00:00Z"},
                           {"id": "2", "status": "closed"}],
               "next": f"{BASE}/requests?page=2"},
        "2": {"results": [{"id": "2", "status": "closed"}, {"id": "3", "status": "open"}]},
    }

    def answer(request):
        return httpx.Response(200, json=pages[dict(request.url.params).get("page")], request=request)

    seen = vendor({"GET /v1/requests": answer})
    since = datetime(2026, 8, 1, tzinfo=timezone.utc)
    records = await generic().pull_updates(since=since)
    assert [r.external_id for r in records] == ["1", "2", "3"]
    assert [r.status for r in records] == ["in_progress", "closed", "open"]
    assert dict(seen[0].url.params)["updated_since"] == since.isoformat()
    assert records[0].updated_at == datetime(2026, 8, 1, 10, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_query_auth_rides_on_every_page(vendor):
    seen = vendor({"GET /v1/requests": ok([{"id": "1", "status": "open"}])})
    await generic({"auth_style": "query"}).pull_updates()
    assert dict(seen[0].url.params)["api_key"] == "k-123"
    assert "authorization" not in seen[0].headers


@pytest.mark.asyncio
async def test_fetch_record_reads_one_and_404_is_absence(vendor):
    vendor({"GET /v1/requests/V-1": ok({"id": "V-1", "status": "resolved"})})
    record = await generic().fetch_record("V-1")
    assert record.external_id == "V-1" and record.status == "closed"
    assert await generic().fetch_record("missing") is None


@pytest.mark.asyncio
async def test_the_check_says_when_no_credential_was_sent(vendor):
    vendor({"GET /v1/requests": ok([])})
    result = await build_connector("generic_rest", {"base_url": BASE}, {}).test_connection()
    assert result["ok"] is True and result["verified"] is False
    result = await generic().test_connection()
    assert result["verified"] is True
