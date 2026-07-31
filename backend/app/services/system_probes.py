"""Disk, database, cache and backups, as things that can be reported on.

The console had two unrelated ideas of "is it working". Connectors had a daily
sweep, a health table, escalation and email. Infrastructure had a page you had
to be looking at -- so a disk filling up was visible to anyone who happened to
open System Health that afternoon, and to nobody otherwise. A full disk stops
the database accepting writes, which stops a town taking reports, and the first
sign of it should not be a resident's form failing.

Rather than build a second alerting path, these are recorded as ordinary
connector-health rows under a `system:` prefix. Everything already built then
applies for free and cannot drift: the same escalation from at-risk to broken,
the same digest, the same cadence, the same mute. The one difference is the
sweep interval -- connectors are checked daily because each costs a call to
somebody else's API, and these cost a syscall, so they run hourly. The alerting
cadence is unchanged by that: it is governed by how long a connector has been
in a state, not by how often it is measured.

Pure, so all of it runs in CI. The readings are passed in; nothing here touches
a disk, a database or a clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

PREFIX = "system:"

# Where a filling disk stops being interesting and starts being a deadline.
#
# 80 is the warning because the gap between "somebody should look at this" and
# "the database cannot write" is measured in days at typical growth, and a
# town's answer is often to ring somebody, which takes one. 90 is not a
# comfortable margin on a small volume -- 10% of 20GB is two gigabytes, which a
# photo-heavy week can eat -- but a threshold nobody reaches is not a threshold.
DISK_WARN_PERCENT = 80
DISK_CRITICAL_PERCENT = 90

# A backup regime that has silently stopped is indistinguishable from one that
# never ran, and both are discovered at restore time. Two days rather than one:
# a single missed nightly run is a blip, two is a pattern.
BACKUP_STALE_AFTER = timedelta(days=2)


def _outcome(ok: bool, detail: str, *, recorded: bool = True) -> Dict[str, Any]:
    return {"ok": ok, "detail": detail, "recorded": recorded}


def classify_disk(percent_used: Optional[float], *, free_label: str = "") -> Dict[str, Any]:
    """A reading, in the words somebody who is not an engineer can act on."""
    if percent_used is None:
        # Not every host lets us see this. Silence beats a guess.
        return _outcome(False, "Disk usage could not be read on this host.", recorded=False)
    room = f" {free_label} free." if free_label else ""
    if percent_used >= DISK_CRITICAL_PERCENT:
        return _outcome(False, (
            f"Disk is {percent_used:.0f}% full.{room} When it reaches 100% the database stops "
            f"accepting new reports. Clear space or extend the volume."
        ))
    if percent_used >= DISK_WARN_PERCENT:
        return _outcome(False, (
            f"Disk is {percent_used:.0f}% full.{room} Not urgent yet, but it does not "
            f"empty itself -- worth arranging more space now rather than at 99%."
        ))
    return _outcome(True, f"Disk is {percent_used:.0f}% full.{room}")


def classify_backup(last_backup_at: Optional[datetime], now: datetime,
                    *, stale_after: timedelta = BACKUP_STALE_AFTER) -> Dict[str, Any]:
    """Backups are only real if they are recent and somebody would notice."""
    if last_backup_at is None:
        return _outcome(False, (
            "No backup has ever been recorded. Nothing here can be restored."
        ))
    if last_backup_at.tzinfo is None:
        last_backup_at = last_backup_at.replace(tzinfo=timezone.utc)
    age = now - last_backup_at
    if age >= stale_after:
        days = max(1, int(age.total_seconds() // 86400))
        return _outcome(False, (
            f"The last successful backup was {days} day{'s' if days != 1 else ''} ago. "
            f"Anything since then would be lost."
        ))
    hours = max(0, int(age.total_seconds() // 3600))
    return _outcome(True, f"Last backup {hours} hour{'s' if hours != 1 else ''} ago.")


def failure_summary(exc: BaseException) -> str:
    """What a connection failure may say in public.

    The exception type and nothing else. These strings are stored, rendered on
    a card and mailed to administrators, and the drivers that raise them put
    the connection string in the message -- `OperationalError` from psycopg
    quotes the DSN, and a Redis URL carries its password inline. Repeating that
    would turn an outage into a credential disclosure with a wide audience and
    a long tail: a database row, an inbox, and whatever the town forwards it
    to.

    The type tells an administrator what kind of problem it is, which is what
    they can act on. The full text goes to the log, sanitised.
    """
    name = type(exc).__name__
    return f"Could not connect ({name}). The full error is in the server log."


def classify_reachable(name: str, reachable: bool, detail: str = "") -> Dict[str, Any]:
    if reachable:
        return _outcome(True, detail or f"{name} is reachable.")
    return _outcome(False, detail or f"{name} is not reachable from the server.")


# What each probe is called on screen and in an email. Kept here so the alert
# text and the health page cannot disagree about what "system:disk" means.
LABELS: Dict[str, str] = {
    "system:disk": "Disk space",
    "system:database": "Database",
    "system:cache": "Cache (Redis)",
    "system:backups": "Backups",
}


def label_for(connector: str) -> str:
    return LABELS.get(connector, connector.replace(PREFIX, "").replace("_", " ").capitalize())


def is_system(connector: str) -> bool:
    return connector.startswith(PREFIX)


# Headers a reverse proxy adds on the way through. Any one of them is evidence
# that this request was routed rather than made directly to the app.
FORWARDED_HEADERS = ("x-forwarded-for", "x-forwarded-proto", "x-real-ip")


def proxy_status(headers) -> Dict[str, str]:
    """Whether the reverse proxy can be said to be working, from in here.

    It used to be hardcoded to "running", on the reasoning that a request we
    received must have been routed to us. That holds only when the request came
    through the proxy. An admin on a port-forward, or a dev server talking to
    the backend directly, got a confident green tick on a proxy that might be
    stopped -- and a green tick nobody checked is the failure this console keeps
    being built around avoiding.

    There is no third state to invent here: either the evidence is in the
    request or it is not.
    """
    names = {str(h).lower() for h in (headers or {})}
    if names & set(FORWARDED_HEADERS):
        return {"status": "running", "detail": "Routed this request"}
    return {
        "status": "unknown",
        "detail": "Cannot tell from here - this request did not arrive through a proxy",
    }
