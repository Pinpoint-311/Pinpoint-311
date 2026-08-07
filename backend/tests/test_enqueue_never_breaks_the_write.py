"""A broker outage must not turn a saved record into an error.

Every `.delay()` in the API layer is made after `db.commit()`. That ordering is
correct -- the record is what matters and it is safe before anything optional
is attempted -- but it means an unreachable Redis raises out of a handler whose
work is already done. The caller is told it failed. For a resident posting a
comment, that means posting it again, and the town gets two.

`enqueue()` is the whole fix: try, log, carry on, report whether it went.
"""

import logging
from pathlib import Path

import pytest

from app.services.enqueue import enqueue


class Task:
    """Stands in for a Celery task. Records the call, or refuses to accept it."""

    name = "app.tasks.integrations.push_comment_to_integrations"

    def __init__(self, raises: Exception | None = None):
        self.raises = raises
        self.calls: list[tuple] = []

    def delay(self, *args, **kwargs):
        if self.raises:
            raise self.raises
        self.calls.append((args, kwargs))
        return "task-id"


def test_a_reachable_broker_gets_the_work():
    task = Task()
    assert enqueue(task, 7, "comments", actor="Resident") is True
    assert task.calls == [((7, "comments"), {"actor": "Resident"})]


def test_an_unreachable_broker_does_not_raise():
    """The one behaviour the comment endpoint depends on."""
    task = Task(raises=ConnectionRefusedError("Error 111 connecting to redis:6379"))
    assert enqueue(task, 7) is False


@pytest.mark.parametrize("failure", [
    ConnectionRefusedError("connection refused"),
    TimeoutError("timed out"),
    OSError("no route to host"),
    RuntimeError("kombu: no more channels"),
    ValueError("could not serialize argument"),
])
def test_it_swallows_every_shape_a_broker_failure_arrives_in(failure):
    """Deliberately not a narrow except. A broker error is any of these
    depending on transport and failure mode, and the caller's correct response
    is identical for all of them -- the record is already saved.
    """
    assert enqueue(Task(raises=failure)) is False


def test_the_failure_is_written_down(caplog):
    """Swallowed is not the same as hidden. An operator has to be able to find
    out that a week of notifications did not go out."""
    with caplog.at_level(logging.WARNING):
        enqueue(Task(raises=ConnectionRefusedError("boom")))
    assert any("could not enqueue" in r.getMessage() for r in caplog.records), caplog.text
    assert "push_comment_to_integrations" in caplog.text


def test_a_hostile_task_name_cannot_forge_a_log_line():
    """The name reaches a log line, so it goes through the same sanitizer as
    every other interpolated value (CWE-117)."""
    task = Task(raises=ConnectionRefusedError("x"))
    task.name = "evil\nWARNING:root:all systems normal"
    assert enqueue(task) is False


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "backend/app/api"

# The two call sites that still say `.delay()` directly, and why each is
# allowed to. Both wrap it themselves; neither is an oversight.
#
#   system.py  "Run retention now" -- must fail loudly, and does, with its own
#              try/except raising 503. Not converted to `enqueue()` because it
#              needs the returned task id, which `enqueue()` does not hand back.
#   gis.py     road seeding -- already falls back to running inline when the
#              queue is unavailable, which is better than either swallowing or
#              raising, and predates this module.
DELIBERATE = {"system.py": 1, "gis.py": 1}


def test_no_handler_calls_delay_unguarded():
    """The sweep, as a test.

    Every `.delay()` in the API layer is made after `db.commit()`, so an
    unreachable broker raised out of a handler whose work was already done.
    Sixteen call sites had that shape. The two below are listed by name with a
    reason; anything else is a regression, and adding one is the natural thing
    to write.
    """
    found = {}
    for path in sorted(API.glob("*.py")):
        count = path.read_text().count(".delay(")
        if count:
            found[path.name] = count

    assert found == DELIBERATE, (
        f"unguarded .delay() in {sorted(set(found) - set(DELIBERATE))}, "
        f"or a count changed: {found} != {DELIBERATE}. Use enqueue() for "
        f"follow-up work, or enqueue() + QUEUE_UNAVAILABLE where the queued "
        f"job is the thing being asked for."
    )


def test_the_deliberate_exceptions_still_handle_a_broker_failure():
    """Naming a file in DELIBERATE is not a way of opting out. Each one has to
    visibly cope with the call raising, or the exemption is just an unguarded
    `.delay()` with a comment next to it."""
    for name in DELIBERATE:
        source = (API / name).read_text()
        window = source[max(0, source.index(".delay(") - 600):source.index(".delay(") + 600]
        assert "try:" in window and "except" in window, (
            f"{name} is exempt from the sweep but does not handle the call failing"
        )


def test_a_job_somebody_asked_for_is_not_reported_as_started_when_it_is_not():
    """The other half of the rule, and the easier one to get wrong.

    `enqueue()` swallowing is right when the queued work is incidental -- a
    resident filed a report, the email is a consequence. It is wrong when the
    queued job *is* the request. "Sync started" and "Retention enforcement
    started" are claims, and answering them for a job that never reached a
    worker is the failure this codebase keeps finding in itself: a button that
    reports success and does nothing. Worse than the 500 it replaced, because a
    500 at least tells somebody to look.
    """
    integrations = (API / "integrations.py").read_text()
    # Anchored on the returned value, not the bare phrase. The first draft
    # searched for "Sync started" and matched the sentence in the comment
    # explaining the guard, which sits *above* it -- so the test failed on
    # correct code. Prose about a behaviour is not the behaviour.
    #
    # Two shapes of guard count, because "Sync now" enqueues two jobs. Raising
    # QUEUE_UNAVAILABLE on the first failure was itself a version of this bug:
    # written `enqueue(a) or enqueue(b)`, a failure of the second returned "this
    # job did not start. Nothing has been changed." after the first had already
    # started. So that endpoint now enqueues both and only claims the unqualified
    # "Sync started" when every one of them went.
    guards = ("QUEUE_UNAVAILABLE", "all(started.values())")
    for claim in ('"message": "Sync started"', '"message": "Asset sync started"'):
        before = integrations[:integrations.index(claim)]
        # The check must be the thing immediately guarding the claim.
        assert any(guard in before[-400:] for guard in guards), (
            f'{claim} is returned without confirming the job was queued'
        )

    system = (API / "system.py").read_text()
    triggered = system[:system.index('"status": "triggered"')]
    assert "QUEUE_UNAVAILABLE" in triggered[-800:], (
        'retention reports "triggered" without confirming the job was queued'
    )


def test_the_unavailable_message_says_what_to_do_and_what_did_not_happen():
    """It is read by a clerk, not an operator. "Service unavailable" tells them
    nothing about whether their data changed."""
    from app.services.enqueue import QUEUE_UNAVAILABLE

    assert "did not start" in QUEUE_UNAVAILABLE
    assert "Nothing has been changed" in QUEUE_UNAVAILABLE
    assert "try again" in QUEUE_UNAVAILABLE


def test_the_message_carries_no_hostname_or_credential():
    """It is rendered in the admin UI and pasted into support threads."""
    from app.services.enqueue import QUEUE_UNAVAILABLE

    for leak in ("redis://", "amqp://", "://", "@", "password"):
        assert leak not in QUEUE_UNAVAILABLE, f"{leak!r} in a user-facing string"
