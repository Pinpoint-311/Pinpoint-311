"""Data-contract tests for the FOIA/OPRA compliance center.

The admin compliance UI headlines the public-records law and computes the
effective retention period, so these pure lookups must always carry
``public_records_law`` and a consistent day/year relationship.
"""
import importlib

import pytest

# retention_service pulls in SQLAlchemy at import time; skip cleanly in the
# minimal unit env that stubs the DB stack (runs for real in CI).
pytest.importorskip("sqlalchemy")

rs = importlib.import_module("app.services.retention_service")


def test_every_state_has_a_public_records_law():
    states = rs.get_all_states()
    assert states, "expected a non-empty state list"
    for s in states:
        for field in ("code", "name", "retention_days", "retention_years", "source", "public_records_law"):
            assert field in s, f"{s.get('code')} missing {field}"
        assert s["public_records_law"], f"{s['code']} has an empty public_records_law"
        # years is the floor of days/365 and must stay consistent
        assert s["retention_years"] == s["retention_days"] // 365


def test_nj_headlines_opra():
    policy = rs.get_retention_policy("NJ")
    assert policy["state_code"] == "NJ"
    assert "OPRA" in policy["public_records_law"]
    assert policy["retention_days"] > 0
    assert policy["public_records_law"]


def test_unknown_state_falls_back_to_default_policy():
    policy = rs.get_retention_policy("ZZ")
    # Unknown codes resolve to the DEFAULT policy rather than raising.
    assert policy["state_code"] == "DEFAULT"
    assert policy["public_records_law"]
    assert policy["retention_days"] > 0


def test_lowercase_state_code_is_normalized():
    assert rs.get_retention_policy("nj")["state_code"] == "NJ"
