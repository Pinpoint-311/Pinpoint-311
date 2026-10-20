"""A hard ceiling on what translation may spend, per UTC day and per month.

`POST /system/translate/batch` is unauthenticated, because the resident portal
is. The per-request bounds and the per-IP rate limit stop one request, and one
address, from asking for too much at once -- but sixty requests a minute of
twenty thousand characters is still 1.2M characters a minute per address, and
an address is cheap. Nothing in the application said "that is enough for
today". The only ceiling was the provider console's own quota, which a town has
to know to set.

This module is that ceiling. Every path that sends characters to a provider
reserves them here first; a reservation that would cross the day's or the
month's budget is refused, and the caller serves the source text instead with
`budget_exhausted` set, so a resident sees English rather than an error page.
Cache hits never reach here -- they cost nothing, so they count for nothing.

Where the numbers live
----------------------
* Budgets: fixed, built in. There is no setting: spend limits a town wants to
  tune belong in its provider's console (Google Cloud quotas and budget
  alerts, Azure's pricing tier), where its billing is. This is the safety net
  under that, sized so ordinary use never meets it.
* Counters: Redis, `INCRBY` with an expiry, keyed by the UTC day and month.
  Redis is shared by the API and the Celery worker, so a worker translating a
  notification and a resident loading a page draw from the same budget.
  Reserve-then-check: INCRBY first, and if the new total is over, DECRBY back
  and refuse. Two racing requests can therefore both be refused near the line,
  but they can never both be admitted past it -- the failure is a few spare
  characters, never an overspend.
* Without Redis the counters fall back to process memory. That still bounds
  each process (so the ceiling becomes budget x processes), which is worse
  than the real thing and much better than no ceiling at all, and it is
  logged as a warning so nobody mistakes it for the real thing.

Alerts go through the proactive-health scan (`proactive_health`, key
"translation_budget"): warning at 80%, critical at 100%, de-duplicated and
mutable like every other check there. Each threshold is also logged once per
period, from whichever process crosses it first.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Sized for a small town, and deliberately generous on the day relative to the
# month so a town adding a language is not stopped halfway through its first
# page load.
#
# * What normal use costs: a resident page's UI labels are 20-50k characters
#   per language and are cached forever after the first visit; report content
#   and notifications are a few hundred characters each. A town of 10-30k
#   residents with a handful of active languages spends well under 1M a month
#   once the catalogue is warm.
# * 500k/day lets roughly ten languages' worth of UI be translated from cold
#   in a single day -- a new deployment, or a translation-cache wipe -- without
#   tripping the cap.
# * 5M/month is ~$90 at Google's list price ($20 per million after the 500k
#   free tier) and ~$30 on Azure's S1 -- a number a town finance office would
#   rather be asked about than surprised by. A town that needs more sets its
#   own limits with its provider, and this one never comes into it.
#
# The demo's 17 August 2026 incident (674,448 characters in a day of text the
# town never held) would have been stopped a little after lunch.
DEFAULT_DAILY_CHARS = 500_000
DEFAULT_MONTHLY_CHARS = 5_000_000

WARN_PCT = 80
CRIT_PCT = 100

_PREFIX = "translation:spend:"
# Long enough to outlive the period it counts, short enough to clean itself up.
_DAY_TTL = int(timedelta(days=3).total_seconds())
_MONTH_TTL = int(timedelta(days=40).total_seconds())


@dataclass(frozen=True)
class Reservation:
    """Characters admitted against both counters. Pass back to `refund`."""
    chars: int
    day_key: str
    month_key: str


# --------------------------------------------------------------------------- #
# Periods
# --------------------------------------------------------------------------- #

def _now() -> datetime:
    return datetime.now(timezone.utc)


def periods(now: Optional[datetime] = None) -> Tuple[str, str]:
    """("2026-10-18", "2026-10") for the UTC instant given (default: now)."""
    now = (now or _now()).astimezone(timezone.utc)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")


def _keys(now: Optional[datetime] = None) -> Tuple[str, str]:
    day, month = periods(now)
    return f"{_PREFIX}day:{day}", f"{_PREFIX}month:{month}"


def _resets(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    now = (now or _now()).astimezone(timezone.utc)
    day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return day, month


# --------------------------------------------------------------------------- #
# Limits
# --------------------------------------------------------------------------- #

async def get_limits() -> Tuple[int, int]:
    """(daily, monthly) character budgets. Async so tests can stand in for it."""
    return DEFAULT_DAILY_CHARS, DEFAULT_MONTHLY_CHARS


# --------------------------------------------------------------------------- #
# Counter store: Redis, or process memory when Redis is unreachable
# --------------------------------------------------------------------------- #

# One client per event loop. The Celery worker runs each task on its own loop
# (core.background.run_async), and a redis.asyncio pool created on one loop
# raises "attached to a different loop" on the next.
_clients: Dict[int, Any] = {}
_redis_failed_at: float = 0.0
_REDIS_RETRY_SECONDS = 30.0


def _client():
    global _redis_failed_at
    if _redis_failed_at and time.monotonic() - _redis_failed_at < _REDIS_RETRY_SECONDS:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    client = _clients.get(id(loop))
    if client is not None:
        return client
    try:
        import redis.asyncio as redis

        from app.core.config import get_settings

        client = redis.from_url(get_settings().redis_url, decode_responses=True, socket_timeout=2)
    except Exception as exc:
        logger.warning("translation budget: redis unavailable, counting in process memory (%s)", exc)
        _redis_failed_at = time.monotonic()
        return None
    # Loops come and go in the worker; keep only a few rather than one per task.
    if len(_clients) > 8:
        _clients.clear()
    _clients[id(loop)] = client
    return client


def _redis_down(exc: Exception) -> None:
    global _redis_failed_at
    logger.warning("translation budget: redis error, counting in process memory (%s)", exc)
    _redis_failed_at = time.monotonic()
    _clients.clear()


class _MemoryStore:
    """Per-process stand-in with the same four operations."""

    def __init__(self) -> None:
        self.values: Dict[str, int] = {}
        self.expires: Dict[str, float] = {}

    def _live(self, key: str) -> None:
        exp = self.expires.get(key)
        if exp is not None and exp <= time.time():
            self.values.pop(key, None)
            self.expires.pop(key, None)

    async def incrby(self, key: str, n: int) -> int:
        self._live(key)
        self.values[key] = self.values.get(key, 0) + int(n)
        return self.values[key]

    async def decrby(self, key: str, n: int) -> int:
        return await self.incrby(key, -int(n))

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = time.time() + seconds
        return True

    async def get(self, key: str):
        self._live(key)
        v = self.values.get(key)
        return None if v is None else str(v)

    async def set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False):
        self._live(key)
        if nx and key in self.values:
            return None
        try:
            self.values[key] = int(value)
        except (TypeError, ValueError):
            self.values[key] = 1
        if ex:
            self.expires[key] = time.time() + ex
        return True


_memory = _MemoryStore()


async def _run(op):
    """Run `op(store)` against Redis, or against memory if Redis fails."""
    client = _client()
    if client is not None:
        try:
            return await op(client), "redis"
        except Exception as exc:  # noqa: BLE001 -- any Redis failure falls back
            _redis_down(exc)
    return await op(_memory), "memory"


# --------------------------------------------------------------------------- #
# Reserve / refund
# --------------------------------------------------------------------------- #

def _pct(used: int, limit: int) -> float:
    if limit <= 0:
        # A zero budget is "no spend at all": already at its ceiling.
        return 100.0
    return round(used / limit * 100, 1)


async def _note_once(store, period_key: str, label: str, message: str, ttl: int) -> None:
    """Log `message` once per (period, label), across every process."""
    try:
        if await store.set(f"{period_key}:noted:{label}", 1, ex=ttl, nx=True):
            logger.warning(message)
    except Exception:
        logger.debug("translation budget: could not record notice", exc_info=True)


async def reserve(chars: int, *, now: Optional[datetime] = None) -> Optional[Reservation]:
    """Admit `chars` against today's and this month's budget, or refuse.

    Returns a Reservation (pass to `refund` if the provider then did not bill),
    or None when the request would take either counter past its budget. A
    refused request has charged nothing.
    """
    chars = int(chars or 0)
    day_key, month_key = _keys(now)
    if chars <= 0:
        return Reservation(0, day_key, month_key)
    daily, monthly = await get_limits()
    day_label, month_label = periods(now)

    async def op(store):
        day_total = await store.incrby(day_key, chars)
        await store.expire(day_key, _DAY_TTL)
        if day_total > daily:
            await store.decrby(day_key, chars)
            await store.set(f"{day_key}:exhausted", 1, ex=_DAY_TTL)
            await _note_once(store, day_key, "100",
                             f"Translation budget exhausted for {day_label}: "
                             f"{day_total - chars:,} of {daily:,} characters used; "
                             "serving untranslated text until midnight UTC.", _DAY_TTL)
            return None
        month_total = await store.incrby(month_key, chars)
        await store.expire(month_key, _MONTH_TTL)
        if month_total > monthly:
            await store.decrby(month_key, chars)
            await store.decrby(day_key, chars)
            await store.set(f"{month_key}:exhausted", 1, ex=_MONTH_TTL)
            await _note_once(store, month_key, "100",
                             f"Translation budget exhausted for {month_label}: "
                             f"{month_total - chars:,} of {monthly:,} characters used; "
                             "serving untranslated text until the 1st.", _MONTH_TTL)
            return None
        if daily and day_total * 100 >= daily * WARN_PCT:
            await _note_once(store, day_key, str(WARN_PCT),
                             f"Translation has used {_pct(day_total, daily)}% of today's "
                             f"budget ({day_total:,} of {daily:,} characters).", _DAY_TTL)
        if monthly and month_total * 100 >= monthly * WARN_PCT:
            await _note_once(store, month_key, str(WARN_PCT),
                             f"Translation has used {_pct(month_total, monthly)}% of this "
                             f"month's budget ({month_total:,} of {monthly:,} characters).",
                             _MONTH_TTL)
        return Reservation(chars, day_key, month_key)

    result, _source = await _run(op)
    return result


async def refund(reservation: Optional[Reservation]) -> None:
    """Give back characters the provider did not bill (it failed, or was absent)."""
    if not reservation or reservation.chars <= 0:
        return

    async def op(store):
        await store.decrby(reservation.day_key, reservation.chars)
        await store.decrby(reservation.month_key, reservation.chars)

    try:
        await _run(op)
    except Exception:
        logger.debug("translation budget: refund failed", exc_info=True)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _period_view(period: str, used: int, limit: int, exhausted: bool, resets: datetime) -> Dict[str, Any]:
    pct = _pct(used, limit)
    return {
        "period": period,
        "used": used,
        "limit": limit,
        "remaining": max(limit - used, 0),
        "percent": pct,
        # Refused requests never land in `used`, so a period can be exhausted
        # at 97%: the next request was bigger than what was left.
        "exhausted": bool(exhausted) or (limit >= 0 and used >= limit),
        "resets_at": resets.isoformat(),
    }


def status_of(view: Dict[str, Any]) -> str:
    """"ok" | "warning" | "critical" for one period view."""
    if view.get("exhausted") or view.get("percent", 0) >= CRIT_PCT:
        return "critical"
    if view.get("percent", 0) >= WARN_PCT:
        return "warning"
    return "ok"


async def usage(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Today's and this month's spend against the budgets. Never raises."""
    daily, monthly = await get_limits()
    day_key, month_key = _keys(now)
    day_label, month_label = periods(now)
    day_reset, month_reset = _resets(now)

    async def op(store):
        vals = []
        for key in (day_key, month_key, f"{day_key}:exhausted", f"{month_key}:exhausted"):
            vals.append(await store.get(key))
        return vals

    try:
        (d, m, dx, mx), source = await _run(op)
    except Exception:
        d = m = dx = mx = None
        source = "unavailable"

    def _int(v) -> int:
        try:
            return max(int(v or 0), 0)
        except (TypeError, ValueError):
            return 0

    day = _period_view(day_label, _int(d), daily, bool(dx), day_reset)
    month = _period_view(month_label, _int(m), monthly, bool(mx), month_reset)
    worst = max((status_of(day), status_of(month)), key=["ok", "warning", "critical"].index)
    return {
        "day": day,
        "month": month,
        "status": worst,
        "counter_store": source,
    }


def _reset_for_tests() -> None:
    global _memory, _redis_failed_at
    _memory = _MemoryStore()
    _clients.clear()
    _redis_failed_at = 0.0
