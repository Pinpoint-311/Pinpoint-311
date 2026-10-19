"""The GeoReport v2 client, driven against a server that answers like the spec.

Tyler's citizen-request products are reached through this exact code — the Tyler
connector is `Open311Connector` with a different `platform` string — so these
tests are the only evidence either of them works. Nothing here can call a real
vendor, so the fake server below answers with the shapes GeoReport v2 documents
(http://wiki.open311.org/GeoReport_v2): a JSON array of services, a
form-encoded create whose response is a one-element array carrying
`service_request_id` *or* `token`, and reads that return arrays.

Two spec details drive most of what is asserted:

  * the create is `application/x-www-form-urlencoded`, not JSON, and
    `attribute[code]` fields are sent only for codes the service defines;
  * `api_key` and `jurisdiction_id` are query/form parameters, not headers.

Status changes on records we filed are read with `service_request_id=a,b,c`
(the spec's multi-get, which overrides the date filters); the `start_date`
window is only for discovering new records to import, because it filters on
when a request was filed.
"""

from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest

import app.integrations.base as base
from app.integrations.base import ConnectorError
from app.integrations.registry import PLATFORM_CATALOG, build_connector

BASE = "https://springfield.tylerapp.com/open311/v2"

# A service list as GeoReport v2 defines it: a bare array of service objects.
SERVICES = [
    {"service_code": "001", "service_name": "Pothole", "description": "Road defect",
     "metadata": False, "type": "realtime", "keywords": "road,pothole", "group": "street"},
    {"service_code": "002", "service_name": "Streetlight Out", "description": "",
     "metadata": False, "type": "realtime", "keywords": "light", "group": "street"},
]

PAYLOAD = {
    "service_request_id": "REQ-20260805-a1b2c3d4",
    "service_code": "001",
    "service_name": "Pothole",
    "description": "Deep pothole outside the school",
    "address": "12 Main St",
    "lat": 40.7301,
    "long": -74.1724,
    "status": "open",
    "media_urls": ["https://cdn.example.test/photo1.jpg"],
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.test",
    "phone": "555-0100",
}


class Server:
    """Stands in for a GeoReport v2 endpoint. Routes on path, records requests."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def install(self, monkeypatch):
        monkeypatch.setattr(base, "_assert_public_url", lambda url: None)

        async def handle(_transport, request):
            await request.aread()
            self.requests.append(request)
            for suffix, responder in self.routes.items():
                if request.url.path.endswith(suffix):
                    return responder(request)
            return httpx.Response(404, json=[], request=request)

        monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", handle)
        return self

    @property
    def last(self):
        return self.requests[-1]

    def form(self, index=-1):
        """The form body of a recorded request, as GeoReport v2 sends it."""
        return {k: v[0] for k, v in parse_qs(self.requests[index].content.decode()).items()}

    def query(self, index=-1):
        return {k: v[0] for k, v in parse_qs(self.requests[index].url.query.decode()).items()}


def json_response(body, status=200):
    return lambda request: httpx.Response(status, json=body, request=request)


@pytest.fixture
def server(monkeypatch):
    def make(routes):
        return Server(routes).install(monkeypatch)
    return make


def tyler(config=None, credentials=None):
    return build_connector(
        "tyler",
        {"base_url": BASE, "jurisdiction_id": "springfield.gov", **(config or {})},
        {"api_key": "tyler-key-abc123", **(credentials or {})},
    )


# ---------------------------------------------------------------------------
# Tyler is this client
# ---------------------------------------------------------------------------

def test_tyler_is_the_georeport_client_under_another_name():
    """If this ever stops being true, every assertion below stops covering
    Tyler and nothing would say so."""
    from app.integrations.connectors.open311 import Open311Connector

    connector = tyler()
    assert isinstance(connector, Open311Connector)
    assert connector.platform == "tyler"
    assert PLATFORM_CATALOG["tyler"]["integration_mode"] == "open311"


def test_the_tyler_card_asks_for_what_the_client_actually_needs():
    """The card's fields are the whole contract with the admin: a field the
    client never reads is a question nobody should be asked, and a value the
    client requires but the card omits is a connection that cannot be made."""
    catalog = PLATFORM_CATALOG["tyler"]
    credential_keys = {f["key"] for f in catalog["credential_fields"]}
    config_keys = {f["key"] for f in catalog["config_fields"]}
    assert credential_keys == {"api_key"}, "the client only ever sends an api_key"
    assert "base_url" in config_keys and "jurisdiction_id" in config_keys
    required = {f["key"] for f in catalog["config_fields"] if f.get("required")}
    assert required == {"base_url"}, "base_url is the only thing the client cannot default"


# ---------------------------------------------------------------------------
# Connection check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_check_reads_the_service_list_and_counts_it(server):
    seen = server({"/services.json": json_response(SERVICES)})
    result = await tyler().test_connection()

    assert result["ok"] is True
    assert "2 service type(s)" in result["detail"]
    assert seen.last.method == "GET"
    assert seen.query() == {"api_key": "tyler-key-abc123", "jurisdiction_id": "springfield.gov"}


@pytest.mark.asyncio
async def test_the_check_refuses_to_claim_the_key_was_verified(server):
    """GeoReport v2 has no authenticated read: /services.json answers anybody.
    Reporting `verified` here would be a green tick earned by an anonymous
    request, which is the whole reason this field exists."""
    server({"/services.json": json_response(SERVICES)})
    result = await tyler().test_connection()
    assert result["verified"] is False
    assert "only exercised on the first push" in result["detail"]


@pytest.mark.asyncio
async def test_a_check_against_the_wrong_address_says_what_the_server_said(server):
    server({"/services.json": lambda r: httpx.Response(404, text="No such endpoint", request=r)})
    with pytest.raises(ConnectorError) as caught:
        await tyler().test_connection()
    assert "HTTP 404" in str(caught.value)
    assert "No such endpoint" in str(caught.value)


# ---------------------------------------------------------------------------
# Create — the one call the api_key actually matters on
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_report_is_filed_as_a_form_post_with_the_spec_field_names(server):
    seen = server({"/requests.json": json_response([{"service_request_id": "638344"}])})
    record = await tyler().push_request(PAYLOAD)

    assert record.external_id == "638344"
    request = seen.last
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}/requests.json"
    # The spec is explicit that this is form-encoded, not JSON.
    assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")

    form = seen.form()
    assert form["api_key"] == "tyler-key-abc123"
    assert form["jurisdiction_id"] == "springfield.gov"
    assert form["service_code"] == "001"
    assert form["description"] == "Deep pothole outside the school"
    assert form["lat"] == "40.7301" and form["long"] == "-74.1724"
    assert form["address_string"] == "12 Main St"
    assert form["media_url"] == "https://cdn.example.test/photo1.jpg"
    # The service defines no attributes (metadata=false), so none are sent.
    assert not [k for k in form if k.startswith("attribute[")]


@pytest.mark.asyncio
async def test_contact_details_ride_along_only_when_the_payload_carries_them(server):
    """The payload only contains them when the connection is configured to
    share PII; the client's job is to pass on what it is given, under the
    spec's own field names."""
    seen = server({"/requests.json": json_response([{"service_request_id": "1"}])})
    await tyler().push_request(PAYLOAD)
    form = seen.form()
    assert form["first_name"] == "Ada" and form["last_name"] == "Lovelace"
    assert form["email"] == "ada@example.test" and form["phone"] == "555-0100"

    seen = server({"/requests.json": json_response([{"service_request_id": "2"}])})
    anonymous = {k: v for k, v in PAYLOAD.items()
                 if k not in ("first_name", "last_name", "email", "phone")}
    await tyler().push_request(anonymous)
    assert not {"first_name", "last_name", "email", "phone"} & set(seen.form())


@pytest.mark.asyncio
async def test_a_report_with_no_coordinates_is_filed_by_address(server):
    seen = server({"/requests.json": json_response([{"service_request_id": "3"}])})
    no_coords = {**PAYLOAD, "lat": None, "long": None}
    await tyler().push_request(no_coords)
    form = seen.form()
    assert form["address_string"] == "12 Main St"
    assert "lat" not in form and "long" not in form


@pytest.mark.asyncio
async def test_a_token_is_resolved_to_the_real_id_when_the_server_has_one(server):
    """A batch-mode endpoint returns a token; GET tokens/{token}.json gives the
    real service_request_id. The token itself is never the record id."""
    seen = server({
        "/requests.json": json_response([{"token": "220e17f8-3d3f"}]),
        "/tokens/220e17f8-3d3f.json": json_response(
            [{"service_request_id": "638399", "token": "220e17f8-3d3f"}]),
    })
    record = await tyler().push_request(PAYLOAD)
    assert record.external_id == "638399"
    assert any(r.url.path.endswith("/tokens/220e17f8-3d3f.json") for r in seen.requests)


@pytest.mark.asyncio
async def test_an_unresolved_token_is_kept_as_a_pending_placeholder(server):
    """Until the server assigns an id, the link holds `token:<token>` so the
    pull knows to resolve it rather than poll a record that does not exist."""
    server({
        "/requests.json": json_response([{"token": "220e17f8-3d3f"}]),
        "/tokens/220e17f8-3d3f.json": json_response([{"token": "220e17f8-3d3f"}]),
    })
    record = await tyler().push_request(PAYLOAD)
    assert record.external_id == "token:220e17f8-3d3f"


@pytest.mark.asyncio
async def test_a_pending_token_resolves_on_a_later_pull(server):
    server({"/tokens/abc.json": json_response([{"service_request_id": "77", "token": "abc"}])})
    assert await tyler().resolve_pending_id("token:abc") == "77"
    server({"/tokens/abc.json": json_response([{"token": "abc"}])})
    assert await tyler().resolve_pending_id("token:abc") is None


@pytest.mark.asyncio
async def test_a_create_that_returns_neither_is_a_failure_not_a_silent_success(server):
    server({"/requests.json": json_response([{"service_notice": "Thanks!"}])})
    with pytest.raises(ConnectorError) as caught:
        await tyler().push_request(PAYLOAD)
    assert "no id/token" in str(caught.value)


@pytest.mark.asyncio
async def test_a_mapped_service_code_is_what_gets_sent(server):
    seen = server({"/requests.json": json_response([{"service_request_id": "4"}])})
    await tyler({"service_code_map_out": {"001": "PTH-9"},
                 "default_service_code": "GENERAL"}).push_request(PAYLOAD)
    assert seen.form()["service_code"] == "PTH-9"


@pytest.mark.asyncio
async def test_the_default_service_code_is_only_a_fallback(server):
    """It used to override every request, filing a pothole and a streetlight
    under one code. Now it applies only to a category with no mapping."""
    seen = server({"/requests.json": json_response([{"service_request_id": "4"}])})
    await tyler({"service_code_map_out": {"002": "LIGHT"},
                 "default_service_code": "GENERAL"}).push_request(PAYLOAD)
    assert seen.form()["service_code"] == "GENERAL"


@pytest.mark.asyncio
async def test_the_legacy_service_code_map_key_means_outbound(server):
    seen = server({"/requests.json": json_response([{"service_request_id": "4"}])})
    await tyler({"service_code_map": {"001": "PTH-LEGACY"}}).push_request(PAYLOAD)
    assert seen.form()["service_code"] == "PTH-LEGACY"


@pytest.mark.asyncio
async def test_with_no_mapping_and_no_default_our_own_code_is_sent(server):
    seen = server({"/requests.json": json_response([{"service_request_id": "4"}])})
    await tyler().push_request(PAYLOAD)
    assert seen.form()["service_code"] == "001"


DEFINITION = {
    "service_code": "001",
    "attributes": [
        {"variable": True, "code": "WHERE", "datatype": "string", "required": True,
         "description": "Where on the road?", "order": 1},
        {"variable": True, "code": "external_id", "datatype": "string", "required": False,
         "description": "Your reference", "order": 2},
        {"variable": False, "code": "NOTE", "datatype": "text", "required": False,
         "description": "Informational", "order": 3},
        {"variable": True, "code": "DEPTH", "datatype": "string", "required": True,
         "description": "How deep?", "order": 4},
    ],
}


@pytest.mark.asyncio
async def test_only_attributes_the_service_defines_are_sent(server):
    """attribute[code] for codes in services/{code}.json -- mapped values for
    required ones, our reference only when the service asks for it, nothing
    for informational entries, and a warning for a required one we cannot fill."""
    seen = server({
        "/services/001.json": json_response(DEFINITION),
        "/requests.json": json_response([{"service_request_id": "5"}]),
    })
    connector = tyler({"attribute_map": {"WHERE": "address"}})
    await connector.push_request({**PAYLOAD, "custom_fields": {"unrelated": "x"}})
    form = seen.form()
    assert form["attribute[WHERE]"] == "12 Main St"
    assert form["attribute[external_id]"] == "REQ-20260805-a1b2c3d4"
    assert "attribute[NOTE]" not in form
    assert "attribute[DEPTH]" not in form
    assert "attribute[unrelated]" not in form
    assert any("DEPTH" in w for w in connector.take_warnings())


@pytest.mark.asyncio
async def test_a_custom_answer_with_the_attribute_code_is_sent(server):
    seen = server({
        "/services/001.json": json_response(DEFINITION),
        "/requests.json": json_response([{"service_request_id": "6"}]),
    })
    await tyler().push_request({**PAYLOAD, "custom_fields": {"DEPTH": "4 in", "WHERE": "lane 2"}})
    form = seen.form()
    assert form["attribute[DEPTH]"] == "4 in"
    assert form["attribute[WHERE]"] == "lane 2"


# ---------------------------------------------------------------------------
# Reading back — the other half of a round trip
# ---------------------------------------------------------------------------

REMOTE_RECORD = {
    "service_request_id": "638344",
    "status": "closed",
    "status_notes": "Patched by the road crew.",
    "service_name": "Pothole",
    "service_code": "001",
    "description": "Deep pothole outside the school",
    "requested_datetime": "2026-08-05T10:01:00Z",
    "updated_datetime": "2026-08-07T16:20:00Z",
    "address": "12 MAIN ST, SPRINGFIELD",
    "lat": 40.7301,
    "long": -74.1724,
}


@pytest.mark.asyncio
async def test_the_record_just_filed_can_be_read_straight_back(server):
    seen = server({"/requests/638344.json": json_response([REMOTE_RECORD])})
    record = await tyler().fetch_record("638344")

    assert record.external_id == "638344"
    assert record.raw_status == "closed"
    assert record.status == "closed"
    assert record.status_notes == "Patched by the road crew."
    assert record.address == "12 MAIN ST, SPRINGFIELD"
    assert record.lat == 40.7301 and record.long == -74.1724
    assert record.updated_at == datetime(2026, 8, 7, 16, 20, tzinfo=timezone.utc)
    assert seen.query()["api_key"] == "tyler-key-abc123"


@pytest.mark.asyncio
async def test_a_record_the_vendor_does_not_have_is_absence_not_an_error(server):
    """404 has to come back as None. Raising would write an error to the sync
    log every fifteen minutes for a record somebody deleted at the vendor."""
    server({"/requests/nope.json": lambda r: httpx.Response(404, text="", request=r)})
    assert await tyler().fetch_record("nope") is None


@pytest.mark.asyncio
async def test_a_vendor_side_status_change_comes_back_on_the_poll(server):
    seen = server({"/requests.json": json_response([
        REMOTE_RECORD,
        {**REMOTE_RECORD, "service_request_id": "638345", "status": "open",
         "updated_datetime": "2026-08-07T17:00:00Z"},
    ])})
    since = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    records = await tyler().pull_updates(since=since)

    assert [r.external_id for r in records] == ["638344", "638345"]
    assert [r.status for r in records] == ["closed", "open"]
    query = seen.query()
    # Both window parameters: `start_date` is in the base spec, `updated_after`
    # is the widespread extension, and which one a given server honours is not
    # something this code can know.
    assert query["start_date"] == since.isoformat()
    assert query["updated_after"] == since.isoformat()
    assert query["jurisdiction_id"] == "springfield.gov"


@pytest.mark.asyncio
async def test_the_import_window_never_spans_more_than_ninety_days(server):
    seen = server({"/requests.json": json_response([])})
    await tyler().pull_updates(since=datetime(2020, 1, 1, tzinfo=timezone.utc))
    sent = datetime.fromisoformat(seen.query()["start_date"])
    assert (datetime.now(timezone.utc) - sent).days <= 90


@pytest.mark.asyncio
async def test_linked_records_are_polled_by_id_in_batches(server):
    """Status changes on older requests are outside any start_date window, so
    they are read with service_request_id=a,b,c -- which the spec says
    overrides every other filter."""
    def answer(request):
        ids = dict(request.url.params)["service_request_id"].split(",")
        return httpx.Response(200, json=[
            {**REMOTE_RECORD, "service_request_id": i} for i in ids], request=request)

    seen = server({"/requests.json": answer})
    ids = [str(n) for n in range(120)] + ["token:pending"]
    records = await tyler().pull_linked(ids)
    assert len(records) == 120
    assert len(seen.requests) == 3, "batches of 50"
    first = seen.query(0)
    assert "start_date" not in first and "updated_after" not in first
    assert first["api_key"] == "tyler-key-abc123"
    assert all("token:" not in dict(r.url.params)["service_request_id"] for r in seen.requests)


def test_open311_polls_linked_records_rather_than_a_change_feed():
    assert "pull_linked" in tyler().capabilities


@pytest.mark.asyncio
async def test_a_first_ever_poll_asks_for_no_window_at_all(server):
    seen = server({"/requests.json": json_response([])})
    await tyler().pull_updates(since=None)
    assert "start_date" not in seen.query() and "updated_after" not in seen.query()


@pytest.mark.asyncio
async def test_a_record_with_no_id_is_skipped_rather_than_linked_to_nothing(server):
    server({"/requests.json": json_response([REMOTE_RECORD, {"status": "open"}])})
    records = await tyler().pull_updates()
    assert [r.external_id for r in records] == ["638344"]


@pytest.mark.asyncio
async def test_a_town_specific_status_word_can_be_mapped(server):
    """Open311 says open/closed; real endpoints emit their own vocabulary, and
    the connection's status_map_in is where a town reconciles the two."""
    server({"/requests.json": json_response([{**REMOTE_RECORD, "status": "dispatched"}])})
    connector = tyler({"status_map_in": {"dispatched": "in_progress"}})
    record = (await connector.pull_updates())[0]
    assert record.raw_status == "dispatched"
    assert record.status == "in_progress"


# ---------------------------------------------------------------------------
# Failure, reported usefully and without the key in it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_rejected_key_is_reported_with_the_servers_own_words(server):
    server({"/requests.json": lambda r: httpx.Response(
        403, json=[{"code": 403, "description": "Invalid api_key received"}], request=r)})
    with pytest.raises(ConnectorError) as caught:
        await tyler().push_request(PAYLOAD)
    message = str(caught.value)
    assert "HTTP 403" in message
    assert "Invalid api_key received" in message


@pytest.mark.asyncio
async def test_an_error_body_that_echoes_the_key_back_is_redacted(server):
    """Servers echo the request in 4xx bodies, and this string is written to
    the sync log and rendered in the admin UI."""
    server({"/requests.json": lambda r: httpx.Response(
        400, text='rejected: api_key=tyler-key-abc123 service_code=001', request=r)})
    with pytest.raises(ConnectorError) as caught:
        await tyler().push_request(PAYLOAD)
    message = str(caught.value)
    assert "tyler-key-abc123" not in message
    assert "[REDACTED]" in message
    assert "service_code=001" in message, "redaction should not eat the useful part"


@pytest.mark.asyncio
async def test_a_server_error_is_retried_and_then_surfaces(server, monkeypatch):
    """A read is idempotent, so the transport rides out a 503 — but a server
    that stays down has to end as a reported failure, not an empty list that
    looks like "no changes"."""
    monkeypatch.setattr(base.RetryTransport, "_backoff",
                        lambda self, attempt, retry_after: _noop())
    server({"/requests.json": lambda r: httpx.Response(503, text="upstream down", request=r)})
    connector = tyler({"max_retries": 2})
    with pytest.raises(ConnectorError) as caught:
        await connector.pull_updates()
    assert "HTTP 503" in str(caught.value)


async def _noop():
    return None


@pytest.mark.asyncio
async def test_the_number_of_attempts_a_read_makes_is_the_configured_one(server, monkeypatch):
    monkeypatch.setattr(base.RetryTransport, "_backoff",
                        lambda self, attempt, retry_after: _noop())
    seen = server({"/requests.json": lambda r: httpx.Response(503, text="down", request=r)})
    with pytest.raises(ConnectorError):
        await tyler({"max_retries": 2}).pull_updates()
    assert len(seen.requests) == 3, "one attempt plus two retries"


@pytest.mark.asyncio
async def test_a_create_is_not_retried_on_a_server_error(server, monkeypatch):
    """A 5xx on a POST may mean the record was filed and the answer was lost.
    Retrying it would file a second one — two tickets for one pothole."""
    monkeypatch.setattr(base.RetryTransport, "_backoff",
                        lambda self, attempt, retry_after: _noop())
    seen = server({"/requests.json": lambda r: httpx.Response(500, text="boom", request=r)})
    with pytest.raises(ConnectorError):
        await tyler().push_request(PAYLOAD)
    # One POST. (The GET before it reads the service's attribute definition.)
    assert [r.method for r in seen.requests].count("POST") == 1


# ---------------------------------------------------------------------------
# The generic Open311 connection is the same client, unpinned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_generic_open311_connection_reaches_any_endpoint(server):
    seen = server({"/services.json": json_response(SERVICES)})
    connector = build_connector(
        "open311", {"base_url": "https://city.example.gov/open311/v2"}, {})
    result = await connector.test_connection()

    assert result["ok"] is True and result["verified"] is False
    assert "No API key is saved" in result["detail"]
    assert str(seen.last.url).startswith("https://city.example.gov/open311/v2/services.json")


def test_a_connection_with_no_base_url_says_so_rather_than_building_a_bad_one():
    connector = build_connector("open311", {}, {"api_key": "k"})
    with pytest.raises(ConnectorError) as caught:
        _ = connector.base_url
    assert "base_url" in str(caught.value)
