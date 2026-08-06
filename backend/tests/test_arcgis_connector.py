"""Esri ArcGIS Feature Service connector.

The interesting behaviours here are the ones ArcGIS makes easy to get wrong:
errors arrive as HTTP 200 bodies, edits are form-encoded JSON strings, dates
are epoch milliseconds, and an unknown attribute name fails the whole edit.
"""
import json
from datetime import datetime, timezone

import httpx
import pytest

import app.integrations.base as base
from app.integrations.base import ConnectorError
from app.integrations.registry import PLATFORM_CATALOG, build_connector

LAYER = "https://services1.arcgis.com/abc/arcgis/rest/services/Requests/FeatureServer/0"

LAYER_METADATA = {
    "id": 0,
    "name": "Service Requests",
    "type": "Feature Layer",
    "capabilities": "Query,Create,Update,Delete",
    "objectIdField": "OBJECTID",
    "hasAttachments": True,
    "editFieldsInfo": {"editDateField": "EditDate", "creationDateField": "CreationDate"},
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID"},
        {"name": "reqid", "type": "esriFieldTypeString"},
        {"name": "reqcategory", "type": "esriFieldTypeString"},
        {"name": "details", "type": "esriFieldTypeString"},
        {"name": "address", "type": "esriFieldTypeString"},
        {"name": "status", "type": "esriFieldTypeString"},
        {"name": "submitdt", "type": "esriFieldTypeDate"},
        {"name": "EditDate", "type": "esriFieldTypeDate"},
    ],
}

PAYLOAD = {
    "service_request_id": "SR-1001",
    "service_name": "Pothole",
    "description": "Deep pothole by the school",
    "address": "12 Main St",
    "lat": 40.73,
    "long": -74.17,
    "status": "open",
    "requested_datetime": "2026-08-01T14:30:00+00:00",
}


def _connector(config=None, credentials=None):
    return build_connector(
        "arcgis",
        {"layer_url": LAYER, **(config or {})},
        {"api_key": "test-key", **(credentials or {})},
    )


class Recorder:
    """Stands in for the ArcGIS service: routes by URL suffix, records requests."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def install(self, monkeypatch):
        monkeypatch.setattr(base, "_assert_public_url", lambda url: None)

        async def handle(_transport, request):
            # read() first: a multipart (attachment) request streams, so
            # touching .content before reading raises.
            body = request.read().decode("utf-8", "replace")
            self.requests.append((str(request.url), request.method, body, dict(request.headers)))
            path = request.url.path
            for suffix, payload in self.routes.items():
                # "metadata" is the layer url itself — no operation on the end.
                if (suffix in path if suffix != "metadata" else path.rstrip("/").split("/")[-1].isdigit()):
                    value = payload(body) if callable(payload) else payload
                    return httpx.Response(200, json=value, request=request)
            raise AssertionError(f"unrouted request: {request.url}")

        monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", handle)
        return self

    def params_for(self, suffix):
        """Parameters of the last request to an endpoint, whether they travelled
        as a query string (reads are GETs) or a form body (edits are POSTs)."""
        from urllib.parse import parse_qs, urlparse
        matches = [r for r in self.requests if suffix in urlparse(r[0]).path]
        assert matches, f"no request to {suffix}"
        url, _method, body, _headers = matches[-1]
        merged = {**parse_qs(urlparse(url).query), **parse_qs(body)}
        return {k: v[0] for k, v in merged.items()}


# ---- Auth -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_key_travels_as_a_bearer_header_on_reads(monkeypatch):
    """GETs carry the token in X-Esri-Authorization, never the URL — query
    strings are copied into proxy and access logs."""
    rec = Recorder({"metadata": LAYER_METADATA}).install(monkeypatch)
    conn = _connector()
    await conn.test_connection()
    url, _method, _body, headers = rec.requests[0]
    assert "test-key" not in url
    assert headers["x-esri-authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_username_password_generates_a_token(monkeypatch):
    rec = Recorder({
        "generateToken": {"token": "minted-token", "expires": 1, "ssl": True},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    conn = build_connector("arcgis", {"layer_url": LAYER}, {"username": "gis", "password": "pw"})
    await conn.test_connection()
    assert rec.requests[0][0].endswith("/sharing/rest/generateToken")
    assert rec.params_for("generateToken")["client"] == "requestip"
    assert "minted-token" not in rec.requests[1][0]
    assert rec.requests[1][3]["x-esri-authorization"] == "Bearer minted-token"


@pytest.mark.asyncio
async def test_falls_back_to_the_maps_arcgis_api_key(monkeypatch):
    """A town that set up Esri maps shouldn't have to paste the same key twice."""
    rec = Recorder({"metadata": LAYER_METADATA}).install(monkeypatch)
    conn = build_connector("arcgis", {"layer_url": LAYER}, {})

    async def fake_get_secret(name):
        return "maps-key" if name == "ARCGIS_API_KEY" else None

    monkeypatch.setattr("app.services.secret_manager.get_secret", fake_get_secret)
    await conn.test_connection()
    assert rec.requests[0][3]["x-esri-authorization"] == "Bearer maps-key"


@pytest.mark.asyncio
async def test_reuse_can_be_turned_off(monkeypatch):
    conn = build_connector("arcgis", {"layer_url": LAYER, "reuse_maps_api_key": "false"}, {})
    with pytest.raises(ConnectorError, match="credentials missing"):
        await conn._get_token()


@pytest.mark.asyncio
@pytest.mark.parametrize("host", [
    "gis.example.gov",   # a town's own ArcGIS Enterprise server
    "notarcgis.com",     # a lookalike — the suffix check needs the dot boundary
    "evil.arcgis.com.attacker.net",
])
async def test_maps_key_is_not_reused_off_esri_hosts(monkeypatch, host):
    """The maps key is an org-wide secret; auto-sending it to whatever
    layer_url an admin pasted would hand it to any host that asks."""
    conn = build_connector(
        "arcgis", {"layer_url": f"https://{host}/arcgis/rest/services/Requests/FeatureServer/0"}, {},
    )

    async def fake_get_secret(name):
        return "maps-key" if name == "ARCGIS_API_KEY" else None

    monkeypatch.setattr("app.services.secret_manager.get_secret", fake_get_secret)
    with pytest.raises(ConnectorError, match=r"only reused for layers on \*\.arcgis\.com"):
        await conn._get_token()


# ---- ArcGIS's error-inside-a-200 bodies ------------------------------------


@pytest.mark.asyncio
async def test_error_body_on_http_200_raises(monkeypatch):
    Recorder({"metadata": {"error": {"code": 400, "message": "Invalid URL", "details": []}}}).install(monkeypatch)
    with pytest.raises(ConnectorError, match="ArcGIS error 400"):
        await _connector().test_connection()


def test_non_json_error_body_is_redacted():
    """A proxy error page can echo the request back, token included; what we
    store and display must be scrubbed."""
    from app.integrations.connectors.arcgis import ArcGISConnector

    resp = httpx.Response(
        200, text="<html>502 Bad Gateway: /query?token=SECRETVALUE123&f=json</html>",
        request=httpx.Request("GET", LAYER),
    )
    with pytest.raises(ConnectorError) as exc:
        ArcGISConnector._arcgis_json(resp, "ArcGIS query")
    assert "SECRETVALUE123" not in str(exc.value)
    assert "[REDACTED]" in str(exc.value)


@pytest.mark.asyncio
async def test_token_rejection_is_reported_as_a_credentials_problem(monkeypatch):
    """Code 498 must read as 403 so the admin UI's friendly text tells the
    clerk to check the key rather than blaming the web address."""
    Recorder({"metadata": {"error": {"code": 498, "message": "Invalid token."}}}).install(monkeypatch)
    with pytest.raises(ConnectorError, match="HTTP 403"):
        await _connector().test_connection()


# ---- Test button -----------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_reports_layer_name_and_editability(monkeypatch):
    Recorder({"metadata": LAYER_METADATA}).install(monkeypatch)
    result = await _connector().test_connection()
    assert result["ok"] is True
    assert "Service Requests" in result["detail"]
    assert "accepts new reports and status updates" in result["detail"]
    assert "Photos will attach" in result["detail"]


@pytest.mark.asyncio
async def test_connection_warns_on_a_read_only_layer(monkeypatch):
    metadata = {**LAYER_METADATA, "capabilities": "Query", "hasAttachments": False}
    Recorder({"metadata": metadata}).install(monkeypatch)
    result = await _connector().test_connection()
    assert "read-only" in result["detail"]
    assert "Attachments are turned off" in result["detail"]


@pytest.mark.asyncio
async def test_connection_warns_when_editor_tracking_is_off(monkeypatch):
    metadata = {k: v for k, v in LAYER_METADATA.items() if k != "editFieldsInfo"}
    metadata["fields"] = [f for f in LAYER_METADATA["fields"] if f["name"] != "EditDate"]
    Recorder({"metadata": metadata}).install(monkeypatch)
    result = await _connector().test_connection()
    assert "Editor tracking is off" in result["detail"]


# ---- Push ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_sends_geometry_and_mapped_attributes(monkeypatch):
    rec = Recorder({
        "applyEdits": {"addResults": [{"objectId": 618, "globalId": None, "success": True}]},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    record = await _connector().push_request(PAYLOAD)

    assert record.external_id == "618"
    form = rec.params_for("applyEdits")
    assert form["f"] == "json" and form["token"] == "test-key"
    feature = json.loads(form["adds"])[0]
    assert feature["geometry"] == {"x": -74.17, "y": 40.73, "spatialReference": {"wkid": 4326}}
    assert feature["attributes"]["reqid"] == "SR-1001"
    assert feature["attributes"]["reqcategory"] == "Pothole"
    assert feature["attributes"]["details"] == "Deep pothole by the school"
    # Pinpoint's "open" becomes the layer's own vocabulary
    assert feature["attributes"]["status"] == "Submitted"
    # Date fields go over as epoch milliseconds, not ISO strings
    assert feature["attributes"]["submitdt"] == 1785594600000


@pytest.mark.asyncio
async def test_push_honours_a_field_map_and_static_fields(monkeypatch):
    rec = Recorder({
        "applyEdits": {"addResults": [{"objectId": 7, "success": True}]},
        "metadata": {**LAYER_METADATA, "fields": LAYER_METADATA["fields"] + [
            {"name": "PROBTYPE", "type": "esriFieldTypeString"},
            {"name": "SOURCE", "type": "esriFieldTypeString"},
        ]},
    }).install(monkeypatch)
    conn = _connector({
        "field_map": {"service_name": "PROBTYPE", "address": ""},
        "static_fields": {"SOURCE": "Pinpoint 311"},
    })
    await conn.push_request(PAYLOAD)
    attributes = json.loads(rec.params_for("applyEdits")["adds"])[0]["attributes"]
    assert attributes["PROBTYPE"] == "Pothole"
    assert attributes["SOURCE"] == "Pinpoint 311"
    assert "address" not in attributes  # mapping a field to blank omits it


@pytest.mark.asyncio
async def test_push_drops_attributes_the_layer_does_not_have(monkeypatch):
    """ArcGIS fails the whole edit on one unknown column, so a drifted field
    map should cost that field, not every report."""
    rec = Recorder({
        "applyEdits": {"addResults": [{"objectId": 9, "success": True}]},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    conn = _connector({"field_map": {"description": "no_such_column"}})
    await conn.push_request(PAYLOAD)
    attributes = json.loads(rec.params_for("applyEdits")["adds"])[0]["attributes"]
    assert "no_such_column" not in attributes
    assert attributes["reqid"] == "SR-1001"


@pytest.mark.asyncio
async def test_push_surfaces_a_per_feature_rejection(monkeypatch):
    Recorder({
        "applyEdits": {"addResults": [
            {"objectId": 2, "success": False,
             "error": {"code": 1019, "description": "Violated attribute constraint rule."}},
        ]},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    with pytest.raises(ConnectorError, match="Violated attribute constraint"):
        await _connector().push_request(PAYLOAD)


@pytest.mark.asyncio
async def test_push_without_coordinates_sends_no_geometry(monkeypatch):
    rec = Recorder({
        "applyEdits": {"addResults": [{"objectId": 3, "success": True}]},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    await _connector().push_request({**PAYLOAD, "lat": None, "long": None})
    assert "geometry" not in json.loads(rec.params_for("applyEdits")["adds"])[0]


# ---- Status write-back ------------------------------------------------------


@pytest.mark.asyncio
async def test_push_status_updates_by_object_id(monkeypatch):
    rec = Recorder({
        "applyEdits": {"updateResults": [{"objectId": 618, "success": True}]},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    conn = _connector({"status_notes_field": "notes"})
    await conn.push_status("618", "closed", notes="Patched on Tuesday")
    attributes = json.loads(rec.params_for("applyEdits")["updates"])[0]["attributes"]
    assert attributes["OBJECTID"] == 618
    assert attributes["status"] == "Completed"
    assert attributes["notes"] == "Patched on Tuesday"


@pytest.mark.asyncio
async def test_push_status_fails_on_an_empty_apply_edits_body(monkeypatch):
    """A 200 with no updateResults is not a confirmation — treating it as one
    would mark the sync done while the layer never changed."""
    Recorder({"applyEdits": {}, "metadata": LAYER_METADATA}).install(monkeypatch)
    with pytest.raises(ConnectorError, match="no updateResults"):
        await _connector().push_status("618", "closed")


# ---- Pull -------------------------------------------------------------------


FEATURE = {
    "attributes": {
        "OBJECTID": 618, "reqid": "SR-1001", "reqcategory": "Pothole",
        "details": "Deep pothole", "address": "12 Main St", "status": "Assigned",
        "EditDate": 1785594600000,
    },
    "geometry": {"x": -74.17, "y": 40.73},
}


@pytest.mark.asyncio
async def test_pull_filters_on_the_edit_date_field(monkeypatch):
    rec = Recorder({
        "/query": {"features": [FEATURE]},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    since = datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)
    records = await _connector().pull_updates(since=since)

    assert rec.params_for("/query")["where"] == "EditDate >= timestamp '2026-08-01 14:30:00'"
    assert rec.params_for("/query")["outSR"] == "4326"
    assert len(records) == 1
    record = records[0]
    assert record.external_id == "618"
    assert record.raw_status == "Assigned"
    assert record.status == "in_progress"
    assert record.updated_at == datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)
    assert (record.lat, record.long) == (40.73, -74.17)
    assert record.description == "Deep pothole"


@pytest.mark.asyncio
async def test_pull_without_editor_tracking_reads_the_whole_layer(monkeypatch):
    metadata = {k: v for k, v in LAYER_METADATA.items() if k != "editFieldsInfo"}
    metadata["fields"] = [f for f in LAYER_METADATA["fields"] if f["name"] != "EditDate"]
    rec = Recorder({"/query": {"features": []}, "metadata": metadata}).install(monkeypatch)
    await _connector().pull_updates(since=datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert rec.params_for("/query")["where"] == "1=1"


@pytest.mark.asyncio
async def test_pull_pages_until_the_transfer_limit_clears(monkeypatch):
    pages = [
        {"features": [FEATURE], "exceededTransferLimit": True},
        {"features": [{**FEATURE, "attributes": {**FEATURE["attributes"], "OBJECTID": 619}}]},
    ]
    state = {"n": 0}

    def query(_body):
        page = pages[min(state["n"], len(pages) - 1)]
        state["n"] += 1
        return page

    Recorder({"/query": query, "metadata": LAYER_METADATA}).install(monkeypatch)
    records = await _connector().pull_updates()
    assert sorted(r.external_id for r in records) == ["618", "619"]


@pytest.mark.asyncio
async def test_fetch_record_by_a_custom_external_id_field(monkeypatch):
    rec = Recorder({"/query": {"features": [FEATURE]}, "metadata": LAYER_METADATA}).install(monkeypatch)
    conn = _connector({"external_id_field": "reqid"})
    record = await conn.fetch_record("SR-1001")
    assert rec.params_for("/query")["where"] == "reqid = 'SR-1001'"
    assert record.external_id == "SR-1001"


def test_sql_literal_quotes_and_escapes():
    """An external id reaches a WHERE clause, so it must not be able to
    break out of the quoted literal."""
    from app.integrations.connectors.arcgis import ArcGISConnector

    assert ArcGISConnector._sql_literal("618") == "618"
    assert ArcGISConnector._sql_literal("SR-1001") == "'SR-1001'"
    assert ArcGISConnector._sql_literal("a' OR '1'='1") == "'a'' OR ''1''=''1'"


# ---- Attachments -------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_document_posts_to_add_attachment(monkeypatch):
    rec = Recorder({
        "addAttachment": {"addAttachmentResult": {"objectId": 4, "success": True}},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    await _connector().push_document("618", "photo.jpg", b"\xff\xd8jpegbytes", "image/jpeg")
    url, method, body, _headers = rec.requests[-1]
    assert url.endswith("/FeatureServer/0/618/addAttachment") and method == "POST"
    assert "photo.jpg" in body and "jpegbytes" in body


@pytest.mark.asyncio
async def test_push_document_explains_a_layer_without_attachments(monkeypatch):
    Recorder({"metadata": {**LAYER_METADATA, "hasAttachments": False}}).install(monkeypatch)
    with pytest.raises(ConnectorError, match="attachments enabled"):
        await _connector().push_document("618", "photo.jpg", b"x", "image/jpeg")


# ---- Assets --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pull_assets_returns_mappable_geojson_points(monkeypatch):
    asset_url = "https://services1.arcgis.com/abc/arcgis/rest/services/Hydrants/FeatureServer/0"
    features = [
        {"attributes": {"OBJECTID": 1, "HYDRANT_ID": "H-12"}, "geometry": {"x": -74.1, "y": 40.7}},
        {"attributes": {"OBJECTID": 2, "HYDRANT_ID": "H-13"}, "geometry": {}},  # no location
    ]
    Recorder({
        "/query": {"features": features},
        "Hydrants/FeatureServer/0": {"name": "Hydrants", "objectIdField": "OBJECTID",
                                     "capabilities": "Query", "fields": []},
        "metadata": LAYER_METADATA,
    }).install(monkeypatch)
    conn = _connector({"asset_layer_url": asset_url, "asset_id_field": "HYDRANT_ID"})
    assets = await conn.pull_assets()
    assert len(assets) == 1  # the one without geometry is skipped
    assert assets[0]["geometry"] == {"type": "Point", "coordinates": [-74.1, 40.7]}
    assert assets[0]["properties"]["asset_id"] == "H-12"


@pytest.mark.asyncio
async def test_pull_assets_without_a_layer_url_explains_itself(monkeypatch):
    with pytest.raises(ConnectorError, match="asset layer URL"):
        await _connector().pull_assets()


# ---- Config guards & catalog ------------------------------------------------


@pytest.mark.asyncio
async def test_missing_layer_url_is_a_clear_error():
    conn = build_connector("arcgis", {}, {"api_key": "k"})
    with pytest.raises(ConnectorError, match="FeatureServer/0"):
        await conn.test_connection()


def test_catalog_entry_matches_the_connector():
    meta = PLATFORM_CATALOG["arcgis"]
    conn = build_connector("arcgis", {"layer_url": LAYER}, {})
    assert set(meta["capabilities"]) == conn.capabilities
    # Every field the card offers has plain-language help behind it.
    for field in meta["credential_fields"] + meta["config_fields"]:
        assert field["key"] in meta["field_help"], f"no field_help for {field['key']}"
    assert meta["plain_summary"] and meta["what_you_need"] and meta["vendor_ask"]
