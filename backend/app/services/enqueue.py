"""Hand work to the queue without letting the queue break the request.

`task.delay(...)` is a network call. It reaches Redis, and Redis is one more
thing that can be down, full, or unreachable across a restart. Every call site
in this codebase makes it *after* `db.commit()`, which means a broker outage
turns a saved record into a 500: the row is in the database, the audit entry is
in the database, and the person who pressed the button is told it failed.

For a resident posting a comment that is not a cosmetic difference. They are
told the comment did not post, so they post it again, and the town gets two.

The work itself is genuinely optional at this instant -- an email, an AI triage
pass, a mirror to a county system. None of it is the record. So a broker that
cannot be reached costs a notification and a line in the log, not the thing the
person actually came to do.

Returns whether it went, so a caller that wants to say "we saved this, the
email will follow when the queue is back" can.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

# For the other kind of call site. Some handoffs are not incidental: an admin
# pressing "Run retention now" or "Sync now" is asking for precisely the queued
# job and nothing else. Swallowing the failure there would answer "started" for
# a job that never started -- the exact lie this codebase keeps finding in
# itself, and worse than the 500 it replaced, because a 500 at least tells
# somebody to look.
#
# So those sites check the return value and raise this. Deliberately plain
# text and no FastAPI import: this module is reachable from the CI test suite,
# which installs neither FastAPI nor Celery.
QUEUE_UNAVAILABLE = (
    "The background worker is not reachable, so this job did not start. "
    "Nothing has been changed. Check that the worker and Redis are running, "
    "then try again."
)


# Govtech pushes are the exception to "optional at this instant": a report that
# never reaches the county is lost work, not a skipped email. When one of these
# cannot be queued it is written to the integration backlog instead, so it shows
# under Failed syncs and the retry beat sends it once the worker is back.
_INTEGRATION_PUSHES = {
    "push_request_to_integrations": "push",
    "push_status_to_integrations": "push_status",
    "push_comment_to_integrations": "push_comment",
}

# Strong references to backlog writes scheduled on the running loop, so the
# garbage collector cannot cancel one half-way.
_PENDING: set = set()


def _backlog_unqueued(name: str, args: tuple, kwargs: dict) -> None:
    """Record an integration push that could not be queued. Never raises."""
    operation = _INTEGRATION_PUSHES.get(str(name).rsplit(".", 1)[-1])
    if not operation or not args:
        return
    try:
        import asyncio

        from app.tasks.integrations import record_unqueued_push

        subject = args[0]
        if operation == "push_comment":
            coro = record_unqueued_push(operation, comment_id=subject)
        else:
            coro = record_unqueued_push(operation, request_id=subject,
                                        notes=kwargs.get("notes"))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            # Inside the API: same loop as the request's database engine.
            task = loop.create_task(coro)
            _PENDING.add(task)
            task.add_done_callback(_PENDING.discard)
        else:
            from app.tasks.service_requests import run_async
            run_async(coro)
    except Exception as exc:  # noqa: BLE001 -- bookkeeping must not break the caller
        logger.warning("[Queue] could not record the unqueued %s in the integration "
                       "backlog: %s", sanitize_for_log(operation), sanitize_for_log(str(exc)))


def enqueue(task: Any, *args: Any, **kwargs: Any) -> bool:
    """Queue `task`. Never raises.

    Deliberately swallows everything. A broker error arrives as any of half a
    dozen exception types depending on transport and failure mode, and the
    caller's correct response is the same for all of them: carry on, the record
    is already saved.
    """
    name = getattr(task, "name", None) or getattr(task, "__name__", "task")
    try:
        task.delay(*args, **kwargs)
        return True
    except Exception as exc:  # noqa: BLE001 -- see docstring
        logger.warning(
            "[Queue] could not enqueue %s: %s. The record is saved; this "
            "follow-up work did not run.",
            sanitize_for_log(str(name)), sanitize_for_log(str(exc)),
        )
        # Only for real Celery tasks: a stand-in without apply_async is a test
        # double, and has no backlog to write to.
        if hasattr(task, "apply_async"):
            _backlog_unqueued(str(name), args, kwargs)
        return False
