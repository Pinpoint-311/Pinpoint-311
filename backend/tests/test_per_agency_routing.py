"""Which agency a redirected resident is actually shown.

The routing modal writes one card per agency into `third_party_contacts`, each
carrying its own road list, message and contact details, and separately syncs
the *combined* road names into `exclusion_list` so the coverage map has
something to draw.

Nothing read the per-agency shape. Both resolvers looked for `jurisdictions`,
did not find it, and fell through to the pre-multi-jurisdiction branch, which
reads `exclusion_list` as one nameless agency's roads and hands back
`third_party_contacts` wholesale as its contacts. So a resident reporting a
pothole on a state highway was told "Another agency" and shown the county's
phone number next to the state's -- every agency at once, on every road.
"""

import pytest

from app.services.road_matching import jurisdictions_from_config, resolve_jurisdiction


CONFIG = {
    "third_party_contacts": [
        {
            "name": "State DOT",
            "phone": "555-0100",
            "email": "roads@dot.example.gov",
            "url": "dot.example.gov/report",
            "message": "Route 1 is a state highway.",
            "road_list": "Route 1, Route 130",
        },
        {
            "name": "County DPW",
            "phone": "555-0200",
            "email": "dpw@county.example.gov",
            "url": "county.example.gov",
            "message": "Cranbury Rd is county-maintained.",
            "road_list": "Cranbury Rd",
        },
    ],
    # What the modal syncs for the coverage map -- every road, flattened.
    "exclusion_list": "Route 1, Route 130, Cranbury Rd",
}


def test_each_agency_owns_only_its_own_roads():
    built = jurisdictions_from_config(CONFIG)
    assert [j["name"] for j in built] == ["State DOT", "County DPW"]
    assert built[0]["roads"] == ["Route 1", "Route 130"]
    assert built[1]["roads"] == ["Cranbury Rd"]


def test_a_state_road_shows_only_the_state():
    match = resolve_jurisdiction(CONFIG, "Route 1")
    assert match is not None
    assert match.name == "State DOT"
    assert match.message == "Route 1 is a state highway."
    assert len(match.contacts) == 1, "the county must not appear on a state road"
    assert match.contacts[0]["phone"] == "555-0100"


def test_a_county_road_shows_only_the_county():
    match = resolve_jurisdiction(CONFIG, "Cranbury Rd")
    assert match is not None
    assert match.name == "County DPW"
    assert match.message == "Cranbury Rd is county-maintained."
    assert len(match.contacts) == 1, "the state must not appear on a county road"
    assert match.contacts[0]["phone"] == "555-0200"


def test_the_email_the_clerk_entered_reaches_the_resident():
    """The modal collects an email; the resident-facing payload dropped it."""
    match = resolve_jurisdiction(CONFIG, "Route 1")
    assert match.contacts[0]["email"] == "roads@dot.example.gov"


def test_an_unlisted_road_is_not_redirected():
    assert resolve_jurisdiction(CONFIG, "Elm Street") is None


def test_a_town_claimed_road_beats_an_agency_claim():
    config = dict(CONFIG, inclusion_list="Route 130")
    assert resolve_jurisdiction(config, "Route 130") is None


# ---- the shapes that came before ------------------------------------------

def test_the_explicit_jurisdictions_shape_still_wins():
    config = dict(CONFIG, jurisdictions=[
        {"name": "Turnpike Authority", "roads": ["Route 1"], "message": "", "contacts": []},
    ])
    assert [j["name"] for j in jurisdictions_from_config(config)] == ["Turnpike Authority"]


def test_the_pre_multi_jurisdiction_shape_still_works():
    """Contacts as a plain list with no roads on them: the old single-agency
    config, which must not be mistaken for the per-agency shape."""
    legacy = {
        "exclusion_list": "Route 1",
        "third_party_name": "State DOT",
        "third_party_message": "State highway.",
        "third_party_contacts": [{"name": "State DOT", "phone": "555-0100", "url": ""}],
    }
    match = resolve_jurisdiction(legacy, "Route 1")
    assert match.name == "State DOT"
    assert match.message == "State highway."
    assert match.contacts == [{"name": "State DOT", "phone": "555-0100", "url": ""}]


def test_an_agency_with_no_roads_is_skipped_not_promoted():
    """A half-filled card must not swallow every road via the legacy branch."""
    config = {
        "third_party_contacts": [
            {"name": "Half-filled", "phone": "555-0300"},
            {"name": "County DPW", "phone": "555-0200", "road_list": "Cranbury Rd"},
        ],
        "exclusion_list": "Cranbury Rd",
    }
    built = jurisdictions_from_config(config)
    assert [j["name"] for j in built] == ["County DPW"]


def test_both_resolvers_read_the_config_identically():
    """The spatial resolver had its own copy of this parsing. A resident in the
    portal and the same report phoned in must not get different answers."""
    road_geometry = pytest.importorskip(
        "app.services.road_geometry",  # needs geoalchemy2, absent in CI
    )

    assert road_geometry._jurisdictions(CONFIG) == jurisdictions_from_config(CONFIG)
