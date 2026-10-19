"""A report's priority reaches the town's systems, and follows it when it changes.

Before: the create push went out the moment a report was filed, usually before
AI triage had scored it, so vendors got the default 5; and accepting the AI's
score or setting one never left Pinpoint. Accela was not sent a priority at all.
"""

import inspect
import json
from urllib.parse import parse_qs

import httpx
import pytest

pytest.importorskip("httpx")
base = pytest.importorskip("app.integrations.base")
accela_module = pytest.importorskip("app.integrations.connectors.accela")
from app.integrations.base import ConnectorError  # noqa: E402
from app.integrations.registry import build_connector  # noqa: E402


# ---- mapping ----------------------------------------------------------------

def _generic(config=None):
    return build_connector("generic_rest", {"base_url": "https://api.vendor.test/v1", **(config or {})},
                           {"api_key": "k"})


def test_unmapped_priority_is_the_score_itself():
    c = _generic()
    assert c.map_priority_out(7) == 7
    assert c.map_priority_out(7.5) == 7.5
    assert c.map_priority_out(None) is None


def test_bands_follow_the_dashboard_and_an_exact_score_wins():
    c = _generic({"priority_map_out": {"high": "P1", "medium": "P2", "low": "P3", "10": "Emergency"}})
    assert c.map_priority_out(8) == "P1"
    assert c.map_priority_out(10) == "Emergency"
    assert c.map_priority_out(7.9) == "P2"
    assert c.map_priority_out(5) == "P2"
    assert c.map_priority_out(4) == "P3"


def test_a_partial_map_omits_what_it_does_not_cover():
    c = _generic({"priority_map_out": {"high": "P1"}})
    assert c.map_priority_out(3) is None


# ---- Accela -------------------------------------------------------------------

@pytest.fixture
def accela(monkeypatch):
    monkeypatch.setattr(base, "_assert_public_url", lambda url: None)
    accela_module._clear_token_cache()
    seen = []

    async def transport(self, request):
        await request.aread()
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600}, request=request)
        seen.append(request)
        return httpx.Response(200, json={"result": [{"id": "AG-1", "status": {"value": "Open"}}]},
                              request=request)

    monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", transport)
    yield seen
    accela_module._clear_token_cache()


def _accela(config=None):
    return build_connector(
        "accela", {"agency_name": "SPRINGFIELD", "record_type": "ServiceRequest/General/Complaint/NA",
                   **(config or {})},
        {"client_id": "i", "client_secret": "s", "username": "u", "password": "p"})


def test_accela_sends_no_priority_until_the_agency_values_are_mapped(accela):
    import asyncio
    c = _accela()
    assert "push_priority" not in c.capabilities
    asyncio.run(c.push_request({"service_code": "PTH", "description": "x", "priority": 9}))
    assert "priority" not in json.loads(accela[-1].content)


def test_accela_create_and_update_carry_the_mapped_priority(accela):
    import asyncio
    c = _accela({"priority_map_out": {"high": "1 - Emergency", "medium": "2 - Routine", "low": "3 - Low"}})
    assert "push_priority" in c.capabilities
    asyncio.run(c.push_request({"service_code": "PTH", "description": "x", "priority": 9}))
    assert json.loads(accela[-1].content)["priority"] == {"value": "1 - Emergency", "text": "1 - Emergency"}

    asyncio.run(c.push_priority("AG-1", 4))
    req = accela[-1]
    assert req.method == "PUT" and req.url.path.endswith("/v4/records/AG-1")
    assert json.loads(req.content) == {"priority": {"value": "3 - Low", "text": "3 - Low"}}


# ---- ArcGIS -------------------------------------------------------------------

LAYER = "https://services1.arcgis.com/abc/arcgis/rest/services/Requests/FeatureServer/0"
METADATA = {
    "objectIdField": "OBJECTID", "capabilities": "Query,Create,Update",
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID"},
        {"name": "status", "type": "esriFieldTypeString"},
        {"name": "prio", "type": "esriFieldTypeString", "domain": {
            "type": "codedValue", "codedValues": [{"code": "High"}, {"code": "Medium"}, {"code": "Low"}]}},
    ],
}


def _arcgis(monkeypatch, config):
    monkeypatch.setattr(base, "_assert_public_url", lambda url: None)
    edits = []

    async def handle(_t, request):
        body = request.read().decode()
        if request.url.path.endswith("/applyEdits"):
            edits.append(parse_qs(body))
            return httpx.Response(200, json={"updateResults": [{"success": True}]}, request=request)
        return httpx.Response(200, json=METADATA, request=request)

    monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", handle)
    return build_connector("arcgis", {"layer_url": LAYER, **config}, {"api_key": "k"}), edits


def test_arcgis_claims_priority_only_with_a_mapped_column(monkeypatch):
    c, _ = _arcgis(monkeypatch, {})
    assert "push_priority" not in c.capabilities
    c, _ = _arcgis(monkeypatch, {"field_map": {"priority": "prio"}})
    assert "push_priority" in c.capabilities


def test_arcgis_priority_update_writes_the_domain_value(monkeypatch):
    import asyncio
    c, edits = _arcgis(monkeypatch, {"field_map": {"priority": "prio"},
                                     "priority_map_out": {"high": "High", "medium": "Medium", "low": "Low"}})
    asyncio.run(c.push_priority("12", 8))
    attrs = json.loads(edits[-1]["updates"][0])[0]["attributes"]
    assert attrs == {"OBJECTID": 12, "prio": "High"}


def test_arcgis_refuses_a_value_outside_the_domain(monkeypatch):
    import asyncio
    c, edits = _arcgis(monkeypatch, {"field_map": {"priority": "prio"}})  # raw 1-10 into a coded column
    with pytest.raises(ConnectorError, match="not one of the values"):
        asyncio.run(c.push_priority("12", 8))
    assert edits == []


# ---- generic REST -----------------------------------------------------------

def _generic_vendor(monkeypatch):
    monkeypatch.setattr(base, "_assert_public_url", lambda url: None)
    seen = []

    async def handle(_t, request):
        await request.aread()
        seen.append(request)
        return httpx.Response(200, json={"id": "V-1"}, request=request)

    monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", handle)
    return seen


def test_generic_rest_needs_an_update_path_to_claim_priority():
    assert "push_priority" not in _generic().capabilities
    assert "push_priority" in _generic({"update_path": "/requests/{id}"}).capabilities


def test_generic_rest_priority_update(monkeypatch):
    import asyncio
    seen = _generic_vendor(monkeypatch)
    c = _generic({"update_path": "/requests/{id}", "field_map": {"priority": "urgency"},
                  "priority_map_out": {"high": "urgent", "medium": "normal", "low": "low"}})
    asyncio.run(c.push_priority("V-1", 9))
    req = seen[-1]
    assert req.method == "PATCH" and req.url.path == "/v1/requests/V-1"
    assert json.loads(req.content) == {"urgency": "urgent"}


def test_generic_rest_create_body_uses_the_mapping(monkeypatch):
    c = _generic({"priority_map_out": {"high": "urgent"}})
    assert c._build_create_body({"priority": 9})["priority"] == "urgent"
    assert _generic()._build_create_body({"priority": 6})["priority"] == 6


def test_open311_cannot_take_priority_updates():
    c = build_connector("open311", {"base_url": "https://city.test/open311/v2"}, {"api_key": "k"})
    assert "push_priority" not in c.capabilities


# ---- wiring -------------------------------------------------------------------

def test_enqueue_later_uses_a_countdown_and_backlogs_on_failure(monkeypatch):
    from app.services import enqueue as enq

    calls = []

    class Task:
        name = "app.tasks.integrations.push_request_to_integrations"

        def apply_async(self, args=None, kwargs=None, countdown=None):
            calls.append((args, countdown))

    assert enq.enqueue_later(Task(), 90, 42) is True
    assert calls == [((42,), 90)]

    backlogged = []
    monkeypatch.setattr(enq, "_backlog_unqueued", lambda name, args, kwargs: backlogged.append((name, args)))

    class Broken(Task):
        def apply_async(self, **kw):
            raise ConnectionError("broker down")

    assert enq.enqueue_later(Broken(), 90, 42) is False
    assert backlogged and backlogged[0][1] == (42,)


def test_priority_pushes_are_backlogged_when_the_queue_is_down():
    from app.services import enqueue as enq
    assert enq._INTEGRATION_PUSHES["push_priority_to_integrations"] == "push_priority"


def test_intake_waits_for_triage_and_triage_sends_the_report():
    open311 = pytest.importorskip("app.api.open311")
    src = inspect.getsource(open311._finalize_new_request)
    assert "enqueue_later(push_request_to_integrations, TRIAGE_GRACE_SECONDS" in src
    tasks = pytest.importorskip("app.tasks.service_requests")
    assert "sync_after_triage" in inspect.getsource(tasks.analyze_request)


def test_staff_priority_changes_are_pushed_and_audited():
    open311 = pytest.importorskip("app.api.open311")
    accept = inspect.getsource(open311.accept_ai_priority)
    assert "push_priority_to_integrations" in accept
    # The old value is read before it is overwritten.
    assert accept.index("previous = request.manual_priority_score") < accept.index(
        "request.manual_priority_score = float(ai_priority)")
    update = inspect.getsource(open311.update_request_status)
    assert "push_priority_to_integrations" in update and '"priority_changed"' in update


def test_imported_reports_are_not_pushed_onward_by_triage():
    integrations = pytest.importorskip("app.tasks.integrations")
    src = inspect.getsource(integrations.sync_after_triage)
    assert 'startswith("integration_")' in src
