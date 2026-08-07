"""Locks the staff export and the research export to one shared schema.

Both exports now build rows through research.build_dataset_row, so they cannot
drift apart — schema drift is exactly what produced the documented-vs-actual
mismatches this module was audited for. These tests also pin the privacy
boundary: the research export must never leak operational or PII columns.
"""

from datetime import datetime, timedelta

import pytest

research = pytest.importorskip("app.api.research")

RESEARCH_COLUMNS = research.RESEARCH_COLUMNS
OPERATIONAL_COLUMNS = research.OPERATIONAL_COLUMNS
PII_COLUMNS = research.PII_COLUMNS
build_dataset_row = research.build_dataset_row


class _Comment:
    visibility = "external"


class _Audit:
    def __init__(self, action, actor_type, created_at, new_value=None, old_value=None):
        self.action, self.actor_type, self.created_at = action, actor_type, created_at
        self.new_value, self.old_value = new_value, old_value


def _request():
    t = datetime(2026, 7, 1, 9, 0)
    r = type("Req", (), {})()
    r.id = 1
    r.service_request_id = "REQ-1"
    r.service_code = "pothole"
    r.service_name = "Pothole"
    r.description = "Pothole outside 12 Maple Ave, call Sarah Whitman 609-555-1212"
    r.media_urls = ["a.jpg"]
    r.matched_asset = {"asset_type": "road", "properties": {"install_year": 2001}}
    r.status = "closed"
    r.closed_substatus = "resolved"
    r.priority = 5
    r.address = "12 Maple Ave"
    r.lat, r.long = 40.3573, -74.6672
    r.requested_datetime = t
    r.closed_datetime = t + timedelta(hours=30)
    r.updated_datetime = t + timedelta(hours=30)
    r.audit_logs = [_Audit("status_change", "staff", t + timedelta(hours=2), new_value="in_progress")]
    r.comments = [_Comment()]
    r.source = "resident_portal"
    r.assigned_department_id = 3
    r.ai_analysis = {"priority_score": 7.0}
    r.ai_summary = "Road damage"
    r.ai_analyzed_at = t
    r.manual_priority_score = 8.0
    r.flagged, r.flag_reason = False, None
    r.first_name, r.last_name = "Sarah", "Whitman"
    r.email, r.phone = "s@example.com", "609-555-1212"
    r.assigned_to, r.staff_notes = "jdoe", "dispatched"
    return r


_EQ = {
    "census_geoid": "34021000100", "social_vulnerability_index": 0.72,
    "svi_source": "cdc_svi_official", "housing_tenure_renter_pct": 0.4,
    "income_band": 3, "population_density": "medium",
    "weather": {"precip_24h_mm": 2.1, "temp_max_c": 30.0, "temp_min_c": 20.0, "weather_code": 61},
}


# ---- shared schema ---------------------------------------------------------

def test_research_row_emits_exactly_the_declared_schema():
    row = build_dataset_row(_request(), _EQ, "fuzzed")
    assert set(row) == set(RESEARCH_COLUMNS)


def test_staff_row_is_research_schema_plus_operational():
    row = build_dataset_row(_request(), _EQ, "exact", operational=True)
    assert set(RESEARCH_COLUMNS).issubset(set(row))
    assert set(OPERATIONAL_COLUMNS).issubset(set(row))


def test_staff_row_adds_pii_only_when_requested():
    without = build_dataset_row(_request(), _EQ, "exact", operational=True)
    assert not any(c in without for c in PII_COLUMNS)
    with_pii = build_dataset_row(_request(), _EQ, "exact", operational=True, include_pii=True)
    assert with_pii["reporter_name"] == "Sarah Whitman"


# ---- privacy boundary ------------------------------------------------------

def test_research_export_never_contains_operational_or_pii_columns():
    """The research export is the privacy-preserving one — it must not carry
    exact location, staff notes, or reporter contact details."""
    row = build_dataset_row(_request(), _EQ, "fuzzed")
    for col in list(OPERATIONAL_COLUMNS) + list(PII_COLUMNS):
        assert col not in row, f"{col} leaked into the research export"


def test_research_mode_redacts_and_fuzzes():
    row = build_dataset_row(_request(), _EQ, "fuzzed")
    assert row["latitude"] != 40.3573          # grid-snapped
    # Street name AND house number are withheld now, not just the number.
    assert "Maple" not in row["address_anonymized"]
    # Timestamps coarsen to the day outside exact mode — a full-second
    # timestamp is a quasi-identifier.
    assert row["submitted_datetime"] == "2026-07-01"


def test_free_text_is_deliberately_out_of_the_schema():
    """Pinned schema change (2026-08 hardening): `description_sanitized` and
    `ai_summary_sanitized` were removed on purpose. Pattern redaction over
    resident free text is best-effort, and one miss ships a name or address in
    a file that leaves the building; researchers get description_word_count
    and the derived scores instead. Do not re-add the prose columns."""
    assert "description_sanitized" not in RESEARCH_COLUMNS
    assert "ai_summary_sanitized" not in RESEARCH_COLUMNS
    row = build_dataset_row(_request(), _EQ, "fuzzed")
    assert "description_sanitized" not in row
    assert row["description_word_count"] == len(_request().description.split())


def test_moderation_flag_reason_is_redacted():
    """The wordlist quotes the offending text into the reason, so the reason
    passes through the same PII redaction as any other free text."""
    r = _request()
    r.flagged, r.flag_reason = True, "Auto-flagged: call Sarah Whitman 609-555-1212"
    row = build_dataset_row(r, _EQ, "fuzzed")
    assert "609-555-1212" not in row["moderation_flag_reason"]
    assert "Sarah Whitman" not in row["moderation_flag_reason"]


def test_staff_mode_keeps_operational_detail():
    row = build_dataset_row(_request(), _EQ, "exact", operational=True)
    assert row["latitude"] == 40.3573          # exact for dispatch
    assert row["address_exact"] == "12 Maple Ave"
    assert row["staff_notes"] == "dispatched"
    assert row["description_raw"] == _request().description


# ---- enrichment reaches both -----------------------------------------------

def test_both_modes_carry_the_analytical_enrichment():
    for kwargs in ({}, {"operational": True}):
        row = build_dataset_row(_request(), _EQ, "exact", **kwargs)
        assert row["social_vulnerability_index"] == 0.72
        assert row["svi_source"] == "cdc_svi_official"
        assert row["weather_temp_max_c"] == 30.0
        assert row["time_to_triage_hours"] == 2.0
        assert row["status_change_count"] == 1
