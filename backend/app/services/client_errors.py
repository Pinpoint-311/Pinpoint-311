"""Keep browser crashes where an administrator will actually find them.

The error screen tells a resident their crash "has been reported". That was only
true in the sense that a line went into the application log. For a town running
this on its own server with no Sentry, the report went into a container log
nobody reads and that rotates away within days -- so the sentence was
technically accurate and practically false.

Persisting them makes it true. The constraints that shape this module both come
from one fact: the endpoint that feeds it is public and unauthenticated, because
a crash report has to work when the app is too broken to authenticate.

  * identical crashes collapse onto one row with a count. A render loop emits
    hundreds of the same error in seconds, and a list of hundreds of identical
    rows hides every other fault on the page.
  * the table is capped and pruned on write, so a flood costs a bounded amount
    of disk rather than a full one.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

MAX_ROWS = 500
MESSAGE_MAX = 1000
STACK_MAX = 4000


def fingerprint(kind: str, message: str, stack: Optional[str]) -> str:
    """A stable id for "the same crash".

    Built from the message plus the first stack frame, not the whole stack: the
    same fault reached through two routes should collapse, and line numbers
    shift between builds. Digits are masked so a message carrying an id or a
    timestamp -- "request 4821 not found" -- does not create a new row every
    time.
    """
    head = ""
    if stack:
        for line in stack.splitlines():
            line = line.strip()
            if line and not line.startswith(message[:40]):
                head = line
                break
    # Computed outside the f-string: Python 3.11 rejects a backslash inside an
    # f-string expression, and the digit mask needs one.
    digits = re.compile(r"\d+")
    masked_message = digits.sub("#", message or "")[:200]
    masked_head = digits.sub("#", head)[:200]
    basis = f"{kind}|{masked_message}|{masked_head}"
    return hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:32]


def _clip(text: Optional[str], limit: int) -> Optional[str]:
    if not text:
        return None
    # Collapse newlines out of single-line fields only; stacks keep theirs.
    return str(text)[:limit]


async def record(db, *, kind: str, message: str, stack: Optional[str] = None,
                 component_stack: Optional[str] = None, url: Optional[str] = None,
                 user_agent: Optional[str] = None) -> None:
    """Store one crash, collapsing onto an existing row if we have seen it.

    Never raises. A crash reporter that can itself 500 turns one broken page
    into two, and the caller is already in a bad state.
    """
    try:
        from sqlalchemy import select

        from app.models import ClientErrorLog

        message = _clip(message, MESSAGE_MAX) or "Unknown error"
        fp = fingerprint(kind, message, stack)
        now = datetime.now(timezone.utc)

        existing = (await db.execute(
            select(ClientErrorLog).where(ClientErrorLog.fingerprint == fp)
        )).scalar_one_or_none()

        if existing is not None:
            existing.occurrences = (existing.occurrences or 1) + 1
            existing.last_seen_at = now
            # Keep the newest URL: the most recent sighting is the one someone
            # will try to reproduce.
            existing.url = _clip(url, 500) or existing.url
        else:
            db.add(ClientErrorLog(
                kind=_clip(kind, 64) or "unknown",
                message=message,
                stack=_clip(stack, STACK_MAX),
                component_stack=_clip(component_stack, STACK_MAX),
                url=_clip(url, 500),
                user_agent=_clip(user_agent, 300),
                fingerprint=fp,
                occurrences=1,
                first_seen_at=now,
                last_seen_at=now,
            ))

        await db.commit()
        await prune(db)
    except Exception as exc:
        logger.warning("[ClientErrors] could not persist: %s", exc)


async def prune(db, keep: int = MAX_ROWS) -> None:
    """Drop all but the most recently seen `keep` distinct crashes.

    On write rather than on a schedule, because the flood this defends against
    arrives in seconds and a nightly task would be far too late.
    """
    try:
        from sqlalchemy import delete, select

        from app.models import ClientErrorLog

        total = (await db.execute(
            select(ClientErrorLog.id).order_by(ClientErrorLog.last_seen_at.desc()).offset(keep).limit(1)
        )).scalar_one_or_none()
        if total is None:
            return

        cutoff = (await db.execute(
            select(ClientErrorLog.last_seen_at)
            .order_by(ClientErrorLog.last_seen_at.desc())
            .offset(keep - 1).limit(1)
        )).scalar_one_or_none()
        if cutoff is None:
            return

        await db.execute(delete(ClientErrorLog).where(ClientErrorLog.last_seen_at < cutoff))
        await db.commit()
    except Exception as exc:
        logger.warning("[ClientErrors] could not prune: %s", exc)


async def recent(db, limit: int = 50) -> List[Any]:
    """Most-recently-seen crashes first. Never raises."""
    try:
        from sqlalchemy import select

        from app.models import ClientErrorLog

        result = await db.execute(
            select(ClientErrorLog).order_by(ClientErrorLog.last_seen_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning("[ClientErrors] could not read: %s", exc)
        return []
