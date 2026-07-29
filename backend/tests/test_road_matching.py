"""Tests for road-name matching and jurisdiction resolution.

Two failure directions matter and they are not symmetric:

  * A false NEGATIVE misroutes a ticket. A clerk reassigns it.
  * A false POSITIVE blocks a resident from reporting a real problem, and they
    have no recourse -- there is no override.

So the tests lean hardest on the false-positive side.
"""

import pytest

rm = pytest.importorskip("app.services.road_matching")

normalize = rm.normalize_road_name
matches = rm.road_matches
route_key = rm.extract_route_key
resolve = rm.resolve_jurisdiction


# ---- normalization ---------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Main St", "Main Street"),
    ("N. Broad Street", "North Broad St"),
    ("Cranbury Rd", "cranbury road"),
    ("Washington Ave", "WASHINGTON AVENUE"),
    ("Sunset Blvd.", "Sunset Boulevard"),
    ("Oak Ln", "Oak Lane"),
    ("Lincoln Hwy", "Lincoln Highway"),
])
def test_spelling_variants_normalize_together(a, b):
    assert normalize(a) == normalize(b)
    assert matches(a, b) and matches(b, a)


def test_house_number_is_stripped():
    """Geocoders hand back "123 Main St"; the list says "Main St"."""
    assert normalize("123 Main St") == normalize("Main St")


def test_empty_input_normalizes_to_empty():
    for value in ("", "   ", None):
        assert normalize(value) == ""


def test_empty_configured_entry_never_matches():
    """A blank row in the admin list must not block every road in town."""
    assert matches("", "Main St") is False
    assert matches("   ", "Main St") is False
    assert matches("Main St", "") is False


# ---- numbered routes -------------------------------------------------------

@pytest.mark.parametrize("value", [
    "County Route 516", "County Road 516", "CR 516", "CR-516", "Co Rd 516", "cr516",
])
def test_county_route_designators_collapse(value):
    assert route_key(value) == "CR-516"


def test_state_route_designators_collapse():
    for value in ("NJ 35", "Route 35", "State Highway 35", "SR 35", "Rt 35"):
        assert route_key(value) == "SR-35"


def test_route_letter_suffix_preserved():
    assert route_key("CR 516A") == "CR-516A"


def test_different_route_numbers_do_not_match():
    assert matches("CR 516", "CR 517") is False


def test_same_number_different_system_does_not_match():
    """CR 35 and NJ 35 are different roads that happen to share a number."""
    assert matches("CR 35", "NJ 35") is False


def test_named_road_is_not_a_route():
    assert route_key("Main Street") is None


# ---- false positives -------------------------------------------------------

def test_prefix_match_requires_whole_tokens():
    """"Oak" must not match "Oakwood" -- that would block the wrong street."""
    assert matches("Oak", "Oakwood Ave") is False
    assert matches("Oak St", "Oakwood Ave") is False


def test_bare_name_matches_its_own_road_with_suffix():
    """Clerks routinely omit the street type."""
    assert matches("Cranbury", "Cranbury Rd") is True


def test_longer_configured_name_does_not_match_shorter_road():
    assert matches("Main Street Extension", "Main St") is False


def test_distinct_roads_sharing_a_word_do_not_match():
    assert matches("Church St", "Churchill Rd") is False
    assert matches("Park Ave", "Parkway Dr") is False


# ---- jurisdiction resolution ----------------------------------------------

COUNTY = {
    "name": "Middlesex County",
    "roads": ["CR 516", "Cranbury Rd"],
    "message": "County roads are maintained by Middlesex County.",
    "contacts": [{"name": "County DPW", "phone": "555-0100", "url": ""}],
}
STATE = {
    "name": "NJDOT",
    "roads": ["NJ 18"],
    "message": "State highways are maintained by NJDOT.",
    "contacts": [],
}


def test_no_config_never_blocks():
    assert resolve(None, "Main St") is None
    assert resolve({}, "Main St") is None


def test_undetected_road_never_blocks():
    """Failing open is the whole point -- a silent geocoder must not block."""
    assert resolve({"jurisdictions": [COUNTY]}, "") is None
    assert resolve({"jurisdictions": [COUNTY]}, None) is None


def test_matching_road_returns_its_jurisdiction():
    match = resolve({"jurisdictions": [COUNTY, STATE]}, "County Route 516")
    assert match is not None
    assert match.name == "Middlesex County"
    assert "Middlesex" in match.message
    assert match.contacts[0]["phone"] == "555-0100"


def test_the_right_jurisdiction_is_selected_among_several():
    match = resolve({"jurisdictions": [COUNTY, STATE]}, "Route 18")
    assert match is not None and match.name == "NJDOT"


def test_unlisted_road_is_municipal():
    assert resolve({"jurisdictions": [COUNTY, STATE]}, "Elm Street") is None


def test_municipal_roads_win_over_a_jurisdiction_entry():
    """A town-maintained stretch of an otherwise county road."""
    config = {"jurisdictions": [COUNTY], "municipal_roads": ["Cranbury Rd"]}
    assert resolve(config, "Cranbury Road") is None


def test_default_handler_blocks_unlisted_roads_when_named():
    config = {"jurisdictions": [COUNTY], "default_handler": "Middlesex County",
              "municipal_roads": ["Elm St"]}
    assert resolve(config, "Elm Street") is None            # explicitly municipal
    match = resolve(config, "Some Unlisted Rd")             # everything else
    assert match is not None and match.name == "Middlesex County"


def test_default_handler_naming_a_missing_jurisdiction_fails_open():
    """A broken config must not block the whole town."""
    config = {"jurisdictions": [COUNTY], "default_handler": "Nonexistent Agency"}
    assert resolve(config, "Elm Street") is None


def test_matched_entry_is_reported_for_diagnosis():
    match = resolve({"jurisdictions": [COUNTY]}, "Cranbury Road")
    assert match.matched_entry == "Cranbury Rd"
    assert match.matched_road == "Cranbury Road"


# ---- backward compatibility ------------------------------------------------

def test_legacy_exclusion_list_still_blocks():
    """Towns configured before multi-jurisdiction support must keep working."""
    legacy = {
        "default_handler": "township",
        "exclusion_list": ["CR 516"],
        "third_party_message": "Call the county.",
        "third_party_contacts": [{"name": "County", "phone": "555-0111"}],
    }
    match = resolve(legacy, "County Route 516")
    assert match is not None
    assert match.message == "Call the county."
    assert match.contacts[0]["phone"] == "555-0111"


def test_legacy_inclusion_list_is_treated_as_municipal_roads():
    legacy = {"default_handler": "township", "inclusion_list": ["Main St"],
              "jurisdictions": [COUNTY]}
    assert resolve(legacy, "Main Street") is None


def test_comma_separated_string_lists_are_accepted():
    """The admin UI edits these as free text before splitting."""
    config = {"jurisdictions": [{"name": "County", "roads": "CR 516, Cranbury Rd"}]}
    assert resolve(config, "Cranbury Rd") is not None
