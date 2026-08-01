"""Store UTC, show the town's time.

Every timestamp column here is `timestamptz`, so the database returns aware
UTC. The Python side was building naive datetimes, which psycopg interprets in
the database session's timezone -- so on a database not set to UTC, every
written timestamp was silently offset and every number still looked plausible.

The other half is display. "Closed at 02:14" means nothing to a clerk in New
Jersey looking at a report closed just before ten the previous night.
"""

from datetime import datetime, timedelta, timezone

from app.services import town_time as T

JAN = datetime(2026, 1, 15, 15, 30, tzinfo=timezone.utc)   # EST, UTC-5
JUL = datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc)   # EDT, UTC-4


class TestValidation:
    def test_a_real_zone_is_accepted(self):
        assert T.is_valid_timezone("America/New_York")

    def test_nonsense_is_not(self):
        for bad in ("", None, "Mars/Olympus", "EST5EDT_typo", 42):
            assert not T.is_valid_timezone(bad)

    def test_a_bad_stored_value_falls_back_rather_than_raising(self):
        """A bad row must not be able to take the console down. It should show
        UTC and let somebody fix it."""
        assert T.normalise_timezone("Mars/Olympus") == "UTC"
        assert T.normalise_timezone(None) == "UTC"

    def test_the_default_is_what_is_stored_rather_than_a_guess(self):
        """Showing a time that matches the database beats one confidently
        shifted into a zone nobody chose."""
        assert T.DEFAULT_TIMEZONE == "UTC"

    def test_the_shortlist_is_a_shortlist_not_a_restriction(self):
        """A town that needs Guam should not be told it is unsupported."""
        assert T.is_valid_timezone("Pacific/Guam")
        assert "Pacific/Guam" not in T.COMMON_TIMEZONES


class TestConversion:
    def test_it_converts_to_the_town_clock(self):
        assert T.to_town(JAN, "America/New_York").hour == 10

    def test_daylight_saving_is_not_a_fixed_offset(self):
        """The same UTC hour is 10am in January and 11am in July. A stored
        offset would be wrong for half the year."""
        assert T.to_town(JAN, "America/New_York").hour == 10
        assert T.to_town(JUL, "America/New_York").hour == 11

    def test_a_naive_input_is_read_as_utc(self):
        """Which is what a naive datetime means everywhere in this codebase.
        Saying so once beats each caller guessing."""
        assert T.to_town(JAN.replace(tzinfo=None), "America/New_York").hour == 10

    def test_nothing_converts_to_nothing(self):
        assert T.to_town(None, "America/New_York") is None
        assert T.format_town(None, "America/New_York") == ""

    def test_the_instant_itself_does_not_move(self):
        """Converting for display must not change what moment it is."""
        assert T.to_town(JAN, "America/Los_Angeles").timestamp() == JAN.timestamp()

    def test_an_unknown_zone_shows_utc_rather_than_failing(self):
        assert T.to_town(JAN, "Mars/Olympus").hour == 15


class TestOffsetLabel:
    def test_it_is_computed_at_an_instant_not_looked_up(self):
        assert T.offset_label("America/New_York", JAN) == "UTC-05:00"
        assert T.offset_label("America/New_York", JUL) == "UTC-04:00"

    def test_utc_is_zero(self):
        assert T.offset_label("UTC", JAN) == "UTC+00:00"

    def test_a_half_hour_zone_is_not_rounded_away(self):
        assert T.offset_label("Asia/Kolkata", JAN) == "UTC+05:30"


def test_the_codebase_no_longer_builds_naive_timestamps():
    """`datetime.utcnow()` returns a naive value. Written to a `timestamptz`
    column, psycopg interprets it in the session's timezone -- so on a database
    not set to UTC, every timestamp was silently hours out."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        # Parsed rather than grepped. The first version of this searched the
        # text and tripped over its own explanation of the bug sitting in a
        # docstring two files away.
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr == "utcnow":
                offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not offenders, "naive timestamps are back:\n  " + "\n  ".join(offenders)
