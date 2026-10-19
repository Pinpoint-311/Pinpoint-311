"""Fuzz target: road-name parsing and matching (backend/app/services/road_matching.py).

Clerks type these road lists into the admin console and geocoders hand back
the other side, so every function here parses untrusted text. The target calls
only the public functions and checks the contracts their docstrings promise.
A slow input is a finding too: pythonfuzz reports any input that runs past its
--timeout, which is how a regex with catastrophic backtracking shows up.
"""
import re

import _harness
from app.services import road_matching as rm

_KEY = re.compile(r"(CR|I|US|SR)-\w+(-[A-Z]+)?")


def _check_one(s: str) -> None:
    entry = rm.parse_road_entry(s)
    if entry is not None:
        assert isinstance(entry, rm.RoadEntry)
        # "None if empty": an entry always names a road.
        assert entry.name and entry.name == entry.name.strip(), entry
        assert isinstance(entry.label, str)
    assert isinstance(rm.road_entry_name(s), str)

    norm = rm.normalize_road_name(s)
    assert isinstance(norm, str)
    assert norm == " ".join(norm.split()), norm

    key = rm.extract_route_key(s)
    assert key is None or _KEY.fullmatch(key), key

    # A name never matches nothing, and an empty entry never matches anything.
    assert rm.road_matches(s, "") is False
    assert rm.road_matches("", s) is False


def fuzz(buf: bytes) -> None:
    s = _harness.text(buf)
    configured, _, detected = s.partition("\n")
    for value in (s, configured, detected):
        _check_one(value)
    assert isinstance(rm.road_matches(configured, detected), bool)
    assert isinstance(rm.routes_match(configured, detected), (bool, type(None)))

    # The same input as the dict form the routing config also accepts.
    fields = s.split("\n")
    entry = rm.parse_road_entry({
        "name": fields[0],
        "from_street": fields[1] if len(fields) > 1 else None,
        "to": fields[2] if len(fields) > 2 else None,
    })
    if entry is not None:
        assert entry.name and entry.name == entry.name.strip(), entry
        # One limit alone does not bound anything.
        assert (entry.from_street is None) == (entry.to_street is None), entry


if __name__ == "__main__":
    _harness.run(fuzz, "road_matching")
