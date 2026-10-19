"""Fire-and-forget asyncio work that is not garbage-collected half-way.

The event loop holds only a weak reference to a task. One started with a bare
`loop.create_task(...)` and not stored anywhere can be collected while it is
still waiting on the database, and asyncio then logs "Task was destroyed but
it is pending!" -- Sentry caught exactly that from proactive_health_scan, where
email-health and usage-metering writes were scheduled this way and simply lost.

`spawn` keeps a strong reference until the task finishes. `drain` lets a
worker's short-lived loop (`run_async`) give these writes a moment to land
before the loop closes, instead of cancelling them.
"""

import asyncio
import logging
from typing import Coroutine, Set

logger = logging.getLogger(__name__)

_tasks: Set[asyncio.Task] = set()


def spawn(coro: Coroutine) -> bool:
    """Schedule `coro` on the running loop, keeping it alive until done.
    Returns False (and closes the coroutine) when no loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return False
    task = loop.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


async def drain(timeout: float = 5.0) -> None:
    """Wait up to `timeout` seconds for this loop's spawned tasks. Never raises."""
    try:
        loop = asyncio.get_running_loop()
        pending = [t for t in _tasks if not t.done() and t.get_loop() is loop]
        if pending:
            await asyncio.wait(pending, timeout=timeout)
    except Exception:  # noqa: BLE001 -- bookkeeping must not fail the task
        logger.debug("background drain failed", exc_info=True)
