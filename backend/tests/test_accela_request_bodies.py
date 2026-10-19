"""What the Accela connector sends, checked against the Construct API v4 shapes.

Per developer.accela.com: a record's `type` is group/type/subType/category (or
the joined `id`), a status update matches on `status.value`, and dates such as
`updateDateFrom` are compared in the agency's own local time. Coordinates are
only meaningful in the agency's spatial reference, which is usually projected.
"""

import json
from datetime import datetime, timezone

import httpx
import pytest

import app.integrations.base as base
import app.integrations.connectors.accela as accela_module
from app.integrations.connectors.accela import _accela_window, record_type_body
from app.integrations.registry import PLATFORM_CATALOG, build_connector

PAYLOAD = {
    "service_request_id": "REQ-1",
    "service_code": "PTH",
    "service_name": "Pothole",
    "description": "Deep pothole",
    "address": "12 Main St",
    "lat": 40.73,
    "long": -74.17,
    "status": "open",
}


@pytest.fixture
def vendor(monkeypatch):
    monkeypatch.setattr(base, "_assert_public_url", lambda url: None)
    accela_module._clear_token_cache()
    seen = []

    async def transport(self, request):
        await request.aread()
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600}, request=request)
        seen.append(request)
        return httpx.Response(200, json={"result": [{"id": "AGENCY-26CAP-00001",
                                                     "status": {"value": "Open", "text": "Open"}}]},
                              request=request)

    monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", transport)
    yield seen
    accela_module._clear_token_cache()


def connector(config=None):
    return build_connector(
        "accela", {"agency_name": "SPRINGFIELD", "record_type": "ServiceRequest/General/Complaint/NA",
                   **(config or {})},
        {"client_id": "i", "client_secret": "s", "username": "u", "password": "p"})


def body_of(request):
    return json.loads(request.content.decode())


# ---- type --------------------------------------------------------------------

def test_the_four_levels_are_group_type_subtype_category():
    assert record_type_body("ServiceRequest/General/Complaint/NA") == {
        "group": "ServiceRequest", "type": "General", "subType": "Complaint", "category": "NA"}


def test_module_is_not_a_field_accela_reads():
    assert "module" not in record_type_body("A/B/C/D")


def test_a_record_type_id_and_an_alias_are_passed_as_such():
    assert record_type_body("ServiceRequest-General-Complaint-NA") == {
        "id": "ServiceRequest-General-Complaint-NA"}
    assert record_type_body("Pothole Complaint") == {"alias": "Pothole Complaint"}


@pytest.mark.asyncio
async def test_a_category_can_have_its_own_record_type(vendor):
    await connector({"service_code_map_out": {"PTH": "ServiceRequest/Streets/Pothole/NA"}}).push_request(PAYLOAD)
    sent = body_of(vendor[-1])
    assert sent["type"] == {"group": "ServiceRequest", "type": "Streets", "subType": "Pothole", "category": "NA"}


# ---- status --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_update_sends_the_value_accela_matches_on(vendor):
    await connector().push_status("R1", "in_progress", "Crew assigned")
    sent = body_of(vendor[-1])
    assert sent["status"]["value"] == "In Progress"
    assert sent["statusReason"] == {"text": "Crew assigned"}


@pytest.mark.asyncio
async def test_the_status_words_are_the_agencys_own(vendor):
    await connector({"status_map_out": {"closed": "Closed - Resolved"}}).push_status("R1", "closed")
    assert body_of(vendor[-1])["status"]["value"] == "Closed - Resolved"


def test_the_defaults_are_published_for_the_mapping_step_to_confirm():
    assert PLATFORM_CATALOG["accela"]["default_status_map_out"]["in_progress"] == "In Progress"
    assert PLATFORM_CATALOG["accela"]["status_push"] is True
    assert PLATFORM_CATALOG["tyler"]["status_push"] is False


def test_an_inbound_record_reads_the_status_value():
    record = connector()._record_from_accela({"id": "R1", "status": {"value": "Complete", "text": "Done"}})
    assert record.raw_status == "Complete"
    assert record.status == "closed"


# ---- coordinates ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_without_a_coordinate_system_only_the_address_is_sent(vendor):
    await connector().push_request(PAYLOAD)
    address = body_of(vendor[-1])["addresses"][0]
    assert address == {"streetAddress": "12 Main St"}


@pytest.mark.asyncio
async def test_wgs84_sends_longitude_and_latitude(vendor):
    await connector({"coordinate_wkid": "4326"}).push_request(PAYLOAD)
    address = body_of(vendor[-1])["addresses"][0]
    assert address["xCoordinate"] == -74.17 and address["yCoordinate"] == 40.73


@pytest.mark.asyncio
async def test_a_projected_system_without_pyproj_omits_xy_and_says_so(vendor, monkeypatch):
    monkeypatch.setattr(accela_module, "_reprojector_from_wgs84", lambda wkid: None)
    conn = connector({"coordinate_wkid": 3424})
    await conn.push_request(PAYLOAD)
    address = body_of(vendor[-1])["addresses"][0]
    assert "xCoordinate" not in address and address["streetAddress"] == "12 Main St"
    assert any("3424" in w for w in conn.take_warnings())


@pytest.mark.asyncio
async def test_a_projected_system_is_reprojected_when_possible(vendor, monkeypatch):
    monkeypatch.setattr(accela_module, "_reprojector_from_wgs84",
                        lambda wkid: (lambda x, y: (x * 1000, y * 1000)))
    await connector({"coordinate_wkid": "3424"}).push_request(PAYLOAD)
    address = body_of(vendor[-1])["addresses"][0]
    assert address["xCoordinate"] == pytest.approx(-74170) and address["yCoordinate"] == pytest.approx(40730)


# ---- time zone --------------------------------------------------------------------

def test_the_window_is_formatted_in_agency_local_time():
    winter = datetime(2026, 1, 15, 17, 30, tzinfo=timezone.utc)
    assert _accela_window(winter) == "2026-01-15 12:30:00"
    assert _accela_window(winter, "America/Chicago") == "2026-01-15 11:30:00"
    # A naive watermark is UTC.
    assert _accela_window(winter.replace(tzinfo=None), "UTC") == "2026-01-15 17:30:00"


def test_an_unknown_zone_falls_back_rather_than_crashing_the_poll():
    winter = datetime(2026, 1, 15, 17, 30, tzinfo=timezone.utc)
    assert _accela_window(winter, "Mars/Olympus") == "2026-01-15 12:30:00"


@pytest.mark.asyncio
async def test_the_pull_sends_the_configured_zone(vendor):
    await connector({"agency_timezone": "America/Los_Angeles"}).pull_updates(
        since=datetime(2026, 8, 5, 19, 0, tzinfo=timezone.utc))
    assert dict(vendor[-1].url.params)["updateDateFrom"] == "2026-08-05 12:00:00"


# ---- sign-in copy -------------------------------------------------------------------

def test_the_setup_notes_say_what_sign_in_needs():
    notes = PLATFORM_CATALOG["accela"]["setup_notes"]
    assert "ACCELA_CLIENT_ID" in notes and "redirect URI" in notes
    assert "username and password" in notes
