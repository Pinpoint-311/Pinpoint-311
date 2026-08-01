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
        return False
