"""What a check found has to outlive the browser session that ran it.

Two gaps, both invisible until you reload.

A failing check kept its message in `last_error`. A passing one kept a
timestamp and nothing else, so the card could say "checked 6 hours ago" and not
what it found -- and the evidence is the useful half.

Worse, a provider that cannot be checked from here at all recorded nothing. On
reload the card reverted to "not checked yet", which invites somebody to press
a button that can never succeed, and makes a genuinely unchecked connector look
identical to one that is unverifiable by nature.
"""

from datetime import datetime, timezone

import pytest

from app.services import connector_health as ch


class Row:
    """Stands in for the ORM row. Attribute assignment is the whole contract."""

    def __init__(self, **kw):
        self.connector = "sms"
        self.provider = None
        self.last_attempt_at = None
        self.last_success_at = None
        self.last_error_at = None
        self.last_error = None
        self.last_result = None
        self.verifiable = None
        self.consecutive_failures = 0
        self.total_successes = 0
        self.total_failures = 0
        self.alerted_level = None
        self.alerted_at = None
        for k, v in kw.items():
            setattr(self, k, v)


class FakeDB:
    def __init__(self, row):
        self.row = row
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture(autouse=True)
def _row(monkeypatch):
    row = Row()

    async def fake_row(db, connector):
        return row

    monkeypatch.setattr(ch, "_row", fake_row)
    return row


@pytest.mark.asyncio
async def test_a_passing_check_keeps_what_it_said(_row):
    await ch.record_success(FakeDB(_row), "sms", detail="Twilio credentials accepted. Nothing was sent.")
    assert _row.last_result == "Twilio credentials accepted. Nothing was sent."
    assert _row.verifiable is True
    assert _row.last_success_at is not None


@pytest.mark.asyncio
async def test_a_passing_check_with_nothing_to_say_stores_nothing(_row):
    """An empty string in the column would render as a blank line under the
    card, which reads as a missing value rather than as no comment."""
    await ch.record_success(FakeDB(_row), "sms", detail="")
    assert _row.last_result is None


@pytest.mark.asyncio
async def test_a_failing_check_keeps_its_message_in_both_places(_row):
    await ch.record_failure(FakeDB(_row), "sms", "401 rejected")
    assert _row.last_error == "401 rejected"
    assert _row.last_result == "401 rejected"
    assert _row.verifiable is True


@pytest.mark.asyncio
async def test_unverifiable_is_recorded_rather_than_dropped(_row):
    await ch.record_unverifiable(FakeDB(_row), "sms", "There is no way to check http without sending a real text.")
    assert _row.verifiable is False
    assert "no way to check" in _row.last_result
    assert _row.last_attempt_at is not None


@pytest.mark.asyncio
async def test_unverifiable_moves_neither_counter(_row):
    """It is not evidence either way. Letting it count as a failure would feed
    the escalation that emails administrators about a connector nobody can do
    anything about."""
    await ch.record_unverifiable(FakeDB(_row), "sms", "cannot check")
    assert _row.consecutive_failures == 0
    assert _row.total_failures == 0
    assert _row.total_successes == 0
    assert _row.last_success_at is None
    assert _row.last_error_at is None


@pytest.mark.asyncio
async def test_a_later_real_result_replaces_the_unverifiable_one(_row):
    """A town that switches from an HTTP gateway to Twilio must not keep being
    told its text messages cannot be tested."""
    await ch.record_unverifiable(FakeDB(_row), "sms", "cannot check")
    await ch.record_success(FakeDB(_row), "sms", detail="Twilio accepted")
    assert _row.verifiable is True
    assert _row.last_result == "Twilio accepted"


@pytest.mark.asyncio
async def test_a_long_provider_message_is_bounded(_row):
    await ch.record_success(FakeDB(_row), "sms", detail="x" * 5000)
    assert len(_row.last_result) <= 500


def test_the_snapshot_carries_both_fields():
    """Stored and not surfaced is the same as not stored."""
    h = ch.to_health(Row(last_result="all good", verifiable=False,
                         last_success_at=datetime.now(timezone.utc)))
    assert h.last_result == "all good"
    assert h.verifiable is False


def test_a_row_from_before_the_migration_does_not_explode():
    class Old:
        connector = "sms"
        status = "unknown"

    h = ch.to_health(Old())
    assert h.last_result is None and h.verifiable is None


def test_the_endpoint_returns_them():
    from pathlib import Path

    api = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    assert '"last_result": h.last_result' in api
    assert '"verifiable": h.verifiable' in api


def test_the_test_endpoint_records_the_unverifiable_case():
    from pathlib import Path

    api = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    assert "record_unverifiable" in api


def test_nothing_saved_is_not_recorded_as_unverifiable():
    """"You have entered nothing" is not "this cannot be checked". Recording it
    would make an empty provider permanently untestable-looking."""
    from pathlib import Path

    api = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    assert 'outcome.get("configured") is not False' in api
