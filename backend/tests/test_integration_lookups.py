"""A mapping should be picked from the vendor's codes, not typed from memory.

`status_map_out`, `status_map_in` and `service_code_map` are promises about
values that live in the vendor's *data* -- this town's Open311 service codes,
this ArcGIS layer's coded-value domain. Nothing published anywhere says what
they are, so the setup form asked an admin to type them, and a wrong one is not
an error anybody sees: it is a status that silently never maps, or a 422 on the
first real report.

Hydration pulls those lists down while we have the credentials. The rule these
tests exist to hold is that it is only done where the vendor genuinely
publishes such a list to a call the connector ALREADY makes -- an invented
endpoint gives an admin a menu that is not the truth, which is worse than the
text box it replaced.
"""

from datetime import datetime, timezone

import httpx
import pytest

import app.integrations.base as base
from app.integrations.base import ConnectorError
from app.integrations.registry import build_connector

BASE = "https://springfield.tylerapp.com/open311/v2"
LAYER = "https://services1.arcgis.com/abc/arcgis/rest/services/Requests/FeatureServer/0"


class Server:
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
            return httpx.Response(404, json={}, request=request)

        monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", handle)
        return self


@pytest.fixture
def server(monkeypatch):
    return lambda routes: Server(routes).install(monkeypatch)


def json_response(body, status=200):
    return lambda request: httpx.Response(status, json=body, request=request)


# ---------------------------------------------------------------------------
# Open311 / Tyler: the service list the spec already requires
# ---------------------------------------------------------------------------

SERVICES = [
    {"service_code": "001", "service_name": "Pothole"},
    {"service_code": "graffiti-removal", "service_name": "Graffiti Removal"},
    {"service_name": "Nameless", "description": "no code, unusable"},
]


async def test_a_georeport_endpoint_offers_its_own_service_codes(server):
    seen = server({"/services.json": json_response(SERVICES)})
    connector = build_connector("tyler", {"base_url": BASE}, {"api_key": "k"})
    lookups = await connector.pull_lookups()

    assert lookups["services"] == [
        {"code": "001", "name": "Pothole"},
        {"code": "graffiti-removal", "name": "Graffiti Removal"},
    ], "a service with no code cannot be mapped to and should not be offered"
    assert lookups["_source"]["services"].endswith("/services.json")
    # No new endpoint: this is the same call the connection check makes.
    assert str(seen.requests[-1].url).startswith(f"{BASE}/services.json")


async def test_the_open311_status_list_is_the_spec_not_a_fetch(server):
    """There is nothing to fetch: GeoReport v2 fixes the outbound vocabulary at
    open/closed, and saying where that came from matters as much as the list."""
    server({"/services.json": json_response(SERVICES)})
    connector = build_connector("open311", {"base_url": BASE}, {})
    lookups = await connector.pull_lookups()

    assert [s["code"] for s in lookups["statuses"]] == ["open", "closed"]
    assert "specification" in lookups["_source"]["statuses"]


async def test_a_server_that_refuses_the_list_does_not_hand_back_an_empty_menu(server):
    """An empty list and a rejected credential must not look the same. One means
    "this town has no categories", the other means "ask again"."""
    server({"/services.json": lambda r: httpx.Response(401, text="bad key", request=r)})
    connector = build_connector("tyler", {"base_url": BASE}, {"api_key": "wrong"})
    with pytest.raises(ConnectorError):
        await connector.pull_lookups()


# ---------------------------------------------------------------------------
# ArcGIS: the layer's own coded-value domain
# ---------------------------------------------------------------------------

def _metadata(status_domain):
    status_field = {"name": "status", "type": "esriFieldTypeString", "alias": "Status"}
    if status_domain is not None:
        status_field["domain"] = status_domain
    return {
        "name": "Service Requests",
        "objectIdField": "OBJECTID",
        "capabilities": "Query,Create,Update",
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "Object ID"},
            {"name": "reqid", "type": "esriFieldTypeString", "alias": "Request ID"},
            status_field,
        ],
    }


CODED = {
    "type": "codedValue",
    "name": "RequestStatus",
    "codedValues": [
        {"name": "Submitted", "code": "SUB"},
        {"name": "Assigned to crew", "code": "ASN"},
        {"name": "Completed", "code": "CMP"},
    ],
}


async def test_the_layers_own_domain_is_the_status_menu(server):
    seen = server({"/FeatureServer/0": json_response(_metadata(CODED))})
    connector = build_connector("arcgis", {"layer_url": LAYER}, {"api_key": "k"})
    lookups = await connector.pull_lookups()

    assert lookups["statuses"] == [
        {"code": "SUB", "name": "Submitted"},
        {"code": "ASN", "name": "Assigned to crew"},
        {"code": "CMP", "name": "Completed"},
    ]
    assert "coded-value domain" in lookups["_source"]["statuses"]
    assert "Service Requests" in lookups["_source"]["statuses"]
    # Same ?f=json the connection check already reads.
    assert seen.requests[-1].url.params.get("f") == "json"


async def test_the_column_list_comes_back_so_a_field_map_is_picked_too(server):
    server({"/FeatureServer/0": json_response(_metadata(CODED))})
    connector = build_connector("arcgis", {"layer_url": LAYER}, {"api_key": "k"})
    lookups = await connector.pull_lookups()
    assert {f["code"] for f in lookups["fields"]} == {"OBJECTID", "reqid", "status"}
    assert {"code": "reqid", "name": "Request ID"} in lookups["fields"]


async def test_a_free_text_status_column_offers_nothing_rather_than_something_invented(server):
    """That town really does have a free-text column. A menu here would be a
    list of values we made up."""
    server({"/FeatureServer/0": json_response(_metadata(None))})
    connector = build_connector("arcgis", {"layer_url": LAYER}, {"api_key": "k"})
    lookups = await connector.pull_lookups()

    assert lookups["statuses"] == []
    assert "no coded-value domain" in lookups["_source"]["statuses"]
    assert lookups["fields"], "the columns are still worth offering"


async def test_the_domain_is_read_off_the_mapped_column_not_a_guessed_one(server):
    """A town whose status column is called something else still gets its own
    domain, because the field map already says which column that is."""
    metadata = _metadata(None)
    metadata["fields"].append({"name": "WorkStatus", "type": "esriFieldTypeString",
                               "alias": "Work Status", "domain": CODED})
    server({"/FeatureServer/0": json_response(metadata)})
    connector = build_connector(
        "arcgis", {"layer_url": LAYER, "field_map": {"status": "WorkStatus"}}, {"api_key": "k"})
    lookups = await connector.pull_lookups()

    assert [s["code"] for s in lookups["statuses"]] == ["SUB", "ASN", "CMP"]
    assert "WorkStatus" in lookups["_source"]["statuses"]


# ---------------------------------------------------------------------------
# Where a vendor publishes nothing, say so
# ---------------------------------------------------------------------------

def test_the_connectors_that_cannot_hydrate_do_not_claim_they_can():
    """Accela's settings path is not something this codebase is confident about,
    and generic_rest exists precisely because the vendor has no published API.
    Both must be absent from the capability rather than raising at the vendor."""
    accela = build_connector("accela", {"agency_name": "A"}, {})
    generic = build_connector("generic_rest", {"base_url": "https://api.test/v1"}, {})
    assert "lookups" not in accela.capabilities
    assert "lookups" not in generic.capabilities
    assert "lookups" in build_connector("tyler", {"base_url": BASE}, {}).capabilities
    assert "lookups" in build_connector("arcgis", {"layer_url": LAYER}, {}).capabilities


async def test_asking_one_anyway_explains_rather_than_invents():
    connector = build_connector("accela", {"agency_name": "A"}, {})
    with pytest.raises(ConnectorError) as caught:
        await connector.pull_lookups()
    assert "does not publish a list of its own codes" in str(caught.value)


def test_no_connector_invents_an_endpoint_for_this():
    """The rule, enforced: hydration may only use a path the connector already
    calls elsewhere. A new URL string inside pull_lookups is the failure mode --
    a mapping screen full of nothing, or a 404 in the sync log every time an
    admin opens the page."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app/integrations/connectors"
    for name in ("open311.py", "arcgis.py"):
        source = (root / name).read_text()
        block = source[source.index("async def pull_lookups"):]
        block = block[:block.index("\n    async def ", 1)] if "\n    async def " in block[1:] else block
        code = "\n".join(line.split("#")[0] for line in block.splitlines())
        # The only URL either builds is one the rest of the file already builds.
        for fragment in ("http://", "https://"):
            assert fragment not in code, f"{name} hardcodes a URL in pull_lookups"


# ---------------------------------------------------------------------------
# The approved mapping
# ---------------------------------------------------------------------------

def test_a_code_the_vendor_does_not_have_is_caught_before_the_first_report():
    pytest.importorskip("fastapi.routing")
    from app.api.integrations import _unknown_codes

    known = [{"code": "SUB", "name": "Submitted"}, {"code": "CMP", "name": "Completed"}]
    assert _unknown_codes({"open": "SUB", "closed": "CMP"}, known) == []
    assert _unknown_codes({"open": "SUB", "closed": "COMPLETE"}, known) == ["COMPLETE"]
    assert _unknown_codes({"open": "Sub"}, known) == ["Sub"], "codes are exact, not casual"


def test_nothing_is_rejected_when_there_is_no_list_to_check_against():
    """A vendor that publishes no codes gets an empty list. Refusing a mapping
    because we could not check it would make the honest "we don't know" state
    unusable, which is how an honest state gets removed."""
    pytest.importorskip("fastapi.routing")
    from app.api.integrations import _unknown_codes

    assert _unknown_codes({"open": "whatever the vendor said"}, []) == []
    assert _unknown_codes(None, [{"code": "SUB"}]) == []


def test_approval_is_recorded_apart_from_the_mapping_itself():
    """An empty mapping somebody deliberately approved and one nobody has ever
    opened are the same JSON. Only one of them is a decision."""
    pytest.importorskip("sqlalchemy.orm")
    from app.models import IntegrationConfig

    columns = {c.name for c in IntegrationConfig.__table__.columns}
    assert {"mapping_approved_at", "mapping_approved_by",
            "lookups_cache", "lookups_fetched_at"} <= columns


def test_the_cache_is_not_somewhere_an_admin_can_write_to():
    """It exists to check the admin's input. A value inside `config` would be
    settable through the ordinary update endpoint by anyone who can edit the
    connection, which would make the check circular."""
    pytest.importorskip("fastapi.routing")
    from app.api.integrations import _EXTRA_CONFIG_KEYS
    from app.integrations.registry import PLATFORM_CATALOG

    writable = set(_EXTRA_CONFIG_KEYS.get("config_fields", set()))
    for meta in PLATFORM_CATALOG.values():
        writable |= {f["key"] for f in meta.get("config_fields", [])}
    assert "lookups_cache" not in writable
    assert "lookups_fetched_at" not in writable
    assert "mapping_approved_at" not in writable


def test_the_hydration_endpoint_records_a_failure_like_any_other_vendor_call():
    """A refresh that fails on an expired credential is the same evidence as a
    failed push, and a health surface that only learns from pushes is how a dead
    key survives a month."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "app/api/integrations.py").read_text()
    block = text[text.index("async def refresh_integration_lookups"):
                 text.index("async def approve_integration_mapping")]
    code = "\n".join(line.split("#")[0] for line in block.splitlines())
    assert "record_failure" in code
    assert "clean_error" in code, "a vendor error reaching the browser must be scrubbed"
    assert "Depends(get_current_admin)" in code


def test_the_migration_and_the_model_agree_on_the_new_columns():
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "alembic/versions"
    migration = "\n".join(p.read_text() for p in versions.glob("*.py")
                          if "lookups_cache" in p.read_text())
    assert migration, "no migration adds lookups_cache"
    for column in ("lookups_cache", "lookups_fetched_at",
                   "mapping_approved_at", "mapping_approved_by"):
        assert f"'{column}'" in migration
    # Additive: four nullable columns, nothing dropped or narrowed.
    assert "drop_column" in migration.split("def downgrade")[1]
    assert "drop_column" not in migration.split("def downgrade")[0]
