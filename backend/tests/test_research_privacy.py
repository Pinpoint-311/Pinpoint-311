"""Tests for research-export privacy and metric correctness.

These cover the fixes made after the data-integrity audit: PII redaction breadth,
keyed zone IDs, k-anonymity small-cell suppression, SVI percentile ranking, and
the corrected audit-log metrics. Pure functions only — no DB, no network.
"""

import pytest

research = pytest.importorskip("app.api.research")

sanitize_description = research.sanitize_description
generate_zone_id = research.generate_zone_id
_suppress_small_tracts = research._suppress_small_tracts
_apply_svi_percentiles = research._apply_svi_percentiles
count_status_changes = research.count_status_changes
days_to_first_staff_action = research.days_to_first_staff_action


# ---- PII redaction ---------------------------------------------------------

def test_redacts_phone_and_email():
    out = sanitize_description("Call 609-555-1234 or email bob@example.com")
    assert "609-555-1234" not in out
    assert "bob@example.com" not in out


def test_redacts_street_address():
    out = sanitize_description("Pothole outside 123 Maple Ave near the school")
    assert "123 Maple Ave" not in out
    assert "[ADDRESS REDACTED]" in out


def test_redacts_untitled_name_after_person_cue():
    out = sanitize_description("Please contact Sarah Whitman about this")
    assert "Sarah Whitman" not in out


def test_redacts_titled_name():
    assert "Smith" not in sanitize_description("Reported by Mr. Smith")


def test_redacts_unit_and_url_and_handle():
    out = sanitize_description("Apt 4B, see https://example.com/x or @janedoe99")
    assert "Apt 4B" not in out
    assert "https://example.com/x" not in out
    assert "@janedoe99" not in out


def test_keeps_ordinary_place_names():
    # Redaction must not eat the research signal — landmarks should survive.
    out = sanitize_description("Broken swing at Maple Park Playground")
    assert "Maple Park Playground" in out


def test_empty_description_is_safe():
    assert sanitize_description("") == ""
    assert sanitize_description(None) == ""


# ---- zone id ---------------------------------------------------------------

def test_zone_id_is_stable_and_grid_based():
    a = generate_zone_id(40.3573, -74.6672)
    b = generate_zone_id(40.3574, -74.6673)   # same ~0.5mi cell
    assert a == b and a.startswith("ZONE-")


def test_zone_id_differs_across_distant_cells():
    assert generate_zone_id(40.35, -74.66) != generate_zone_id(41.90, -73.10)


def test_zone_id_is_not_a_plain_md5_of_coordinates():
    """An unsalted digest would be brute-forceable back to the grid cell."""
    import hashlib
    zone_str = f"{round(40.3573 / 0.007) * 0.007:.3f},{round(-74.6672 / 0.007) * 0.007:.3f}"
    naive = f"ZONE-{hashlib.md5(zone_str.encode()).hexdigest()[:8].upper()}"
    assert generate_zone_id(40.3573, -74.6672) != naive


# ---- k-anonymity -----------------------------------------------------------

def _enrichment(counts: dict) -> dict:
    """Build an enrichment map with `counts` records per tract."""
    out, rid = {}, 0
    for geoid, n in counts.items():
        for _ in range(n):
            rid += 1
            out[rid] = {
                "census_geoid": geoid, "income_band": 3, "population_density": "medium",
                "social_vulnerability_index": 0.5, "housing_tenure_renter_pct": 0.4,
            }
    return out


def test_small_tracts_are_suppressed():
    e = _enrichment({"34021000100": 2})   # below k=5
    _suppress_small_tracts(e)
    row = next(iter(e.values()))
    assert row["census_geoid"] is None
    assert row["social_vulnerability_index"] is None
    assert row["tract_suppressed"] is True


def test_large_tracts_are_retained():
    e = _enrichment({"34021000100": 7})   # at/above k=5
    _suppress_small_tracts(e)
    row = next(iter(e.values()))
    assert row["census_geoid"] == "34021000100"
    assert row["social_vulnerability_index"] == 0.5


def test_suppression_is_per_tract():
    e = _enrichment({"34021000100": 6, "34021000200": 1})
    _suppress_small_tracts(e)
    kept = [r for r in e.values() if r["census_geoid"] == "34021000100"]
    dropped = [r for r in e.values() if r.get("tract_suppressed")]
    assert len(kept) == 6 and len(dropped) == 1


# ---- SVI percentile ranking ------------------------------------------------

def test_svi_is_percentile_ranked_within_export():
    e = {
        1: {"census_geoid": "A", "social_vulnerability_index": 0.10},
        2: {"census_geoid": "B", "social_vulnerability_index": 0.50},
        3: {"census_geoid": "C", "social_vulnerability_index": 0.90},
    }
    _apply_svi_percentiles(e)
    assert e[1]["social_vulnerability_index"] == 0.0    # least vulnerable tract
    assert e[3]["social_vulnerability_index"] == 1.0    # most vulnerable tract


def test_single_tract_keeps_raw_score():
    e = {1: {"census_geoid": "A", "social_vulnerability_index": 0.42}}
    _apply_svi_percentiles(e)
    assert e[1]["social_vulnerability_index"] == 0.42


# ---- corrected audit-log metrics -------------------------------------------

class _Audit:
    def __init__(self, action, actor_type, created_at):
        self.action, self.actor_type, self.created_at = action, actor_type, created_at


class _Req:
    def __init__(self, requested_datetime, audit_logs):
        self.requested_datetime, self.audit_logs = requested_datetime, audit_logs


def test_status_change_count_excludes_other_audit_actions():
    from datetime import datetime
    t = datetime(2026, 7, 1)
    req = _Req(t, [
        _Audit("status_change", "staff", t), _Audit("comment", "staff", t),
        _Audit("status_change", "staff", t), _Audit("department_assigned", "staff", t),
    ])
    assert count_status_changes(req) == 2   # not 4


def test_days_to_first_action_uses_the_earliest_staff_action():
    from datetime import datetime, timedelta
    t = datetime(2026, 7, 1)
    req = _Req(t, [
        _Audit("status_change", "staff", t + timedelta(days=30)),   # much later
        _Audit("comment", "staff", t + timedelta(days=2)),          # the real first
    ])
    assert days_to_first_staff_action(req) == 2.0


def test_days_to_first_action_ignores_resident_actions():
    from datetime import datetime, timedelta
    t = datetime(2026, 7, 1)
    req = _Req(t, [
        _Audit("submitted", "resident", t),
        _Audit("status_change", "staff", t + timedelta(days=3)),
    ])
    assert days_to_first_staff_action(req) == 3.0


def test_days_to_first_action_none_when_untouched():
    from datetime import datetime
    assert days_to_first_staff_action(_Req(datetime(2026, 7, 1), [])) is None
