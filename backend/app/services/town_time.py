"""The town's clock, without moving what is stored.

Every timestamp column in this schema is `timestamptz`, so the database hands
back aware datetimes in UTC. The Python side was building naive ones with
`datetime.utcnow()` -- 73 of them -- and psycopg interprets a naive value in the
*session's* timezone. On a database that is not set to UTC, every timestamp
written was silently offset by hours, and nothing would have said so: the
numbers all look plausible.

That is fixed by storing aware UTC everywhere. This module is the other half:
UTC is right for storage and wrong for a person. "Closed at 02:14" means
nothing to a clerk in New Jersey looking at a report closed just before ten
last night, and an SLA that turns over at midnight UTC turns over at 7pm local,
which is the sort of thing that is only noticed during an audit.

So: store UTC, show the town's time. The town says which zone it is in; this
validates that answer and converts for display.

Pure, and dependency-free apart from the standard library's own zone database.
"""

from datetime import datetime, timezone, tzinfo
from typing import Optional

try:  # pragma: no cover - available on every supported Python
    from zoneinfo import ZoneInfo, available_timezones
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore
    available_timezones = None  # type: ignore

# Not a guess about where any particular town is. UTC is the honest default for
# a deployment that has not said, because it is what is stored -- showing a time
# that matches the database is better than showing one confidently shifted into
# a zone nobody chose.
DEFAULT_TIMEZONE = "UTC"

# Offered first in the picker. Not a restriction: every zone the platform's
# Python knows about is accepted, because a town that needs Guam should not be
# told it is unsupported.
COMMON_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Puerto_Rico",
    "UTC",
]


def is_valid_timezone(name: Optional[str]) -> bool:
    if not name or not isinstance(name, str):
        return False
    if ZoneInfo is None:  # pragma: no cover
        return name == "UTC"
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def normalise_timezone(name: Optional[str]) -> str:
    """What to store. An unrecognised zone falls back rather than raising.

    A bad value in the database must not be able to take the whole console
    down; it should show UTC and let somebody fix it.
    """
    return name if is_valid_timezone(name) else DEFAULT_TIMEZONE


def town_tz(name: Optional[str]) -> tzinfo:
    if ZoneInfo is None:  # pragma: no cover
        return timezone.utc
    try:
        return ZoneInfo(normalise_timezone(name))
    except Exception:  # pragma: no cover
        return timezone.utc


def to_town(moment: Optional[datetime], name: Optional[str]) -> Optional[datetime]:
    """Convert a stored instant into the town's wall clock.

    A naive input is assumed to be UTC, which is what everything in this
    codebase means by a naive datetime -- and saying so here beats each caller
    guessing differently.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(town_tz(name))


def format_town(moment: Optional[datetime], name: Optional[str],
                fmt: str = "%d %b %Y, %H:%M %Z") -> str:
    local = to_town(moment, name)
    return local.strftime(fmt) if local else ""


def offset_label(name: Optional[str], at: Optional[datetime] = None) -> str:
    """"UTC-04:00" for the settings screen, computed at a real instant.

    Not from a table: half the zones this matters for observe daylight saving,
    so the offset depends on when you ask.
    """
    moment = (at or datetime.now(timezone.utc)).astimezone(town_tz(name))
    delta = moment.utcoffset()
    if delta is None:  # pragma: no cover
        return "UTC"
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"UTC{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"
