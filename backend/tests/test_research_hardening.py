"""Tests for the research-portal hardening pass.

Covers the privacy boundary this pass drew: unlisted reports stay out of every
research query, per-pack switches are enforced at column selection, exact
coordinates never leave for external lookups, staff analytics-chat context is
minimized, and every staff bulk export leaves an audit trace.
Pure functions only — no DB, no network.
"""

import asyncio
from datetime import date, datetime

import pytest

research = pytest.importorskip("app.api.research")


# ---- unlisted reports stay out --------------------------------------------

def test_research_queries_filter_unlisted_reports():
    """A resident who asked for off-the-map asked for off-the-CSV too. Every
    research query builds its WHERE clause from this one function."""
    conditions = research.research_visibility_conditions()
    rendered = [str(c) for c in conditions]
    assert any("is_public" in c for c in rendered), rendered
    assert any("deleted_at" in c for c in rendered), rendered


# ---- pack switches ---------------------------------------------------------

def test_liability_packs_default_off():
    """Sentiment/trust and moderation fields are town-authored characterizations
    of residents' messages — they ship only when an admin enables them."""
    cols = research.allowed_research_columns(None)
    for col in ("sentiment_score", "is_repeat_report", "prior_report_mentioned",
                "frustration_expressed", "moderation_flagged", "moderation_flag_reason"):
        assert col not in cols, f"{col} shipped without an explicit opt-in"


def test_analytical_packs_default_on():
    """Absent key = pack default: an upgrade must not silently strip the
    equity/weather/friction fields a town already relies on."""
    cols = research.allowed_research_columns(None)
    for col in ("census_tract_geoid", "weather_temp_max_c", "time_to_triage_hours",
                "ai_priority_score"):
        assert col in cols


def test_pack_off_removes_its_columns_and_only_its_columns():
    class Settings:
        research_packs = {"social_equity": False}

    cols = research.allowed_research_columns(Settings())
    for col in ("census_tract_geoid", "social_vulnerability_index", "svi_source",
                "housing_tenure_renter_pct", "income_quintile", "population_density"):
        assert col not in cols
    # Core identification/timing columns always ship.
    for col in ("request_id", "status", "submitted_datetime", "zone_id"):
        assert col in cols


def test_liability_pack_can_be_enabled_deliberately():
    class Settings:
        research_packs = {"sentiment_trust": True}

    cols = research.allowed_research_columns(Settings())
    assert "sentiment_score" in cols
    assert "moderation_flagged" not in cols  # the other one stays off


def test_every_pack_label_in_dictionary_is_defined():
    """A COLUMN_DICTIONARY row naming a pack that has no switch would ship
    unconditionally by accident."""
    known = {meta["label"] for meta in research.RESEARCH_PACKS_DEF.values()} | {"Core"}
    for name, _t, _d, pack in research.COLUMN_DICTIONARY:
        assert pack in known, f"{name} names unknown pack {pack!r}"


# ---- fuzz before egress ----------------------------------------------------

def test_external_lookups_receive_snapped_coordinates(monkeypatch):
    """The Census geocoder and weather API must see the ~100ft-snapped point,
    never the raw one — in every privacy mode, exact included."""
    received = {}

    async def fake_geoid(lat, lng):
        received["census"] = (lat, lng)
        return None

    async def fake_cdc(geoid):
        return None

    async def fake_weather(dt, lat, lng):
        received["weather"] = (lat, lng)
        return {}

    monkeypatch.setattr(research, "get_census_tract_geoid", fake_geoid)
    monkeypatch.setattr(research, "get_cdc_svi", fake_cdc)
    monkeypatch.setattr(research, "get_weather_context", fake_weather)

    req = type("Req", (), {})()
    req.id, req.lat, req.long = 1, 40.35731, -74.66729
    req.requested_datetime = datetime(2026, 7, 1, 9, 0)

    asyncio.run(research.build_equity_map([req], "exact"))

    snapped = research.fuzz_location(40.35731, -74.66729)
    assert received["census"] == snapped
    assert received["census"] != (40.35731, -74.66729)
    assert received["weather"] == snapped


# ---- quasi-identifier coarsening --------------------------------------------

def test_fuzzed_address_drops_the_street_name():
    out = research.anonymize_address("123 Main Street, West Windsor", "fuzzed")
    assert "Main" not in out and "123" not in out
    assert out == "Block near West Windsor"


def test_fuzzed_address_without_locality_withholds_everything():
    assert research.anonymize_address("123 Main Street", "fuzzed") == "Block (street withheld)"


def test_exact_address_is_unchanged_for_admins():
    assert research.anonymize_address("123 Main Street, West Windsor", "exact") == \
        "123 Main Street, West Windsor"


# ---- staff analytics-chat minimization --------------------------------------

system = pytest.importorskip("app.api.system")


def test_staff_names_become_stable_role_labels():
    labels = system.staff_role_labels({"walt", "ada", "grace"})
    assert set(labels.values()) == {"staff member 1", "staff member 2", "staff member 3"}
    # Sorted numbering: the same roster always maps the same way, so the
    # labels cross-reference between the workload and resolution tables.
    assert labels == system.staff_role_labels(["grace", "ada", "walt"])
    assert labels["ada"] == "staff member 1"


def test_chat_address_anonymization_is_block_level():
    """The analytics chat sends addresses through the research module's fuzzed
    form — no house number, no street name."""
    out = research.anonymize_address("45 Elm Street, Princeton Junction", "fuzzed")
    assert "Elm" not in out and "45" not in out
    assert "Princeton Junction" in out


# ---- staff bulk export audit -------------------------------------------------

data_export = pytest.importorskip("app.api.data_export")


def test_export_audit_details_record_scope_not_contents():
    details = data_export.export_audit_details(
        format="csv", row_count=42,
        start_date=datetime(2026, 1, 1), end_date=None,
        status="open", service_code=None, include_pii=False,
    )
    assert details["row_count"] == 42
    assert details["include_pii"] is False
    assert details["operational_columns"] is True
    assert details["filters"] == {
        "start_date": "2026-01-01T00:00:00",
        "end_date": None,
        "status": "open",
        "service_code": "all",
    }
    # Never record contents: the details must be exactly scope metadata.
    assert set(details) == {"format", "row_count", "filters", "include_pii", "operational_columns"}
