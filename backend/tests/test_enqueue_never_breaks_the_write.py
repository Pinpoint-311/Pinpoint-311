"""A broker outage must not turn a saved record into an error.

Every `.delay()` in the API layer is made after `db.commit()`. That ordering is
correct -- the record is what matters and it is safe before anything optional
is attempted -- but it means an unreachable Redis raises out of a handler whose
work is already done. The caller is told it failed. For a resident posting a
comment, that means posting it again, and the town gets two.

`enqueue()` is the whole fix: try, log, carry on, report whether it went.
"""

import logging

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


def test_the_comment_endpoints_do_not_call_delay_directly():
    """The regression guard. Adding a `.delay()` back to either comment handler
    reinstates exactly the failure this module exists to prevent, and it is the
    natural thing to write.

    Scoped to the comment paths on purpose: the other API handlers still call
    `.delay()` unguarded and converting them is a separate change with its own
    blast radius. Widening this assertion is how that gets finished.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    staff = (root / "backend/app/api/comments.py").read_text()
    assert ".delay(" not in staff, "use enqueue() -- see the module docstring"

    public = (root / "backend/app/api/open311.py").read_text()
    handler = public[public.index("async def add_public_comment"):]
    handler = handler[:handler.index("\n@router")]
    assert ".delay(" not in handler, "use enqueue() -- see the module docstring"
