"""When something breaks, somebody is told -- once.

The daily sweep already found the failures. What it did with them was write a
row and a log line, which for a self-hosted town is the same as nothing: the
software knew on Tuesday and the clerk found out on Monday, from a resident who
never got their confirmation email.

Two ways to get this wrong, and the second is the one that actually happens.
Silence is the obvious failure. The other is an email every morning saying the
same thing, which is filtered into a folder within a fortnight -- and then the
one that mattered is in the folder too. So the rules under test are as much
about *not* sending as about sending.

No database, no mail server and no FastAPI here: the decisions are pure, which
is the only reason they can be checked at all in CI.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import connector_alerts as A


NOW = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)


class FakeHealth:
    """Enough of a health row for the planner. Mirrors connector_health.Health."""

    def __init__(self, connector, status, *, alerted_level=None, alerted_at=None,
                 last_error=None, last_success_at=None):
        self.connector = connector
        self.status = status
        self.alerted_level = alerted_level
        self.alerted_at = alerted_at
        self.last_error = last_error
        self.last_success_at = last_success_at

    def summary(self):
        return f"{self.status} summary"


# ---------------------------------------------------------------------------
# Which states are worth an email
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,expected", [
    ("working", A.HEALTHY),
    ("unknown", A.HEALTHY),
    ("failing", A.AT_RISK),
    ("stale", A.AT_RISK),
    ("down", A.BROKEN),
])
def test_the_status_maps_onto_a_level(status, expected):
    assert A.alert_level(status) == expected


def test_stale_is_a_warning_and_not_health():
    """No successful call in over a week is not "fine".

    It is the exact state a revoked key produces on a connector nobody has
    exercised, and treating it as healthy is how an expired credential survives
    until the morning somebody needs it.
    """
    assert A.alert_level("stale") == A.AT_RISK


def test_the_first_failed_call_is_the_alert_worth_having():
    """A clerk told on the first failure has days to renew a secret. A clerk
    told once sign-in is fully down is being informed of an outage they are
    already standing in."""
    assert A.alert_level("failing") == A.AT_RISK
    assert A.alert_level("down") == A.BROKEN


# ---------------------------------------------------------------------------
# When to actually send
# ---------------------------------------------------------------------------

def test_a_connector_that_has_always_worked_generates_nothing():
    assert A.decide(level=A.HEALTHY, previous_level=None, alerted_at=None, now=NOW) is None


def test_a_new_problem_is_announced():
    assert A.decide(level=A.AT_RISK, previous_level=None, alerted_at=None, now=NOW) == "new"


def test_getting_worse_is_announced_again():
    assert A.decide(level=A.BROKEN, previous_level=A.AT_RISK,
                    alerted_at=NOW - timedelta(hours=1), now=NOW) == "escalated"


def test_the_same_problem_tomorrow_is_not_mentioned_again():
    """This is the whole reason the state columns exist. Daily repetition of an
    unchanged fact is how an alert channel becomes a folder."""
    assert A.decide(level=A.BROKEN, previous_level=A.BROKEN,
                    alerted_at=NOW - timedelta(days=1), now=NOW) is None


def test_a_problem_still_there_a_week_later_is_mentioned_again():
    assert A.decide(level=A.BROKEN, previous_level=A.BROKEN,
                    alerted_at=NOW - timedelta(days=7), now=NOW) == "reminder"


def test_partial_improvement_is_not_worth_an_email():
    """"Good news, it is now only intermittently broken" is not news."""
    assert A.decide(level=A.AT_RISK, previous_level=A.BROKEN,
                    alerted_at=NOW - timedelta(days=1), now=NOW) is None


def test_recovery_is_worth_an_email_but_only_if_we_complained():
    assert A.decide(level=A.HEALTHY, previous_level=A.BROKEN,
                    alerted_at=NOW - timedelta(days=1), now=NOW) == "recovered"
    assert A.decide(level=A.HEALTHY, previous_level=A.HEALTHY,
                    alerted_at=None, now=NOW) is None


def test_a_missing_timestamp_errs_towards_sending():
    """A duplicate email is a smaller failure than a silent outage."""
    assert A.decide(level=A.BROKEN, previous_level=A.BROKEN, alerted_at=None, now=NOW) == "reminder"


def test_a_naive_timestamp_does_not_explode():
    """Some databases hand back timestamps without a timezone. Subtracting one
    of those from an aware `now` raises, and it would raise inside the daily
    sweep -- taking the health write with it."""
    naive = (NOW - timedelta(days=9)).replace(tzinfo=None)
    assert A.decide(level=A.BROKEN, previous_level=A.BROKEN, alerted_at=naive, now=NOW) == "reminder"


# ---------------------------------------------------------------------------
# Planning across connectors
# ---------------------------------------------------------------------------

def test_only_the_connectors_that_changed_are_in_the_plan():
    healths = [
        FakeHealth("email", "working"),
        FakeHealth("identity", "down"),
        FakeHealth("sms", "down", alerted_level=A.BROKEN, alerted_at=NOW - timedelta(days=1)),
    ]
    plan = A.plan(healths, now=NOW)
    assert [a.connector for a in plan] == ["identity"]


def test_the_worst_thing_is_first():
    healths = [
        FakeHealth("translation", "failing"),
        FakeHealth("identity", "down"),
    ]
    plan = A.plan(healths, now=NOW)
    assert [a.connector for a in plan] == ["identity", "translation"]


def test_a_row_with_no_alert_state_is_treated_as_never_alerted():
    class Bare:
        connector = "ai"
        status = "down"

    plan = A.plan([Bare()], now=NOW)
    assert [(a.connector, a.kind) for a in plan] == [("ai", "new")]


# ---------------------------------------------------------------------------
# What the email says
# ---------------------------------------------------------------------------

def test_the_subject_names_the_service_in_words_a_clerk_uses():
    """"sms is down" is not something to forward to a township administrator."""
    plan = A.plan([FakeHealth("sms", "down")], now=NOW)
    assert A.subject(plan, "Montclair") == "[Montclair] Text messages to residents not working"


def test_the_subject_counts_rather_than_lists_when_several_break():
    plan = A.plan([FakeHealth("sms", "down"), FakeHealth("identity", "down")], now=NOW)
    assert A.subject(plan, "Montclair") == "[Montclair] 2 services not working"


def test_broken_outranks_at_risk_in_the_subject():
    plan = A.plan([FakeHealth("sms", "failing"), FakeHealth("identity", "down")], now=NOW)
    assert "not working" in A.subject(plan, "Montclair")
    assert "may stop" not in A.subject(plan, "Montclair")


def test_an_unknown_connector_still_gets_a_readable_name():
    """A new integration is the one most likely to be misconfigured, so it must
    not be the one that cannot raise an alarm."""
    assert A.label("govtech:accela") == "Accela"
    assert A.label("sms") == "Text messages to residents"


def test_the_body_carries_the_providers_own_words():
    """A clerk searching the web for their error needs the actual string. Our
    paraphrase of it resolves to nothing."""
    plan = A.plan([FakeHealth("identity", "down", last_error="AADSTS7000222: client secret expired")],
                  now=NOW)
    body = A.compose(plan, town="Montclair", settings_url="https://montclair.gov/admin", now=NOW)
    assert "AADSTS7000222" in body["text"]
    assert "AADSTS7000222" in body["html"]
    assert "https://montclair.gov/admin" in body["text"]


def test_the_body_says_when_it_last_worked():
    plan = A.plan([FakeHealth("email", "down", last_success_at=NOW - timedelta(days=3))], now=NOW)
    body = A.compose(plan, town="T", now=NOW)
    assert "3 days ago" in body["text"]


def test_a_connector_that_never_worked_says_so_rather_than_guessing():
    plan = A.plan([FakeHealth("email", "down")], now=NOW)
    assert "never" in A.compose(plan, town="T", now=NOW)["text"]


def test_a_provider_error_cannot_inject_markup_into_the_email():
    """`last_error` is remote text of unbounded shape, and it is being placed
    into HTML we send. Anything that reaches an inbox unescaped is a hole."""
    nasty = '<img src=x onerror="alert(1)">'
    plan = A.plan([FakeHealth("ai", "down", last_error=nasty)], now=NOW)
    html = A.compose(plan, town="T", now=NOW)["html"]
    assert "<img" not in html
    assert "&lt;img" in html


def test_broken_and_at_risk_are_separate_headings():
    """Filing "may stop working" under "not working" is the same class of lie
    as a green tick on a revoked key."""
    plan = A.plan([FakeHealth("sms", "failing"), FakeHealth("identity", "down")], now=NOW)
    text = A.compose(plan, town="T", now=NOW)["text"]
    assert "Not working right now:" in text
    assert "May stop working:" in text
    assert text.index("Not working right now:") < text.index("May stop working:")


# ---------------------------------------------------------------------------
# Sending, and remembering that we sent
# ---------------------------------------------------------------------------

class FakeDB:
    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_one_digest_covers_everything_rather_than_one_email_each():
    """A cloud outage takes four connectors down together. Four separate
    alarms about one event is how people learn to delete them unread."""
    sent = []
    recorded = []

    async def fake_remember(db, alerts, *, now=None):
        recorded.extend(a.connector for a in alerts)

    A_remember, A.remember = A.remember, fake_remember
    try:
        result = await A.dispatch(
            FakeDB(),
            healths=[FakeHealth("ai", "down"), FakeHealth("translation", "down")],
            send=lambda **kw: sent.append(kw) or True,
            recipients=["clerk@montclair.gov"],
            town="Montclair",
            now=NOW,
        )
    finally:
        A.remember = A_remember

    assert len(sent) == 1
    assert result["sent"] is True
    assert sorted(recorded) == ["ai", "translation"]


@pytest.mark.asyncio
async def test_every_administrator_is_written_to_separately():
    """One town's administrators are not disclosed to each other's mail
    providers, and one bad address does not drop the whole batch."""
    sent = []

    async def fake_remember(db, alerts, *, now=None):
        pass

    A_remember, A.remember = A.remember, fake_remember
    try:
        await A.dispatch(
            FakeDB(),
            healths=[FakeHealth("ai", "down")],
            send=lambda **kw: sent.append(kw["to"]) or True,
            recipients=["a@t.gov", "b@t.gov"],
            town="T",
            now=NOW,
        )
    finally:
        A.remember = A_remember

    assert sent == ["a@t.gov", "b@t.gov"]


@pytest.mark.asyncio
async def test_one_failing_address_does_not_stop_the_others():
    delivered = []

    async def fake_remember(db, alerts, *, now=None):
        pass

    def send(**kw):
        if kw["to"] == "bad@t.gov":
            raise RuntimeError("550 no such mailbox")
        delivered.append(kw["to"])
        return True

    A_remember, A.remember = A.remember, fake_remember
    try:
        result = await A.dispatch(
            FakeDB(), healths=[FakeHealth("ai", "down")], send=send,
            recipients=["bad@t.gov", "good@t.gov"], town="T", now=NOW,
        )
    finally:
        A.remember = A_remember

    assert delivered == ["good@t.gov"]
    assert result["sent"] is True


@pytest.mark.asyncio
async def test_nothing_is_recorded_when_nothing_could_be_sent():
    """The state write says "we told them". A mail server that is itself down
    must not silently consume the alert -- tomorrow's sweep has to try again."""
    recorded = []

    async def fake_remember(db, alerts, *, now=None):
        recorded.append(alerts)

    A_remember, A.remember = A.remember, fake_remember
    try:
        result = await A.dispatch(
            FakeDB(), healths=[FakeHealth("ai", "down")],
            send=lambda **kw: False, recipients=["a@t.gov"], town="T", now=NOW,
        )
    finally:
        A.remember = A_remember

    assert result["sent"] is False
    assert recorded == []


@pytest.mark.asyncio
async def test_a_town_with_no_administrator_address_is_not_an_exception():
    result = await A.dispatch(
        FakeDB(), healths=[FakeHealth("ai", "down")],
        send=lambda **kw: True, recipients=[], town="T", now=NOW,
    )
    assert result["sent"] is False
    assert result["reason"] == "no-recipients"


@pytest.mark.asyncio
async def test_a_quiet_day_sends_nothing_at_all():
    calls = []
    result = await A.dispatch(
        FakeDB(), healths=[FakeHealth("ai", "working"), FakeHealth("email", "working")],
        send=lambda **kw: calls.append(kw) or True, recipients=["a@t.gov"], town="T", now=NOW,
    )
    assert calls == []
    assert result["sent"] is False


def test_a_recovery_clears_the_state_rather_than_recording_health():
    """If it stored a level instead, the connector's next failure would be
    compared against a stale entry and reported as a reminder -- so the email
    saying it had broken again would arrive a week late, or never."""
    recovered = A.Alert(connector="ai", level=A.HEALTHY, kind="recovered", summary="")
    assert A.next_state(recovered, now=NOW) == (None, None)


def test_an_ongoing_problem_records_its_level_and_the_time():
    broken = A.Alert(connector="ai", level=A.BROKEN, kind="new", summary="")
    assert A.next_state(broken, now=NOW) == (A.BROKEN, NOW)


def test_the_recorded_state_is_what_silences_tomorrow():
    """The two halves have to agree: whatever `next_state` writes is what
    `decide` reads back the following day, and a mismatch means either daily
    spam or permanent silence."""
    broken = A.Alert(connector="ai", level=A.BROKEN, kind="new", summary="")
    level, at = A.next_state(broken, now=NOW)
    assert A.decide(level=A.BROKEN, previous_level=level, alerted_at=at,
                    now=NOW + timedelta(days=1)) is None
    assert A.decide(level=A.BROKEN, previous_level=level, alerted_at=at,
                    now=NOW + timedelta(days=8)) == "reminder"
