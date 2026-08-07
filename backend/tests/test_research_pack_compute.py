"""Pack off = never computed, not computed-then-hidden.

Public-records law makes anything the system generates or saves a requestable
record, regardless of what a column filter later drops from the file. These
tests pin the compute-side enforcement: when an admin switches a research pack
OFF, the expensive/characterizing functions behind it are NOT invoked at all —
no sentiment score over a resident's text, no Census/CDC/ACS call, no weather
lookup — and the pack's row values come back None.

Pure functions only — no DB, no network. External lookups are monkeypatched to
fail loudly if invoked.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

research = pytest.importorskip("app.api.research")

build_dataset_row = research.build_dataset_row
build_equity_map = research.build_equity_map


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
    r.description = "Third time reporting this, still broken. Unacceptable."
    r.media_urls = []
    r.matched_asset = {"asset_type": "road", "properties": {"install_year": 2001}}
    r.status = "closed"
    r.closed_substatus = "resolved"
    r.priority = 5
    r.address = "12 Maple Ave, West Windsor"
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
    r.flagged, r.flag_reason = True, "Auto-flagged: profanity"
    r.first_name, r.last_name = "Sarah", "Whitman"
    r.email, r.phone = "s@example.com", "609-555-1212"
    r.assigned_to, r.staff_notes = "jdoe", "dispatched"
    return r


ALL_ON = {pack_id: True for pack_id in research.RESEARCH_PACKS_DEF}


def _packs(**overrides):
    packs = dict(ALL_ON)
    packs.update(overrides)
    return packs


def _boom(name):
    def fn(*a, **k):
        raise AssertionError(f"{name} was invoked for a switched-off pack")
    return fn


def _async_boom(name):
    async def fn(*a, **k):
        raise AssertionError(f"{name} was invoked for a switched-off pack")
    return fn


# ---- build_equity_map: external calls never leave for an off pack ----------

def test_equity_off_skips_census_cdc_and_acs(monkeypatch):
    monkeypatch.setattr(research, "get_census_tract_geoid", _async_boom("get_census_tract_geoid"))
    monkeypatch.setattr(research, "get_cdc_svi", _async_boom("get_cdc_svi"))
    monkeypatch.setattr(research, "get_social_vulnerability_index",
                        _async_boom("get_social_vulnerability_index"))
    monkeypatch.setattr(research, "get_census_acs_data", _async_boom("get_census_acs_data"))

    weather_calls = []

    async def fake_weather(dt, lat, lng):
        weather_calls.append((lat, lng))
        return {"temp_max_c": 30.0}

    monkeypatch.setattr(research, "get_weather_context", fake_weather)

    out = asyncio.run(build_equity_map([_request()], "fuzzed", _packs(social_equity=False)))

    # Weather (environmental pack, still on) resolved; no Census key present.
    assert out[1]["weather"] == {"temp_max_c": 30.0}
    assert "census_geoid" not in out[1]
    assert weather_calls, "environmental pack is on — weather should still resolve"


def test_environmental_off_skips_weather(monkeypatch):
    monkeypatch.setattr(research, "get_weather_context", _async_boom("get_weather_context"))

    async def fake_geoid(lat, lng):
        return None

    async def fake_cdc(geoid):
        return None

    monkeypatch.setattr(research, "get_census_tract_geoid", fake_geoid)
    monkeypatch.setattr(research, "get_cdc_svi", fake_cdc)

    out = asyncio.run(build_equity_map([_request()], "fuzzed", _packs(environmental_context=False)))
    assert "weather" not in out[1]


def test_both_lookup_packs_off_makes_no_external_call_at_all(monkeypatch):
    for name in ("get_census_tract_geoid", "get_cdc_svi", "get_social_vulnerability_index",
                 "get_census_acs_data", "get_weather_context",
                 "get_income_quintile_from_zone", "get_population_density_category",
                 "get_housing_tenure_mix"):
        monkeypatch.setattr(research, name, _async_boom(name))

    out = asyncio.run(build_equity_map(
        [_request()], "fuzzed", _packs(social_equity=False, environmental_context=False)))
    assert out == {1: {}}


def test_packs_none_still_resolves_everything(monkeypatch):
    """Backward-compat: callers that don't pass packs get the all-on behavior."""
    calls = []

    async def fake_geoid(lat, lng):
        calls.append("census")
        return None

    async def fake_cdc(geoid):
        return None

    async def fake_weather(dt, lat, lng):
        calls.append("weather")
        return {}

    monkeypatch.setattr(research, "get_census_tract_geoid", fake_geoid)
    monkeypatch.setattr(research, "get_cdc_svi", fake_cdc)
    monkeypatch.setattr(research, "get_weather_context", fake_weather)

    asyncio.run(build_equity_map([_request()], "fuzzed"))
    assert "census" in calls and "weather" in calls


# ---- build_dataset_row: characterizations never produced for an off pack ---

def test_sentiment_off_never_runs_the_analyzers(monkeypatch):
    monkeypatch.setattr(research, "analyze_sentiment", _boom("analyze_sentiment"))
    monkeypatch.setattr(research, "detect_trust_indicators", _boom("detect_trust_indicators"))

    row = build_dataset_row(_request(), {}, "fuzzed", packs=_packs(sentiment_trust=False))
    assert row["sentiment_score"] is None
    assert row["is_repeat_report"] is None
    assert row["prior_report_mentioned"] is None
    assert row["frustration_expressed"] is None


def test_sentiment_on_still_scores(monkeypatch):
    called = []
    monkeypatch.setattr(research, "analyze_sentiment", lambda text: called.append(text) or -0.5)
    row = build_dataset_row(_request(), {}, "fuzzed", packs=_packs(sentiment_trust=True))
    assert called and row["sentiment_score"] == -0.5


def test_moderation_off_never_touches_the_stored_flag(monkeypatch):
    # sanitize_description is only reached from the flag_reason path here; the
    # request IS flagged, and the row must not say so when the pack is off.
    monkeypatch.setattr(research, "sanitize_description", _boom("sanitize_description"))
    row = build_dataset_row(_request(), {}, "fuzzed", packs=_packs(moderation=False))
    assert row["moderation_flagged"] is None
    assert row["moderation_flag_reason"] is None


def test_friction_off_never_derives_the_audit_metrics(monkeypatch):
    for name in ("calculate_time_to_triage", "count_reassignments",
                 "is_off_hours_submission", "calculate_escalation_occurred",
                 "count_status_changes", "days_to_first_staff_action",
                 "calculate_business_hours"):
        monkeypatch.setattr(research, name, _boom(name))

    row = build_dataset_row(_request(), {}, "fuzzed", packs=_packs(bureaucratic_friction=False))
    for col in ("time_to_triage_hours", "reassignment_count", "off_hours_submission",
                "escalation_occurred", "total_hours_to_resolve",
                "business_hours_to_resolve", "days_to_first_update", "status_change_count"):
        assert row[col] is None


def test_environmental_off_never_derives_asset_or_season(monkeypatch):
    monkeypatch.setattr(research, "get_matched_asset_attributes", _boom("get_matched_asset_attributes"))
    monkeypatch.setattr(research, "get_asset_age_years", _boom("get_asset_age_years"))
    monkeypatch.setattr(research, "get_season", _boom("get_season"))

    row = build_dataset_row(_request(), {}, "fuzzed", packs=_packs(environmental_context=False))
    for col in ("matched_asset_attributes", "nearby_asset_age_years", "season",
                "weather_precip_24h_mm", "weather_temp_max_c", "weather_temp_min_c",
                "weather_code"):
        assert row[col] is None


def test_ai_pack_off_blanks_the_stored_triage_fields():
    row = build_dataset_row(_request(), {}, "fuzzed", packs=_packs(ai_ml_research=False))
    assert row["ai_priority_score"] is None
    assert row["ai_analyzed"] is None
    assert row["ai_vs_manual_priority_diff"] is None


def test_equity_off_blanks_even_a_prebuilt_map():
    """Belt over braces: if a caller hands in an already-populated equity map,
    the row builder still refuses to carry the fields for an off pack."""
    eq = {"census_geoid": "34021000100", "social_vulnerability_index": 0.72,
          "svi_source": "cdc_svi_official", "housing_tenure_renter_pct": 0.4,
          "income_band": 3, "population_density": "medium"}
    row = build_dataset_row(_request(), eq, "fuzzed", packs=_packs(social_equity=False))
    for col in ("census_tract_geoid", "social_vulnerability_index", "svi_source",
                "housing_tenure_renter_pct", "income_quintile", "population_density"):
        assert row[col] is None


def test_default_packs_none_keeps_all_on_row_behavior():
    row = build_dataset_row(_request(), {}, "fuzzed")
    assert row["sentiment_score"] is not None
    assert row["status_change_count"] == 1
    assert row["ai_analyzed"] is True
    assert row["moderation_flagged"] is True


# ---- schema stays stable: off = None, key still present, filter drops it ---

def test_row_keys_are_stable_regardless_of_pack_state():
    """The DictWriter/columns filter is the disclosure gate; the row builder
    keeps a stable shape so fieldnames never KeyError."""
    all_off = {pack_id: False for pack_id in research.RESEARCH_PACKS_DEF}
    row = build_dataset_row(_request(), {}, "fuzzed", packs=all_off)
    assert set(row) == set(research.RESEARCH_COLUMNS)


def test_staff_export_columns_honor_pack_switches():
    """The admin staff export selects its analytical columns through the same
    allowed_research_columns gate as the research export — a pack switched off
    disappears from that file too, while operational columns are unaffected."""
    class Settings:
        research_packs = {"social_equity": False}

    cols = research.allowed_research_columns(Settings())
    assert "census_tract_geoid" not in cols
    # Operational columns are not pack-governed and are added separately.
    assert not set(research.OPERATIONAL_COLUMNS) & set(research.RESEARCH_COLUMNS)
