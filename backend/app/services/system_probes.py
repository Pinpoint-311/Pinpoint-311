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


# --------------------------------------------------------------------------- #
# Reading a container's own limits, rather than the machine it happens to be on.
#
# Both resource probes measured the host and reported it as if it were ours:
#
#   * `shutil.disk_usage("/")` reads the filesystem behind the container's root.
#     On a default Docker install that *is* the host disk, so the number is
#     usually right by accident -- and silently wrong the moment the volumes
#     that hold the data live somewhere else. `uploads_data` and
#     `migration_backups` are where a town's disk actually fills up: photos on
#     every report, and an unencrypted pg_dump before every migration. Mount
#     either on a second disk and the probe watches the one that is not filling.
#
#   * `/proc/meminfo` is the *host's* memory, always. It is not namespaced.
#     compose caps the backend at `memory: 1G`; on a 32GB server a backend
#     sitting at 990MB and one OOM-kill away from restarting mid-report reports
#     3% used, green. The limit that kills the process is the one to measure
#     against.
#
# So: disk is read at every path that matters and the worst one is reported by
# name, and memory prefers the cgroup limit, falling back to the host only when
# the container genuinely has no cap.
# --------------------------------------------------------------------------- #

MEMORY_WARN_PERCENT = 85
MEMORY_CRITICAL_PERCENT = 95

# cgroup writes "max" (v2) or a number near 2^63 (v1) to mean "no limit".
_NO_LIMIT_ABOVE = 1 << 62


def _fmt_bytes(n: Optional[float]) -> str:
    if n is None:
        return "?"
    gb = n / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f} GB"
    return f"{n / (1024 ** 2):.0f} MB"


def interpret_memory(limit_bytes: Optional[int], usage_bytes: Optional[int],
                     host_total_bytes: Optional[int] = None,
                     host_available_bytes: Optional[int] = None) -> Dict[str, Any]:
    """Which memory figure to trust, and what it comes to as a percentage.

    The container's own limit wins whenever there is one, because that is the
    number the kernel kills the process at. The host is the fallback, and it is
    labelled as the host so nobody reads a reassuring 3% as being about us.
    """
    if limit_bytes is not None and 0 < limit_bytes < _NO_LIMIT_ABOVE and usage_bytes is not None:
        return {
            "scope": "container",
            "used_bytes": usage_bytes,
            "limit_bytes": limit_bytes,
            "percent": round(usage_bytes / limit_bytes * 100, 1),
        }
    if host_total_bytes and host_available_bytes is not None:
        return {
            "scope": "host",
            "used_bytes": host_total_bytes - host_available_bytes,
            "limit_bytes": host_total_bytes,
            "percent": round((1 - host_available_bytes / host_total_bytes) * 100, 1),
        }
    return {"scope": None, "used_bytes": None, "limit_bytes": None, "percent": None}


def classify_memory(reading: Dict[str, Any]) -> Dict[str, Any]:
    percent = reading.get("percent")
    if percent is None:
        return _outcome(False, "Memory usage could not be read on this host.", recorded=False)

    where = ("this container's %s limit" % _fmt_bytes(reading.get("limit_bytes"))
             if reading.get("scope") == "container"
             else "the server's %s of RAM" % _fmt_bytes(reading.get("limit_bytes")))
    used = f"{_fmt_bytes(reading.get('used_bytes'))} of {where}"

    if percent >= MEMORY_CRITICAL_PERCENT:
        return _outcome(False, (
            f"Memory is {percent:.0f}% used -- {used}. At 100% the container is killed and "
            f"restarted, losing whatever it was in the middle of. Raise the limit or "
            f"reduce what is running."
        ))
    if percent >= MEMORY_WARN_PERCENT:
        return _outcome(False, (
            f"Memory is {percent:.0f}% used -- {used}. Not failing yet, but there is little "
            f"headroom for a busy afternoon."
        ))
    return _outcome(True, f"Memory is {percent:.0f}% used -- {used}.")


def worst_disk(readings) -> Optional[Dict[str, Any]]:
    """The fullest of the filesystems we depend on, with its name attached.

    Several of the paths usually turn out to be the same filesystem, which is
    why they are deduplicated by device rather than reported four times. What is
    left is the set of distinct disks a town can actually run out of, and the
    only one worth alerting on is the one closest to full -- naming it, because
    "disk is 94% full" without saying which disk is not something anybody can
    act on.
    """
    seen = set()
    best = None
    for r in readings or []:
        if r is None or not r.get("total"):
            continue
        key = r.get("device")
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        percent = round(r["used"] / r["total"] * 100, 1)
        entry = {**r, "percent": percent}
        if best is None or percent > best["percent"]:
            best = entry
    return best


def describe_disk(reading: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not reading:
        return classify_disk(None)
    label = reading.get("label") or reading.get("path") or ""
    out = classify_disk(reading["percent"], free_label=_fmt_bytes(reading.get("free")))
    if label:
        out["detail"] = out["detail"].replace("Disk is", f"{label} is", 1)
    return out


# The paths a town's data actually lives on, as this container sees them, and
# what to call each one on a screen read by somebody who did not deploy it.
# `/` is kept because the container's own filesystem filling up stops it writing
# logs and temporary files even when every volume has room.
DISK_PATHS = (
    ("/", "The server disk"),
    ("/project/uploads", "Photo storage"),
    ("/backups", "Backup storage"),
)


def _first_int(path: str) -> Optional[int]:
    try:
        with open(path) as fh:
            return int(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _keyed_int(path: str, key: str) -> Optional[int]:
    try:
        with open(path) as fh:
            for line in fh:
                parts = line.split()
                if parts and parts[0] == key:
                    return int(parts[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def read_cgroup_memory(root: str = "/sys/fs/cgroup"):
    """(limit, usage) for this container, or (None, None) if it is not capped.

    v2 first, then v1. Page cache is subtracted from usage in both: the kernel
    reclaims it under pressure rather than OOM-killing, so counting it would
    have every long-running container reading 99% and nobody believing the
    number by the second week.
    """
    limit = _first_int(f"{root}/memory.max")
    if limit is None:
        # "max" is not an int; the file existing at all means v2.
        try:
            with open(f"{root}/memory.max") as fh:
                if fh.read().strip() == "max":
                    return None, None
        except OSError:
            pass
    if limit is not None:
        usage = _first_int(f"{root}/memory.current")
        cache = _keyed_int(f"{root}/memory.stat", "inactive_file") or 0
        return limit, (max(0, usage - cache) if usage is not None else None)

    limit = _first_int(f"{root}/memory/memory.limit_in_bytes")
    if limit is None:
        return None, None
    usage = _first_int(f"{root}/memory/memory.usage_in_bytes")
    cache = _keyed_int(f"{root}/memory/memory.stat", "total_inactive_file") or 0
    return limit, (max(0, usage - cache) if usage is not None else None)


def read_host_memory(path: str = "/proc/meminfo"):
    """(total, available) in bytes. Always the host's -- /proc is not namespaced."""
    total = _keyed_int(path, "MemTotal:")
    avail = _keyed_int(path, "MemAvailable:")
    return (total * 1024 if total else None), (avail * 1024 if avail is not None else None)


def read_memory(cgroup_root: str = "/sys/fs/cgroup",
                meminfo: str = "/proc/meminfo") -> Dict[str, Any]:
    limit, usage = read_cgroup_memory(cgroup_root)
    total, avail = read_host_memory(meminfo)
    return interpret_memory(limit, usage, total, avail)


def read_disks(paths=DISK_PATHS):
    """Usage for each path that exists, tagged with the device behind it.

    A path that is not mounted in this container is skipped rather than
    reported as an error: the backend does not see the database volume, and
    saying so on every sweep would train people to ignore the panel.
    """
    import os
    import shutil

    out = []
    for path, label in paths:
        try:
            usage = shutil.disk_usage(path)
            device = os.stat(path).st_dev
        except OSError:
            continue
        out.append({
            "path": path, "label": label, "device": device,
            "total": usage.total, "used": usage.used, "free": usage.free,
        })
    return out


def read_cpu_allowance(root: str = "/sys/fs/cgroup") -> Optional[float]:
    """How many cores this container may use, or None if it is not capped."""
    try:
        with open(f"{root}/cpu.max") as fh:
            quota, _, period = fh.read().strip().partition(" ")
        if quota == "max":
            return None
        return int(quota) / int(period or 100000)
    except (OSError, ValueError):
        pass
    quota = _first_int(f"{root}/cpu/cpu.cfs_quota_us")
    period = _first_int(f"{root}/cpu/cpu.cfs_period_us")
    if quota is None or quota <= 0 or not period:
        return None
    return quota / period


def read_cpu_seconds(root: str = "/sys/fs/cgroup") -> Optional[float]:
    """Total CPU time this container has used, in seconds."""
    usec = _keyed_int(f"{root}/cpu.stat", "usage_usec")
    if usec is not None:
        return usec / 1_000_000
    nsec = _first_int(f"{root}/cpuacct/cpuacct.usage")
    if nsec is not None:
        return nsec / 1_000_000_000
    return None


def cpu_percent(used_seconds: Optional[float], elapsed_seconds: float,
                cores: Optional[float]) -> Optional[float]:
    """CPU used over a window, as a percentage of what this container may use.

    Against the container's own allowance, not the machine's core count: a
    backend limited to `cpus: '1.0'` on an eight-core server is saturated at
    what the host would call 12%.
    """
    if used_seconds is None or elapsed_seconds <= 0:
        return None
    allowed = cores if cores and cores > 0 else 1.0
    return round(used_seconds / (elapsed_seconds * allowed) * 100, 1)


def describe_cpu(percent: Optional[float], cores: Optional[float],
                 window_seconds: float) -> Dict[str, Any]:
    """A reading, said as the momentary thing it is.

    Deliberately not alerted on. This is one short sample, and a container is
    briefly at 100% every time it renders a PDF or resizes a photo -- alerting
    on that would send an email a day about nothing, and an alert nobody
    believes is worse than no alert. Disk fills and memory caps are the ones
    that predict an outage; CPU here is a number to look at when something
    already feels slow.
    """
    if percent is None:
        return _outcome(True, "CPU usage could not be read on this host.", recorded=False)
    allowance = (f"{cores:g} core{'s' if cores and cores != 1 else ''}"
                 if cores else "all the server's cores")
    return _outcome(True, (
        f"CPU was {percent:.0f}% of {allowance} over the last {window_seconds:g}s."
    ))


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
    "system:memory": "Memory",
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
