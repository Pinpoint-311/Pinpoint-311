"""Match a detected road name against clerk-configured jurisdiction road lists.

Clerks configure road-based routing by typing road names, which is the right
config surface -- it needs no GIS data and no training. The cost is that a typed
name and a geocoder's name for the same road frequently differ:

    "County Route 516"   vs  "Cranbury Rd"
    "Main St"            vs  "Main Street"
    "N. Broad Street"    vs  "North Broad St"
    "CR-527"             vs  "County Road 527"

So the names are normalized on both sides before comparison, and route numbers
are extracted as their own comparison key. Everything here is a pure function of
its inputs so the behavior is testable without a database or a network call.

The previous implementation substring-matched the configured name against the
entire formatted address ("123 Main Street, Springfield, NJ 07081"), which made
city, county and ZIP part of the match surface -- a list entry of "Union" or
"Springfield" would match the town name and block the whole municipality. Match
against the route component only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Street-type suffixes collapsed to a canonical short form. Both the clerk's
# entry and the geocoder's output are mapped through this, so either spelling
# works in either place.
_SUFFIXES = {
    "street": "st", "st": "st",
    "avenue": "ave", "av": "ave", "ave": "ave",
    "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr",
    "boulevard": "blvd", "blvd": "blvd",
    "lane": "ln", "ln": "ln",
    "court": "ct", "ct": "ct",
    "circle": "cir", "cir": "cir",
    "place": "pl", "pl": "pl",
    "terrace": "ter", "terr": "ter", "ter": "ter",
    "parkway": "pkwy", "pkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy",
    "turnpike": "tpke", "tpke": "tpke", "pike": "pike",
    "trail": "trl", "trl": "trl",
    "way": "way",
    "square": "sq", "sq": "sq",
    "expressway": "expy", "expy": "expy",
    "extension": "ext", "ext": "ext",
}

# Leading/trailing directionals.
_DIRECTIONS = {
    "north": "n", "n": "n",
    "south": "s", "s": "s",
    "east": "e", "e": "e",
    "west": "w", "w": "w",
    "northeast": "ne", "ne": "ne",
    "northwest": "nw", "nw": "nw",
    "southeast": "se", "se": "se",
    "southwest": "sw", "sw": "sw",
}

# Route designators -> canonical prefix. The third element says whether the
# designator names its system. A bare "Route 500" does not: in New Jersey that
# is as likely to be County Route 500 or US 9 as a state highway, and residents,
# clerks and road publishers all write it that way.
_ROUTE_PATTERNS = [
    (re.compile(r"\b(?:county\s+(?:route|road|rte|rd)|cr|co\s+rd)[\s.\-#]*(\d+[a-z]?)\b"), "CR", False),
    (re.compile(r"\b(?:interstate|i)[\s.\-#]*(\d+[a-z]?)\b"), "I", False),
    (re.compile(r"\b(?:us\s*(?:route|highway|hwy|rte)?|u\.s\.)[\s.\-#]*(\d+[a-z]?)\b"), "US", False),
    (re.compile(r"\b(?:state\s+(?:route|highway|hwy|rte)|nj|njsh|sr)[\s.\-#]*(\d+[a-z]?)\b"), "SR", False),
    (re.compile(r"\b(?:route|rte|rt)[\s.\-#]*(\d+[a-z]?)\b"), "SR", True),
]

# A word after the number that makes it a different road: "Route 501 Spur" is
# not Route 501, and must not claim it.
_ROUTE_QUALIFIERS = {
    "spur": "SPUR", "alt": "ALT", "alternate": "ALT", "bus": "BUS",
    "business": "BUS", "truck": "TRUCK", "connector": "CONN", "conn": "CONN",
}


@dataclass(frozen=True)
class _RouteParts:
    system: str
    number: str
    bare: bool

    @property
    def key(self) -> str:
        return f"{self.system}-{self.number}"


def _tokens(value: str) -> List[str]:
    cleaned = re.sub(r"[^\w\s]", " ", value.lower())
    return [t for t in cleaned.split() if t]


def _route_parts(value: str) -> Optional[_RouteParts]:
    """The first numbered route named in `value`, or None.

    First by position, not by pattern order: a ramp named "FR NJ 10 EB to US 1
    NB" leaves Route 10, and used to be read as US 1 because the US pattern was
    tried first.
    """
    if not value:
        return None
    lowered = re.sub(r"[^\w\s.\-#]", " ", value.lower())
    best = None
    for order, (pattern, prefix, bare) in enumerate(_ROUTE_PATTERNS):
        match = pattern.search(lowered)
        if match and (best is None or (match.start(), order) < (best[0].start(), best[1])):
            best = (match, order, prefix, bare)
    if best is None:
        return None
    match, _, prefix, bare = best
    number = match.group(1).upper()
    following = lowered[match.end():].split()
    word = following[0].strip(".") if following else ""
    if word in _ROUTE_QUALIFIERS:
        number = f"{number}-{_ROUTE_QUALIFIERS[word]}"
    return _RouteParts(prefix, number, bare)


def extract_route_key(value: str) -> Optional[str]:
    """Canonical key for a numbered route, or None if it is not one.

    "County Route 516", "CR-516" and "Co Rd 516" all yield "CR-516". The state
    designator is normalized to SR rather than the state's own abbreviation, so
    "NJ 35" and "Route 35" compare equal -- a clerk in one town writes one and
    the geocoder returns the other. A qualifier stays part of the key:
    "Route 501 Spur" is "SR-501-SPUR", a different road from Route 501.
    """
    parts = _route_parts(value)
    return parts.key if parts else None


def routes_match(configured: str, detected: str) -> Optional[bool]:
    """Compare two names as numbered routes. None when either is not one.

    Same number and qualifier, and either the same system or one side written
    with a bare "Route": "Route 9" is US 9 when the data calls it "US Highway
    9", and "Route 500" is County Route 500. Two explicit, different systems
    ("CR 35" and "NJ 35") stay different roads.
    """
    a, b = _route_parts(configured), _route_parts(detected)
    if not a or not b:
        return None
    if a.number != b.number:
        return False
    return a.system == b.system or a.bare or b.bare


# ---- limits on a road entry ------------------------------------------------

# "Oak Road (Elm Street to Route 10)". Whitespace is required around the
# separator so a hyphenated name inside the parentheses survives.
#
# Parsed by hand rather than with one regular expression. The expression this
# replaces -- lazy `[^()]+?` groups next to `\s*` and `\s+` -- backtracked
# polynomially: a few thousand spaces in a road name held a worker for
# minutes, and road names arrive from imported street data and admin input.
# This reads each word once. Same results, including where the stretch
# splits: the first separator word that has a word on each side.
_LIMIT_SEPARATORS = frozenset({"to", "and", "thru", "through", "-", "–", "—"})
_LIMIT_PREFIXES = frozenset({"from", "between"})
_WORD_RE = re.compile(r"\S+")


def _split_limits(text: str) -> Optional[Tuple[str, str, str]]:
    """(name, from, to) for "Name (A to B)", else None. Linear time."""
    s = (text or "").strip()
    if not s.endswith(")") or s.count("(") != 1 or s.count(")") != 1:
        return None
    open_at = s.index("(")
    name = s[:open_at].strip()
    if not name:
        return None
    inner = s[open_at + 1:-1]
    words = list(_WORD_RE.finditer(inner))

    def split(ws):
        for i in range(1, len(ws) - 1):
            if ws[i].group().lower() in _LIMIT_SEPARATORS:
                return (inner[ws[0].start():ws[i - 1].end()],
                        inner[ws[i + 1].start():ws[-1].end()])
        return None

    # "from"/"between" is optional and taken when the rest still splits,
    # as the optional group in the old expression was.
    if words and words[0].group().lower() in _LIMIT_PREFIXES:
        found = split(words[1:])
        if found:
            return (name, *found)
    found = split(words)
    return (name, *found) if found else None


@dataclass(frozen=True)
class RoadEntry:
    """One road on an agency's list, optionally limited to a stretch of it.

    Stored in the routing config as text, "Name (From to To)", so every reader
    of the config and the admin road picker keep working with plain strings.
    A dict ``{name, from_street, to_street}`` is accepted too and read as that
    text.
    """

    name: str
    from_street: Optional[str] = None
    to_street: Optional[str] = None

    @property
    def has_limits(self) -> bool:
        return bool(self.from_street and self.to_street)

    @property
    def label(self) -> str:
        if self.has_limits:
            return f"{self.name} ({self.from_street} to {self.to_street})"
        return self.name


def parse_road_entry(value: Any) -> Optional[RoadEntry]:
    """Read a configured road, with its limits if it has them. None if empty."""
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        if not name:
            return None
        start = str(value.get("from_street") or value.get("from") or "").strip() or None
        end = str(value.get("to_street") or value.get("to") or "").strip() or None
        if not (start and end):
            start = end = None  # one limit alone does not bound anything
        return RoadEntry(name, start, end)
    text = str(value or "").strip()
    if not text:
        return None
    limits = _split_limits(text)
    if limits:
        name, start, end = limits
        return RoadEntry(name.strip(), start.strip(), end.strip())
    return RoadEntry(text)


def road_entry_name(value: Any) -> str:
    """The road itself, without any limits -- what name matching compares."""
    entry = parse_road_entry(value)
    return entry.name if entry else ""


def normalize_road_name(value: str) -> str:
    """Reduce a road name to a comparable form.

    Casefolds, drops punctuation, canonicalizes directionals and street-type
    suffixes. Returns "" for empty or unusable input, which never matches
    anything -- an empty configured entry must not block every road.
    """
    if not value:
        return ""
    # "Oak Rd (Elm St to Route 10)" is Oak Rd; the limits are not
    # part of its name.
    limits = _split_limits(value)
    if limits:
        value = limits[0]
    tokens = _tokens(value)
    if not tokens:
        return ""

    # Leading house number is address noise, not part of the road name.
    if tokens and tokens[0].isdigit():
        tokens = tokens[1:]
    if not tokens:
        return ""

    if tokens[0] in _DIRECTIONS:
        tokens[0] = _DIRECTIONS[tokens[0]]
    if len(tokens) > 1 and tokens[-1] in _DIRECTIONS:
        tokens[-1] = _DIRECTIONS[tokens[-1]]

    tokens = [_SUFFIXES.get(t, t) if i else t for i, t in enumerate(tokens)]
    return " ".join(tokens)


def road_matches(configured: str, detected: str) -> bool:
    """Does a clerk-configured road name refer to the same road as `detected`?

    Numbered routes compare on their route key, so the designator style does not
    matter. Named roads compare on the normalized form. A configured name that
    omits the street type ("Cranbury" for "Cranbury Rd") still matches, because
    clerks routinely leave it off -- but only as a whole-token prefix, so
    "Oak" does not match "Oakwood Ave".
    """
    if not configured or not detected:
        return False
    # Limits say which stretch, not which road. Matching the whole entry read
    # "Oak Rd (Elm St to Route 10)" as Route 10.
    configured = road_entry_name(configured)
    if not configured:
        return False

    same_route = routes_match(configured, detected)
    if same_route is not None:
        return same_route
    # One is a numbered route and the other is not: fall through to name
    # comparison rather than returning False, since a road can be known by both
    # a number and a name and the lists may use either.

    config_norm = normalize_road_name(configured)
    detected_norm = normalize_road_name(detected)
    if not config_norm or not detected_norm:
        return False
    if config_norm == detected_norm:
        return True

    # Whole-token prefix: "cranbury" matches "cranbury rd", not "cranbury" vs
    # "cranburyville rd".
    config_tokens = config_norm.split()
    detected_tokens = detected_norm.split()
    if len(config_tokens) < len(detected_tokens):
        return detected_tokens[: len(config_tokens)] == config_tokens
    return False


@dataclass
class JurisdictionMatch:
    """The jurisdiction responsible for a road, when it is not the municipality."""

    name: str
    message: str
    contacts: List[Dict[str, str]]
    matched_road: str
    matched_entry: str


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        out: List[str] = []
        for v in value:
            if isinstance(v, dict):
                # {name, from_street, to_street} -> "Name (From to To)".
                entry = parse_road_entry(v)
                if entry:
                    out.append(entry.label)
            elif str(v).strip():
                out.append(str(v).strip())
        return out
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _agency_contacts(agency: Dict[str, Any]) -> List[Dict[str, str]]:
    """One agency card becomes one contact block.

    The routing modal collects the contact details flat on the agency itself --
    name, phone, email, url -- rather than as a nested list, so build the list
    the rest of the pipeline expects. An explicit `contacts` list, if a config
    has one, wins.
    """
    explicit = agency.get("contacts")
    if isinstance(explicit, list) and explicit:
        return [c for c in explicit if isinstance(c, dict)]
    entry = {
        key: str(agency.get(key) or "").strip()
        for key in ("name", "phone", "email", "url")
    }
    return [entry] if any(entry.values()) else []


def jurisdictions_from_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every agency in a routing config, each owning only its own roads.

    Three shapes, newest first. This is the single reader for all of them, so
    that the spatial resolver and the address resolver cannot disagree about
    who owns a road -- they did diverge before, and a resident reporting through
    the portal could be told something different from one phoned in.

      1. `jurisdictions`  -- the explicit multi-agency shape.
      2. `third_party_contacts` where the entries carry roads -- what the
         routing modal writes: one card per agency, each with its own road
         list, message and contact details.
      3. the pre-multi-jurisdiction shape -- one unnamed third party owning
         `exclusion_list`.

    Shape 2 previously fell through to shape 3, which read the *combined*
    exclusion_list as one nameless agency's roads and handed back every
    agency's contacts at once. A resident on a state highway was shown the
    county's phone number alongside the state's, under the heading "Another
    agency".
    """
    jurisdictions = config.get("jurisdictions")
    if isinstance(jurisdictions, list) and jurisdictions:
        return [j for j in jurisdictions if isinstance(j, dict)]

    agencies = config.get("third_party_contacts")
    if isinstance(agencies, list):
        built: List[Dict[str, Any]] = []
        for agency in agencies:
            if not isinstance(agency, dict):
                continue
            # `roads` is the normalised array; `road_list` is the raw
            # comma-separated string the input writes as the clerk types.
            roads = _as_list(agency.get("roads")) or _as_list(agency.get("road_list"))
            if not roads:
                continue
            built.append({
                "name": agency.get("name") or "Another agency",
                "roads": roads,
                "message": agency.get("message") or "",
                "contacts": _agency_contacts(agency),
            })
        if built:
            return built

    return _legacy_jurisdictions(config)


def _legacy_jurisdictions(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read the older single-third-party shape as one unnamed jurisdiction.

    Towns configured before multi-jurisdiction support keep working untouched.
    """
    roads = _as_list(config.get("exclusion_list"))
    if not roads:
        return []
    return [
        {
            "name": config.get("third_party_name") or "Another agency",
            "roads": roads,
            "message": config.get("third_party_message") or "",
            "contacts": config.get("third_party_contacts") or [],
        }
    ]


# Values meaning "the town keeps anything nobody else claimed".
MUNICIPAL_DEFAULTS = {"", "municipality", "township", "town", "municipal"}
# The generic literal the routing UI used to write, before it named the agency.
GENERIC_THIRD_PARTY = {"third_party", "thirdparty", "third party", "3rd_party"}


def default_jurisdiction(
    config: Dict[str, Any], jurisdictions: Sequence[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Who owns a road that no rule claims -- None meaning the municipality.

    Normally the town is the default and the listed roads are the exceptions.
    A town can invert that: an agency maintains everything and the town keeps
    only the roads on its own list. That setting existed in the UI and did
    nothing, because it was stored as the literal "third_party" and looked up
    against the configured agencies' names, which never matched. Every road
    fell back to the municipality.

    It is resolved here, once, for both resolvers.

    Ambiguity fails open. "third_party" does not say *which* agency when more
    than one is configured, and guessing would redirect a resident to a phone
    number for a road that agency does not maintain. Naming the agency in the
    setting resolves it; check_config says so.
    """
    raw = config.get("default_handler")
    handler = (raw or "").strip() if isinstance(raw, str) else ""
    if handler.lower() in MUNICIPAL_DEFAULTS:
        return None

    real = [j for j in jurisdictions if isinstance(j, dict)]
    for jurisdiction in real:
        if handler in (jurisdiction.get("id"), jurisdiction.get("name")):
            return jurisdiction

    if handler.lower() in GENERIC_THIRD_PARTY:
        return real[0] if len(real) == 1 else None

    # Named something that is not configured -- a renamed or deleted agency.
    return None


def resolve_jurisdiction(
    config: Optional[Dict[str, Any]], detected_road: str
) -> Optional[JurisdictionMatch]:
    """Which jurisdiction handles `detected_road`, or None if the municipality does.

    Evaluation order:
      1. Roads the municipality explicitly claims win over everything. This is
         the escape hatch for a town-maintained stretch of an otherwise county
         road, and it must be checked first or the county entry would swallow it.
      2. Each configured jurisdiction, in the order the clerk arranged them.
      3. The default handler -- either the municipality (no match, report
         proceeds) or a named jurisdiction that owns everything unlisted.

    Returns None whenever the municipality is responsible, including when no road
    was detected. Failing open is deliberate: a resident must never be blocked
    from reporting because a geocoder returned nothing.
    """
    if not config or not detected_road:
        return None

    for entry in _as_list(config.get("municipal_roads")) or _as_list(
        config.get("inclusion_list")
    ):
        if road_matches(entry, detected_road):
            return None

    jurisdictions = jurisdictions_from_config(config)

    for jurisdiction in jurisdictions:
        if not isinstance(jurisdiction, dict):
            continue
        for entry in _as_list(jurisdiction.get("roads")):
            if road_matches(entry, detected_road):
                return JurisdictionMatch(
                    name=jurisdiction.get("name") or "Another agency",
                    message=jurisdiction.get("message") or "",
                    contacts=jurisdiction.get("contacts") or [],
                    matched_road=detected_road,
                    matched_entry=entry,
                )

    # Nobody claimed this road by name. Under a third-party default that means
    # it belongs to the default agency; normally it means the town.
    fallback = default_jurisdiction(config, jurisdictions)
    if fallback is None:
        return None
    return JurisdictionMatch(
        name=fallback.get("name") or "Another agency",
        message=fallback.get("message") or "",
        contacts=fallback.get("contacts") or [],
        matched_road=detected_road,
        matched_entry="(default -- road not listed as municipal)",
    )
