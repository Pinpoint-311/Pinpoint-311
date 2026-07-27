"""Tests for the official CDC/ATSDR SVI lookup.

The network call can't be exercised here, so these pin the parsing and
sentinel-handling logic — the parts that would silently corrupt a research
dataset if they regressed (notably CDC's -999 "unavailable" marker, which must
never be read as a real percentile).
"""

import pytest

cdc = pytest.importorskip("app.services.cdc_svi")

clean_value = cdc.clean_value
parse_svi_attributes = cdc.parse_svi_attributes
_is_tract_layer = cdc._is_tract_layer


# ---- the -999 sentinel -----------------------------------------------------

def test_missing_sentinel_becomes_none_not_a_score():
    # -999 read as a value would rank every unmeasurable tract as least vulnerable.
    assert clean_value(-999) is None
    assert clean_value("-999") is None
    assert clean_value(-999.0) is None


def test_real_percentiles_pass_through():
    assert clean_value(0.8342) == 0.8342
    assert clean_value("0.5") == 0.5
    assert clean_value(0) == 0.0
    assert clean_value(1) == 1.0


def test_out_of_range_values_rejected():
    # A percentile outside 0-1 isn't a ranking; better absent than wrong.
    assert clean_value(42) is None
    assert clean_value(-0.5) is None


def test_garbage_is_none():
    assert clean_value(None) is None
    assert clean_value("") is None
    assert clean_value("N/A") is None


# ---- attribute parsing -----------------------------------------------------

def test_parses_overall_and_themes():
    rec = parse_svi_attributes({
        "FIPS": "34021000100",
        "RPL_THEMES": 0.7521,
        "RPL_THEME1": 0.61, "RPL_THEME2": 0.42,
        "RPL_THEME3": 0.88, "RPL_THEME4": 0.35,
    })
    assert rec["overall"] == 0.7521
    assert rec["themes"]["socioeconomic_status"] == 0.61
    assert rec["themes"]["racial_ethnic_minority_status"] == 0.88
    assert len(rec["themes"]) == 4


def test_missing_overall_yields_no_record():
    # Without a usable overall value there is nothing trustworthy to report.
    assert parse_svi_attributes({"FIPS": "1", "RPL_THEMES": -999}) is None
    assert parse_svi_attributes({"FIPS": "1"}) is None
    assert parse_svi_attributes({}) is None


def test_partial_themes_do_not_fabricate():
    rec = parse_svi_attributes({"RPL_THEMES": 0.5, "RPL_THEME1": 0.3, "RPL_THEME2": -999})
    assert rec["overall"] == 0.5
    assert rec["themes"] == {"socioeconomic_status": 0.3}   # theme2 omitted, not zeroed


def test_renamed_theme_fields_degrade_gracefully():
    # A CDC field rename should cost sub-scores, not null the whole record.
    rec = parse_svi_attributes({"RPL_THEMES": 0.9, "SOME_NEW_NAME": 0.2})
    assert rec["overall"] == 0.9
    assert rec["themes"] == {}


# ---- layer discovery -------------------------------------------------------

def test_identifies_tract_layer():
    assert _is_tract_layer({"name": "SVI 2022 - United States, tract"}) is True


def test_rejects_county_and_state_layers():
    # Querying county data as if it were tract data would look plausible and be wrong.
    assert _is_tract_layer({"name": "SVI 2022 - United States, county"}) is False
    assert _is_tract_layer({"name": "States"}) is False
    assert _is_tract_layer({}) is False
