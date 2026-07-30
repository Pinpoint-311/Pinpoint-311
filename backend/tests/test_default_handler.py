"""Who handles a road that no rule names.

Normally the town does, and the listed roads are the exceptions. A town can
invert that -- an agency maintains everything and the town keeps only the roads
on its own list -- and the routing UI has offered that choice all along.

It did nothing. The UI stored the literal "third_party"; the resolver looked that
value up against the configured agencies' names and ids, where it never matched,
and fell through to "the municipality handles it". So every road stayed with the
town, which is precisely what selecting the setting was meant to stop.

The spatial resolver -- the one the resident portal actually uses -- did not read
the setting at all, so even a correctly named agency only ever took effect for
reports typed in by address.
"""

import pytest

from app.services.road_matching import default_jurisdiction, resolve_jurisdiction

# road_geometry pulls in geoalchemy2 and SQLAlchemy, which CI does not install.
# Guarded per-test rather than for the module, so the address-path and
# config-check tests -- which need neither -- still run there.
try:
    from app.services.road_geometry import RoadMatch, check_config, choose_road
    HAVE_GEO_STACK = True
except ModuleNotFoundError:  # pragma: no cover - depends on the environment
    HAVE_GEO_STACK = False

needs_geo = pytest.mark.skipif(not HAVE_GEO_STACK, reason="geoalchemy2 not installed")


def _config(default_handler, *, municipal="Elm Street"):
    return {
        "default_handler": default_handler,
        "inclusion_list": municipal,
        "third_party_contacts": [
            {"name": "County DPW", "phone": "555-0200", "road_list": "Cranbury Rd"},
        ],
    }


def road(name, distance=5.0, fid="f1"):
    return RoadMatch(name=name, ref=None, distance_m=distance, segment_id=1,
                     source_feature_id=fid, highway_class="residential",
                     fraction_along=0.5)


# ---- resolving the setting ---------------------------------------------------

def test_the_municipality_is_the_default_default():
    from app.services.road_matching import jurisdictions_from_config
    cfg = _config(None)
    assert default_jurisdiction(cfg, jurisdictions_from_config(cfg)) is None


def test_naming_the_agency_resolves_it():
    from app.services.road_matching import jurisdictions_from_config
    cfg = _config("County DPW")
    resolved = default_jurisdiction(cfg, jurisdictions_from_config(cfg))
    assert resolved and resolved["name"] == "County DPW"


def test_the_legacy_literal_resolves_when_there_is_only_one_agency():
    """Configs saved by the old UI still work, where they are unambiguous."""
    from app.services.road_matching import jurisdictions_from_config
    cfg = _config("third_party")
    resolved = default_jurisdiction(cfg, jurisdictions_from_config(cfg))
    assert resolved and resolved["name"] == "County DPW"


def test_the_legacy_literal_fails_open_with_several_agencies():
    """"A third party" does not say which one. Guessing would hand a resident a
    phone number for a road that agency does not maintain."""
    from app.services.road_matching import jurisdictions_from_config
    cfg = _config("third_party")
    cfg["third_party_contacts"].append(
        {"name": "State DOT", "phone": "555-0100", "road_list": "Route 1"}
    )
    assert default_jurisdiction(cfg, jurisdictions_from_config(cfg)) is None


def test_an_agency_that_no_longer_exists_fails_open():
    from app.services.road_matching import jurisdictions_from_config
    cfg = _config("Renamed Authority")
    assert default_jurisdiction(cfg, jurisdictions_from_config(cfg)) is None


# ---- the address resolver ----------------------------------------------------

def test_an_unlisted_road_goes_to_the_default_agency():
    match = resolve_jurisdiction(_config("County DPW"), "Nowhere Lane")
    assert match is not None and match.name == "County DPW"


def test_the_towns_own_roads_stay_with_the_town():
    assert resolve_jurisdiction(_config("County DPW"), "Elm Street") is None


def test_with_a_municipal_default_an_unlisted_road_is_not_redirected():
    assert resolve_jurisdiction(_config("township"), "Nowhere Lane") is None


# ---- the spatial resolver, which ignored the setting entirely ----------------

@needs_geo
def test_spatially_an_unlisted_road_goes_to_the_default_agency():
    chosen = choose_road([road("Nowhere Lane")], _config("County DPW"))
    assert chosen is not None
    _, claim = chosen
    assert claim is not None and claim[0]["name"] == "County DPW"


@needs_geo
def test_spatially_a_municipal_road_stays_with_the_town():
    chosen = choose_road([road("Elm Street")], _config("County DPW"))
    assert chosen is not None and chosen[1] is None


@needs_geo
def test_spatially_a_municipal_default_redirects_nothing_unlisted():
    chosen = choose_road([road("Nowhere Lane")], _config("township"))
    assert chosen is not None and chosen[1] is None


@needs_geo
def test_a_switched_off_stretch_stays_with_the_town_under_an_agency_default():
    """Turning a stretch off in the coverage map must not hand it away. The
    clerk did that deliberately, and the inverted default would otherwise turn
    every exclusion into the opposite of what was intended."""
    cfg = dict(_config("County DPW"), excluded_segments=["f9"])
    chosen = choose_road([road("Nowhere Lane", fid="f9")], cfg)
    assert chosen is not None and chosen[1] is None


@needs_geo
def test_a_trimmed_stretch_stays_with_the_town_beyond_the_trim():
    cfg = dict(_config("County DPW"), segment_trims={"f1": {"start": 0.0, "end": 0.2}})
    chosen = choose_road([road("Nowhere Lane")], cfg)  # fraction_along = 0.5, past the trim
    assert chosen is not None and chosen[1] is None


@needs_geo
def test_an_off_road_pin_is_never_redirected_by_the_default():
    """No road means no answer, and fail-open beats turning someone away."""
    assert choose_road([], _config("County DPW")) is None


# ---- the clerk is told when the setting cannot take effect -------------------

@needs_geo
def test_an_ambiguous_default_is_flagged():
    cfg = _config("third_party")
    cfg["third_party_contacts"].append(
        {"name": "State DOT", "phone": "555-0100", "road_list": "Route 1"}
    )
    kinds = [i.kind for i in check_config(cfg, [])]
    assert "default_handler_unresolved" in kinds


@needs_geo
def test_a_missing_agency_default_is_flagged():
    kinds = [i.kind for i in check_config(_config("Renamed Authority"), [])]
    assert "default_handler_unresolved" in kinds


@needs_geo
def test_a_resolvable_default_is_not_flagged():
    kinds = [i.kind for i in check_config(_config("County DPW"), [])]
    assert "default_handler_unresolved" not in kinds


@needs_geo
def test_a_municipal_default_is_not_flagged():
    kinds = [i.kind for i in check_config(_config("township"), [])]
    assert "default_handler_unresolved" not in kinds
