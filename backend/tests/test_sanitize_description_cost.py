"""The research redaction pass has to stay linear in the text it is given.

`sanitize_description` runs over resident-written description text during a
research export. The description field has no maximum length, so the only bound
on it is the 13MB request body limit -- a resident can write a long one, and the
cost of redacting it is paid later by whoever runs the export.

One of the ten patterns in that function was quadratic: the email local part
`[a-zA-Z0-9._%+-]+` could begin at every character of a run of letters, each
start scanning forward to the end of the run. Timed on the pattern alone,
3,000 characters took 14ms and 30,000 took 1,408ms.

This test measures growth rather than naming a deadline, because a wall-clock
limit measures whatever else the machine is doing. Ten times the input on a
linear pass costs roughly ten times as much; the regression costs a hundred
times, and the gap between those is far too wide for load to close.
"""

import time

import pytest

pytest.importorskip("fastapi.routing")

from app.api.research import sanitize_description


def _elapsed(text: str) -> float:
    start = time.perf_counter()
    sanitize_description(text)
    return time.perf_counter() - start


@pytest.mark.parametrize(
    "name,make",
    [
        # A run of local-part characters with the `@` the pattern is hunting for
        # at the far end, which is the shape that was slow.
        ("letters-then-at", lambda n: "a" * n + "@" + "a" * n),
        ("letters", lambda n: "a" * n),
        ("digits", lambda n: "1" * n),
        ("dotted", lambda n: "a." * n),
    ],
)
def test_redaction_cost_grows_with_the_text_not_its_square(name, make):
    small = _elapsed(make(3_000))
    large = _elapsed(make(30_000))
    # A floor on the small measurement, so a fast machine timing near zero
    # cannot turn the ratio into noise.
    small = max(small, 1e-4)
    growth = large / small
    assert growth < 25, (
        f"{name}: 10x the input cost {growth:.0f}x the time "
        f"({small * 1000:.1f}ms -> {large * 1000:.1f}ms); a linear pass is ~10x"
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("mail me at jo.smith+311@town.example.gov please", "mail me at [EMAIL REDACTED] please"),
        ("a@b.co", "[EMAIL REDACTED]"),
        ("two a@b.co and c.d@e.fg", "two [EMAIL REDACTED] and [EMAIL REDACTED]"),
        ("x.y%z-1@sub.domain.org", "[EMAIL REDACTED]"),
        ("no email here", "no email here"),
        ("not.an.email@", "not.an.email@"),
    ],
)
def test_the_fix_did_not_change_what_gets_redacted(text, expected):
    assert sanitize_description(text) == expected
