"""Whether a service category asks for a location, and what that means on intake.

Three answers, chosen per category by an administrator:

    required       a pin or an address must be given; the report is refused
                   without one
    optional       the map is offered and can be skipped (what every category
                   did before this setting existed, so it is the default)
    hidden         no map on the form, and a location sent anyway is dropped --
                   a records request or a general question has no "where", and
                   a stored address there is resident data held for no purpose

One module, so every intake path (the resident form via Open311 POST, staff
manual intake, inbound connectors) applies the same rule rather than each
re-deciding it.

The blank address is normalised to None here too. The resident form sends
`address: ""` when nothing was picked, and the AI recurrence check matches on
`ServiceRequest.address == address` -- so every location-less report in a
category counted as a repeat at the same "address" as all the others. Storing
None instead means "no location" never equals anything.
"""
from typing import Optional, Tuple

REQUIRED = "required"
OPTIONAL = "optional"
HIDDEN = "hidden"

LOCATION_MODES = (REQUIRED, OPTIONAL, HIDDEN)
DEFAULT_MODE = OPTIONAL


class LocationMissing(ValueError):
    """The category requires a location and none was given."""


def normalise_mode(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    return v if v in LOCATION_MODES else DEFAULT_MODE


def clean_address(address: Optional[str]) -> Optional[str]:
    if address is None:
        return None
    stripped = address.strip()
    return stripped or None


def has_location(address: Optional[str], lat: Optional[float], long: Optional[float]) -> bool:
    return bool(clean_address(address)) or (lat is not None and long is not None)


def apply(
    mode: Optional[str],
    address: Optional[str],
    lat: Optional[float],
    long: Optional[float],
    *,
    enforce_required: bool = True,
) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """Return the (address, lat, long) to store for a category in `mode`.

    `enforce_required=False` is for staff intake: a clerk taking a phone call
    may not have a location yet and is trusted to judge that, whereas a public
    submission without one for a category that needs one is simply incomplete.
    """
    mode = normalise_mode(mode)
    address = clean_address(address)
    if lat is None or long is None:
        # Half a coordinate is not a location; keep neither rather than store
        # a point on the equator or the prime meridian.
        lat, long = None, None

    if mode == HIDDEN:
        return None, None, None
    if mode == REQUIRED and enforce_required and not has_location(address, lat, long):
        raise LocationMissing("This category needs a location. Pick a spot on the map or enter an address.")
    return address, lat, long


def validate_routing(mode: Optional[str], routing_mode: Optional[str]) -> None:
    """Road-based routing decides from the pin, so it cannot run without one."""
    if normalise_mode(mode) == HIDDEN and (routing_mode or "") == "road_based":
        raise ValueError(
            "Road-based routing needs a location, so this category cannot be set to "
            "'Not collected'. Choose Optional or Required, or change the routing first."
        )
