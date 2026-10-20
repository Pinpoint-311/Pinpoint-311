"""Road limits are parsed in linear time, with the old expression's results.

`_LIMITS_RE` paired lazy `[^()]+?` groups with `\\s*`/`\\s+` and backtracked
polynomially: a road name of a few thousand spaces held a worker for minutes
(CodeQL "polynomial regular expression used on uncontrolled data"). Road names
come from imported street data and admin input. The replacement reads each
word once; these pin both properties -- fast on hostile input, and the same
answer as the old expression on ordinary input.
"""
import random
import re
import time

from app.services import road_matching as rm

# The expression that was replaced, kept here only as the reference to agree with.
OLD = re.compile(
    r"^\s*(?P<name>[^()]+?)\s*\(\s*(?:from\s+|between\s+)?(?P<a>[^()]+?)"
    r"\s+(?:to|and|thru|through|-|–|—)\s+(?P<b>[^()]+?)\s*\)\s*$",
    re.IGNORECASE,
)


def old_parse(text):
    m = OLD.match(text)
    if not m or not m.group("name").strip():
        return None
    parts = (m.group("name").strip(), m.group("a").strip(), m.group("b").strip())
    return parts if all(parts) else None


def new_parse(text):
    found = rm._split_limits(text)
    if not found:
        return None
    parts = tuple(p.strip() for p in found)
    return parts if all(parts) else None


def test_ordinary_entries():
    assert new_parse("Jennings Road (Bay Avenue to Route 72)") == ("Jennings Road", "Bay Avenue", "Route 72")
    assert new_parse("Oak Rd (from Elm St to Route 10)") == ("Oak Rd", "Elm St", "Route 10")
    assert new_parse("Oak Rd (between Elm St and Pine St)") == ("Oak Rd", "Elm St", "Pine St")
    assert new_parse("Main St (Smith-Jones Rd - Route 9)") == ("Main St", "Smith-Jones Rd", "Route 9")
    assert new_parse("Main St (A thru B to C)") == ("Main St", "A", "B to C")   # first separator wins
    assert new_parse("Main St (Elm St)") is None
    assert new_parse("Main St") is None
    assert new_parse("(A to B)") is None
    assert rm.parse_road_entry("Oak Rd (Elm St to Route 10)").from_street == "Elm St"
    assert rm.normalize_road_name("Oak Rd (Elm St to Route 10)") == rm.normalize_road_name("Oak Rd")


def test_agrees_with_the_old_expression_on_random_entries():
    rng = random.Random(311)
    words = ["Oak", "Rd", "Elm", "St", "to", "TO", "and", "thru", "through", "-", "–", "—",
             "from", "between", "Route", "72", "Smith-Jones", "(", ")", "  ", "\t"]
    for _ in range(20000):
        text = " ".join(rng.choice(words) for _ in range(rng.randint(0, 9)))
        assert new_parse(text) == old_parse(text), text


def test_hostile_input_is_linear():
    for text in ("a" + " " * 50000 + "(",
                 "x (" + " " * 50000 + "to",
                 "Oak (" + "a to " * 10000,
                 "Oak (a " + " to " * 12000,
                 "'" + " " * 50000):
        start = time.perf_counter()
        rm.parse_road_entry(text)
        rm.normalize_road_name(text)
        assert time.perf_counter() - start < 0.5, text[:20]
