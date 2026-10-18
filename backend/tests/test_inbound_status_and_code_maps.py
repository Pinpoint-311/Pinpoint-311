"""Inbound status that does not clobber staff work, and explicit code maps.

A pull reports the vendor's status on every poll whether or not it changed.
Applying it whenever it differed from ours meant Open311 -- which has only
open/closed -- reset every "in progress" a staff member set, every fifteen
minutes. And the service-code map was read one way on push and the other way on
import. These tests pin both rules down without a database.
"""

from pathlib import Path

import pytest

from app.integrations.mapping import (
    decide_inbound_status, local_code_for, normalize_raw_status,
    service_code_map_in, service_code_map_out,
)
from app.integrations.registry import build_connector

BACKEND = Path(__file__).resolve().parents[1]


def open311_map(raw):
    return build_connector("open311", {"base_url": "https://x.test/v2"}, {}).map_status_in(raw)


def arcgis_map(raw):
    return build_connector("arcgis", {"layer_url": "https://x.arcgis.com/0"}, {}).map_status_in(raw)


def decide(previous, current, local, map_in=open311_map):
    return decide_inbound_status(previous_raw=previous, current_raw=current,
                                 inbound_status=map_in(current), local_status=local,
                                 map_in=map_in)


# ---------------------------------------------------------------------------
# No clobber
# ---------------------------------------------------------------------------

def test_an_unchanged_vendor_status_never_downgrades_local_progress():
    """The bug: vendor still says "open", staff moved it to in progress."""
    assert decide("open", "open", "in_progress") is None


def test_an_unchanged_vendor_status_does_not_reopen_a_closed_request():
    assert decide("open", "open", "closed") is None


def test_case_and_spacing_are_not_a_change():
    assert normalize_raw_status("In  Progress") == normalize_raw_status("in_progress")
    assert decide("In Progress", "in progress", "open", arcgis_map) is None


def test_a_genuine_vendor_change_is_applied():
    assert decide("open", "closed", "in_progress") == "closed"


def test_a_genuine_vendor_reopen_after_our_push_is_applied():
    """Closed locally, then the vendor reopened it: that is real news."""
    assert decide("closed", "open", "closed") == "open"


def test_a_change_between_two_words_that_mean_the_same_is_not_a_downgrade():
    """Submitted -> Received is open -> open to us; applying it would turn a
    local in_progress back to open through a lossy map."""
    assert decide("Submitted", "Received", "in_progress", arcgis_map) is None


def test_the_vendor_moving_back_to_an_open_word_is_applied():
    """We pushed Assigned (in progress); the crew set it back to Submitted."""
    assert decide("Assigned", "Submitted", "in_progress", arcgis_map) == "open"


def test_first_sighting_only_moves_forward():
    """No baseline: an "open" might be stale, a "closed" is progress."""
    assert decide(None, "open", "in_progress") is None
    assert decide(None, "closed", "in_progress") == "closed"
    assert decide(None, "Assigned", "open", arcgis_map) == "in_progress"


def test_nothing_to_apply_when_it_already_matches():
    assert decide("open", "closed", "closed") is None


def test_an_unknown_inbound_status_is_ignored():
    assert decide_inbound_status(previous_raw="a", current_raw="b", inbound_status="weird",
                                 local_status="open", map_in=lambda r: r) is None


def test_a_word_we_send_reads_back_as_what_we_meant():
    """status_map_out in_progress -> "Under Review" with no inbound entry used to
    read our own pushed word back as "open"."""
    conn = build_connector("accela", {"agency_name": "A",
                                      "status_map_out": {"in_progress": "Under Review"}}, {})
    assert conn.map_status_in("Under Review") == "in_progress"


def test_an_ambiguous_outbound_word_is_not_reversed():
    conn = build_connector("open311", {"base_url": "https://x.test/v2",
                                       "status_map_out": {"open": "open", "in_progress": "open"}}, {})
    assert conn.map_status_in("open") == "open"


# ---------------------------------------------------------------------------
# The pull, refresh and webhook paths use the rule and notify
# ---------------------------------------------------------------------------

def _source(rel):
    return (BACKEND / rel).read_text()


def test_every_inbound_path_goes_through_the_one_rule():
    tasks = _source("app/tasks/integrations.py")
    pull = tasks[tasks.index("def pull_integration_updates("):]
    pull = pull[:pull.index("@celery_app.task", 1)]
    refresh = tasks[tasks.index("def refresh_request_from_integrations("):]
    refresh = refresh[:refresh.index("@celery_app.task", 1)]
    for block in (pull, refresh):
        assert "_apply_inbound_status(" in block
        assert "sr.status = record.status" not in block, "a path still applies the raw mapped status"
        assert "notify_external_status_change(" in block
    hook = _source("app/api/integrations.py")
    hook = hook[hook.index("async def integration_webhook"):]
    assert "decide_inbound_status(" in hook
    assert "notify_external_status_change(" in hook
    # Notified after the commit, never before.
    assert hook.index("await db.commit()") < hook.index("notify_external_status_change(")


def test_the_notification_is_the_one_a_staff_change_sends(monkeypatch):
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("celery.app")
    import app.tasks.integrations as tasks
    import app.tasks.service_requests as service_requests

    sent = []
    monkeypatch.setattr(tasks, "enqueue", lambda task, *a, **k: sent.append((task, a, k)) or True)
    tasks.notify_external_status_change(42, "open", "Patched.", "Accela")
    assert sent[0][0] is service_requests.send_branded_notification
    assert sent[0][1] == (42, "status_update")
    assert sent[0][2] == {"old_status": "open", "completion_message": "Patched."}
    assert sent[1][0] is service_requests.notify_staff_of_activity
    assert sent[1][1] == (42, "status_changes")


@pytest.mark.asyncio
async def test_apply_inbound_status_records_the_raw_word_and_applies_real_changes():
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("celery.app")
    import app.tasks.integrations as tasks
    from app.integrations.base import ExternalRecord

    class DB:
        def __init__(self):
            self.added = []

        def add(self, row):
            self.added.append(row)

    class Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    conn = build_connector("open311", {"base_url": "https://x.test/v2"}, {})
    integration = Obj(display_name="Tyler")

    # Unchanged "open" from the vendor: local in_progress stays.
    sr = Obj(id=1, status="in_progress", completion_message=None, closed_substatus=None)
    link = Obj(external_status="open")
    db = DB()
    change = await tasks._apply_inbound_status(
        db, sr, link, ExternalRecord(external_id="9", status="open", raw_status="open"),
        conn, integration)
    assert change is None and sr.status == "in_progress" and not db.added

    # Vendor closes it: applied, audited, notification returned.
    change = await tasks._apply_inbound_status(
        db, sr, link, ExternalRecord(external_id="9", status="closed", raw_status="closed",
                                     status_notes="Filled."), conn, integration)
    assert sr.status == "closed"
    assert link.external_status == "closed"
    assert change == (1, "in_progress", "Filled.", True)  # True: recent enough to notify
    assert db.added and db.added[0].new_value == "closed"


# ---------------------------------------------------------------------------
# Service-code maps
# ---------------------------------------------------------------------------

def test_outbound_map_is_explicit_and_the_legacy_key_means_outbound():
    assert service_code_map_out({"service_code_map_out": {"PTH": "101"}}) == {"PTH": "101"}
    assert service_code_map_out({"service_code_map": {"PTH": "101"}}) == {"PTH": "101"}
    # The explicit key wins over the legacy one.
    assert service_code_map_out({"service_code_map_out": {"PTH": "1"},
                                 "service_code_map": {"PTH": "2"}}) == {"PTH": "1"}
    # Blank values are "not mapped", not "map to blank".
    assert service_code_map_out({"service_code_map_out": {"PTH": ""}}) == {}


def test_inbound_map_is_explicit_or_the_outbound_read_backwards():
    assert service_code_map_in({"service_code_map_in": {"Pothole": "PTH"}}) == {"Pothole": "PTH"}
    assert service_code_map_in({"service_code_map_out": {"PTH": "101", "PTH2": "101"}}) == {"101": "PTH"}


def test_an_import_finds_its_category_by_vendor_code_then_name():
    config = {"service_code_map_in": {"101": "PTH", "street light": "LIGHT"}}
    assert local_code_for(config, "101", "Pothole") == "PTH"
    assert local_code_for(config, None, "Street Light") == "LIGHT"
    assert local_code_for(config, "999", "Other") is None


def test_every_category_sending_connector_uses_the_outbound_map():
    conn = build_connector("generic_rest", {"base_url": "https://api.test/v1",
                                            "service_code_map_out": {"PTH": "V-1"}}, {})
    assert conn._build_create_body({"service_code": "PTH"})["category_code"] == "V-1"
    unmapped = conn._build_create_body({"service_code": "OTHER"})
    assert unmapped["category_code"] == "OTHER"


def test_the_import_path_reads_the_inbound_map():
    tasks = _source("app/tasks/integrations.py")
    block = tasks[tasks.index("async def _import_external_record"):]
    block = block[:block.index("\nasync def ", 1)]
    assert "local_code_for(" in block
    assert 'config.get("service_code_map")' not in block


def test_the_mapping_endpoint_saves_explicit_keys_and_retires_the_old_one():
    api = _source("app/api/integrations.py")
    block = api[api.index("async def approve_integration_mapping"):]
    block = block[:block.index("@router.", 1)]
    assert '"service_code_map_out"' in block and '"service_code_map_in"' in block
    assert 'config.pop("service_code_map", None)' in block
    assert "share_pii" in block and "import_new_records" in block
