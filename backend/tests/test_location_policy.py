"""Per-category location rules, applied the same way on every intake path."""
import pytest

from app.services import location_policy as lp


def test_unknown_or_missing_mode_reads_as_optional():
    """Optional is how every category behaved before the setting existed."""
    assert lp.normalise_mode(None) == "optional"
    assert lp.normalise_mode("") == "optional"
    assert lp.normalise_mode("bogus") == "optional"
    assert lp.normalise_mode(" Required ") == "required"


def test_required_refuses_a_report_with_no_location():
    with pytest.raises(lp.LocationMissing):
        lp.apply("required", "", None, None)
    with pytest.raises(lp.LocationMissing):
        lp.apply("required", "   ", 40.1, None)  # half a coordinate is not a location


def test_required_accepts_an_address_or_a_pin():
    assert lp.apply("required", "1 Main St", None, None) == ("1 Main St", None, None)
    assert lp.apply("required", None, 40.1, -74.2) == (None, 40.1, -74.2)


def test_staff_intake_is_not_forced_to_have_a_location():
    """A clerk on a phone call may not have one yet."""
    assert lp.apply("required", None, None, None, enforce_required=False) == (None, None, None)


def test_hidden_drops_whatever_was_sent():
    """A location the category does not collect is resident data held for no
    purpose, so it is not stored even if a client sends one."""
    assert lp.apply("hidden", "1 Main St", 40.1, -74.2) == (None, None, None)


def test_a_blank_address_is_stored_as_none():
    """`address == ""` made every location-less report a recurrence of the others."""
    assert lp.apply("optional", "", None, None) == (None, None, None)
    assert lp.apply("optional", "  1 Main St ", None, None) == ("1 Main St", None, None)


def test_road_based_routing_cannot_hide_location():
    with pytest.raises(ValueError):
        lp.validate_routing("hidden", "road_based")
    lp.validate_routing("optional", "road_based")
    lp.validate_routing("hidden", "township")


def test_the_create_paths_apply_the_policy():
    """Read the source: the public form, Open311 clients and staff intake all go
    through location_policy.apply, so no path re-decides the rule."""
    pytest.importorskip("fastapi.routing")
    import inspect
    from app.api import open311

    assert "location_policy.apply(" in inspect.getsource(open311.create_request)
    staff = inspect.getsource(open311.create_manual_intake)
    assert "location_policy.apply(" in staff and "enforce_required=False" in staff


def test_a_blank_address_never_counts_as_a_recurrence():
    pytest.importorskip("sqlalchemy")
    import inspect
    from app.services import vertex_ai_service

    src = inspect.getsource(vertex_ai_service.get_historical_context)
    assert "ServiceRequest.address == address," not in src
    assert "false()" in src
