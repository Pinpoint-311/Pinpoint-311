"""The Spatial Bias detector counted reports and called them reporters.

A town's panel read "7 Total Reports / 7 Unique Reporters / 1.0x" for seven
mapped reports filed by two residents. Two faults, either one enough:

  * `total_unique_reporters` was `len(reporter_points)` -- the number of
    ~100 m grid cells with a report in them, not a count of people.
  * The per-cell de-duplication was `DISTINCT ON (email, ...)` over the
    encrypted email column. AES-GCM with a fresh nonce gives every row its
    own ciphertext, so the same address never matched itself and every
    report was a new "reporter". The cluster query's COUNT(DISTINCT email)
    had the same flaw, so no cluster could ever be flagged.

The fix counts the keyed email fingerprint (resident_email_index), which is
the one stable identifier the database holds, only while the town keeps it;
reports with none are anonymous, not reporters.
"""
import inspect

import pytest

from app.services.reporter_bias import grid, summarise

JANE, JOHN = "a" * 64, "b" * 64


def test_the_reported_case_two_residents_not_seven():
    """Seven mapped reports, each in its own grid cell, by two people."""
    rows = [(40.0 + i * 0.01, -74.0, JANE if i < 4 else JOHN) for i in range(7)]
    out = summarise(rows, identity_available=True)

    assert out["total_reports"] == 7
    assert out["total_unique_reporters"] == 2
    assert out["identified_reports"] == 7
    assert out["anonymous_reports"] == 0
    assert out["identified_reports"] / out["total_unique_reporters"] == 3.5


def test_reporter_total_is_people_not_grid_cells():
    """One resident filing in three places is one reporter, though three
    cells each show a reporter point."""
    rows = [(40.0, -74.0, JANE), (40.1, -74.0, JANE), (40.2, -74.0, JANE)]
    out = summarise(rows, identity_available=True)
    assert out["total_unique_reporters"] == 1
    assert len(out["reporter_points"]) == 3


def test_repeat_reports_in_one_cell_weigh_once():
    rows = [(40.0, -74.0, JANE)] * 5 + [(40.0, -74.0, JOHN)]
    out = summarise(rows, identity_available=True)
    assert out["reporter_points"] == [{"lat": 40.0, "lng": -74.0, "weight": 2}]
    assert len(out["report_points"]) == 6


def test_anonymous_reports_are_reports_but_not_reporters():
    """Each anonymous report used to be a reporter of its own, dragging the
    average toward 1.0x exactly where it matters."""
    rows = [(40.0, -74.0, JANE)] * 3 + [(40.0, -74.0, None), (40.1, -74.0, "")]
    out = summarise(rows, identity_available=True)
    assert out["total_reports"] == 5
    assert out["total_unique_reporters"] == 1
    assert out["identified_reports"] == 3
    assert out["anonymous_reports"] == 2
    assert out["reporter_points"] == [{"lat": 40.0, "lng": -74.0, "weight": 1}]


def test_without_fingerprints_reporters_are_unknown_not_guessed():
    """Resident history off: the town holds no linkable identifier on purpose.
    Any number here would be invented; fingerprints left over from before the
    switch went off are not used either."""
    rows = [(40.0, -74.0, JANE), (40.1, -74.0, JANE), (40.2, -74.0, None)]
    out = summarise(rows, identity_available=False)
    assert out["total_reports"] == 3
    assert out["total_unique_reporters"] is None
    assert out["identified_reports"] is None
    assert out["anonymous_reports"] is None
    assert out["reporter_points"] == []
    assert out["reporter_identity_available"] is False


def test_unmapped_rows_are_skipped():
    out = summarise([(None, -74.0, JANE), (40.0, None, JOHN), (40.0, -74.0, JANE)], True)
    assert out["total_reports"] == 1
    assert out["total_unique_reporters"] == 1


def test_no_identity_leaves_the_payload():
    """Fingerprints are compared, never returned."""
    out = summarise([(40.0, -74.0, JANE)], identity_available=True)
    assert JANE not in repr(out)


@pytest.mark.parametrize("value,expected", [
    (40.0005, 40.001),     # half away from zero, as Postgres ROUND(numeric)
    (-74.0005, -74.001),
    (40.00049, 40.0),
    (40.1234, 40.123),
])
def test_grid_matches_postgres_rounding(value, expected):
    assert grid(value) == expected


def test_payload_fits_the_response_model():
    schemas = pytest.importorskip("app.schemas")
    for available in (True, False):
        out = summarise([(40.0, -74.0, JANE), (40.0, -74.0, None)], available)
        schemas.HeatmapDataResponse(**out)


def test_no_query_counts_reporters_by_the_encrypted_email():
    """Source check, because both queries need Postgres (DISTINCT ON,
    ST_ClusterDBSCAN) and CI runs without it."""
    system = pytest.importorskip("app.api.system")
    src = inspect.getsource(system)
    assert "COUNT(DISTINCT email)" not in src
    assert "DISTINCT ON (COALESCE(email" not in src
    assert "len(reporter_points)" not in src
    assert "COUNT(DISTINCT resident_email_index)" in src
