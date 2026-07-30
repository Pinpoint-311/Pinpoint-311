"""Proactive (leading-indicator) health checks.

The point of this module is to warn *before* something fails, not just report
that it already did. It evaluates capacity/resource signals that predict an
outage on a small self-hosted deployment — disk filling up, memory pressure,
database connections nearing the limit, backups going stale, Redis memory — and
classifies each against a WARNING and a CRITICAL threshold.

Three consumers:
  - Admins get the full detail (which check, the number, and a suggested action)
    in the operations panel, alongside the restart/diagnose runbooks.
  - Non-technical staff get a single plain-language rollup ("All systems normal"
    / "Minor issue" / "Service issue").
  - A scheduled task emails admins when a check crosses into warning/critical, so
    problems surface early instead of after downtime.

The threshold classification is pure and unit-tested; the metric collectors do
I/O and are each defensive (a failing probe degrades to "unknown", never raises).
"""

import logging
import os
import shutil
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Severity ordering for rollups. "unknown" is treated as non-actionable (0) so a
# probe we couldn't run never escalates the overall status on its own.
_SEVERITY = {"ok": 0, "unknown": 0, "warning": 1, "critical": 2}


def classify_metric(
    value: Optional[float],
    warn: float,
    crit: float,
    *,
    higher_is_worse: bool = True,
) -> str:
    """Classify a numeric metric against warn/crit thresholds.

    Returns "ok" | "warning" | "critical", or "unknown" if value is None.
    """
    if value is None:
        return "unknown"
    if higher_is_worse:
        if value >= crit:
            return "critical"
        if value >= warn:
            return "warning"
    else:
        if value <= crit:
            return "critical"
        if value <= warn:
            return "warning"
    return "ok"


def rollup_status(checks: List[Dict[str, Any]]) -> str:
    """Worst status across all checks -> overall status."""
    worst = "ok"
    for c in checks:
        if _SEVERITY.get(c.get("status"), 0) > _SEVERITY.get(worst, 0):
            worst = c["status"]
    return worst


def clerk_summary(overall: str) -> Dict[str, str]:
    """Plain-language rollup for non-technical staff — no numbers, no jargon."""
    table = {
        "ok": {
            "level": "ok",
            "label": "All systems normal",
            "detail": "Residents can submit and track requests normally.",
        },
        "warning": {
            "level": "warning",
            "label": "Minor issue — IT notified",
            "detail": "The system is running normally, but staff have been alerted to look into something.",
        },
        "critical": {
            "level": "critical",
            "label": "Service issue — IT notified",
            "detail": "Something needs attention and IT has been alerted. Some features may be affected.",
        },
    }
    return table.get(overall, table["ok"])


def is_worse(new_status: str, old_status: Optional[str]) -> bool:
    """True if new_status is more severe than old_status (for alert de-duping)."""
    return _SEVERITY.get(new_status, 0) > _SEVERITY.get(old_status or "ok", 0)


# --------------------------------------------------------------------------- #
# Metric collectors — each returns a check dict and never raises.
# --------------------------------------------------------------------------- #

def _check(key: str, label: str, status: str, value, message: str, action: str = "") -> Dict[str, Any]:
    return {"key": key, "label": label, "status": status, "value": value, "message": message, "action": action}


def _disk_check() -> Dict[str, Any]:
    try:
        usage = shutil.disk_usage("/")
        pct = round(usage.used / usage.total * 100, 1)
        status = classify_metric(pct, warn=80, crit=92)
        free_gb = round(usage.free / (1024 ** 3), 1)
        return _check(
            "disk", "Disk space", status, pct,
            f"Disk is {pct}% full ({free_gb} GB free).",
            "Delete old backups/logs or expand the volume before it fills." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] disk check failed: {e}")
        return _check("disk", "Disk space", "unknown", None, "Could not read disk usage.")


def _memory_check() -> Dict[str, Any]:
    try:
        total = avail = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])  # kB
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1])
                if total is not None and avail is not None:
                    break
        if not total or avail is None:
            return _check("memory", "Memory", "unknown", None, "Could not read memory usage.")
        pct = round((1 - avail / total) * 100, 1)
        status = classify_metric(pct, warn=85, crit=95)
        return _check(
            "memory", "Memory", status, pct,
            f"Memory is {pct}% used.",
            "Restart heavy services or add RAM; sustained high memory can crash containers." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] memory check failed: {e}")
        return _check("memory", "Memory", "unknown", None, "Could not read memory usage.")


async def _db_connection_check(db) -> Dict[str, Any]:
    try:
        from sqlalchemy import text
        used = (await db.execute(text("SELECT count(*) FROM pg_stat_activity"))).scalar()
        max_conn = (await db.execute(text("SHOW max_connections"))).scalar()
        max_conn = int(max_conn)
        pct = round(used / max_conn * 100, 1) if max_conn else None
        status = classify_metric(pct, warn=75, crit=90)
        return _check(
            "db_connections", "Database connections", status, pct,
            f"{used} of {max_conn} connections in use ({pct}%).",
            "Check for connection leaks or raise the pool/limit before it's exhausted." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] db connection check failed: {e}")
        return _check("db_connections", "Database connections", "unknown", None, "Could not read connection stats.")


async def _backup_age_check() -> Dict[str, Any]:
    try:
        from datetime import datetime
        from app.services.backup_service import get_backup_status
        status_info = await get_backup_status()
        last = status_info.get("last_backup") if isinstance(status_info, dict) else None
        if not last or not last.get("created_at"):
            return _check(
                "backup", "Backup freshness", "warning", None,
                "No database backup found yet.",
                "Run a backup now so a fresh restore point exists.",
            )
        created = last["created_at"]
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "").replace("+00:00", ""))
        hours = (datetime.utcnow() - created).total_seconds() / 3600
        status = classify_metric(round(hours, 1), warn=36, crit=72)
        return _check(
            "backup", "Backup freshness", status, round(hours, 1),
            f"Last backup was {round(hours)}h ago.",
            "Backups are stale — verify the backup task is running." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] backup age check failed: {e}")
        return _check("backup", "Backup freshness", "unknown", None, "Could not read backup status.")


async def _redis_check() -> Dict[str, Any]:
    try:
        import redis.asyncio as aioredis
        url = os.getenv("REDIS_URL") or "redis://redis:6379/0"
        client = aioredis.from_url(url, socket_timeout=3)
        try:
            info = await client.info("memory")
        finally:
            await client.aclose()
        used = info.get("used_memory", 0)
        max_mem = info.get("maxmemory", 0)
        used_mb = round(used / (1024 ** 2), 1)
        if not max_mem:
            # No cap configured — report healthy with the current footprint.
            return _check("redis", "Cache (Redis)", "ok", used_mb, f"Redis using {used_mb} MB (no cap set).")
        pct = round(used / max_mem * 100, 1)
        status = classify_metric(pct, warn=80, crit=92)
        return _check(
            "redis", "Cache (Redis)", status, pct,
            f"Redis memory at {pct}% of its cap ({used_mb} MB).",
            "Raise maxmemory or review the eviction policy before keys are evicted." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] redis check failed: {e}")
        return _check("redis", "Cache (Redis)", "unknown", None, "Could not reach Redis.")


async def _kms_check() -> Dict[str, Any]:
    """Is resident data still being encrypted with the key the town chose?

    This is the only check here whose failure is not recoverable by fixing it
    later, which is why it is critical rather than warning.

    A cloud KMS key that stops answering -- scheduled for deletion, permissions
    revoked, credentials expired -- does not raise anything. `_wrap_dek` falls
    back to the application key and carries on: new reports save fine, and the
    rows written under the old key quietly stop being readable. The gap can run
    for weeks, and if the cause was a scheduled deletion, the window to cancel
    it closes inside that time. After that the data is gone for good.

    So this compares what the town selected against what actually wrapped the
    data key just now. Those agreeing is the only evidence that the arrangement
    still works; a settings page showing a key name proves nothing, because the
    key name is still there when the key is not.
    """
    try:
        from app.core import pii_crypto
        from app.core.encryption import _kms_provider

        selected = _kms_provider()
        if selected not in ("google", "azure", "aws"):
            # No cloud KMS chosen. Encrypting with the application key is then
            # the configured behaviour, not a fault.
            return _check("kms", "Resident data encryption", "ok", "local",
                          "Resident data is encrypted with the application key, as configured.")

        # A live wrap, not `active_backend()`. That reads the data key this
        # process cached at startup, so a worker that has been running since
        # before the key broke would answer with the state of the world an
        # arbitrary time ago -- and would keep saying "ok" through the entire
        # deletion window, which is the one stretch where saying otherwise
        # matters. Wrapping a throwaway key costs one KMS call every fifteen
        # minutes and answers the question as of now.
        actual = pii_crypto.probe_backend()
        if actual == selected:
            return _check("kms", "Resident data encryption", "ok", actual,
                          f"Resident data is being encrypted with your {actual} key.")

        return _check(
            "kms", "Resident data encryption", "critical", actual,
            f"Your {selected} key is not being used — new resident data is being "
            f"encrypted with the application key instead.",
            action=(
                "Act today. Check that the key still exists and has not been scheduled "
                "for deletion, and that its credentials have not expired. Records saved "
                "before this started may already be unreadable, and if a deletion is "
                "pending it can only be cancelled inside the waiting period."
            ),
        )
    except Exception:
        logger.debug("KMS health probe failed", exc_info=True)
        return _check("kms", "Resident data encryption", "unknown", None,
                      "Could not determine which key is encrypting resident data.")


async def collect_checks(db) -> List[Dict[str, Any]]:
    """Run all proactive checks. Never raises; failed probes return 'unknown'."""
    checks = [
        _disk_check(),
        _memory_check(),
        await _db_connection_check(db),
        await _backup_age_check(),
        await _redis_check(),
        await _kms_check(),
    ]
    return checks


async def evaluate(db) -> Dict[str, Any]:
    """Full proactive-health evaluation for the API/alerting layers."""
    from datetime import datetime
    checks = await collect_checks(db)
    overall = rollup_status(checks)
    return {
        "overall_status": overall,
        "summary": clerk_summary(overall),
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }
