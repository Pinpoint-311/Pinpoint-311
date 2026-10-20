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


def escalations(
    checks: List[Dict[str, Any]], previous: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Which checks just got worse and are worth emailing about.

    A muted check is one an admin has already said "I know" about, so it does
    not page anyone -- but note that `evaluate` still returns it, at its real
    status. The mute is applied here, at the mail, and nowhere else.
    """
    return [
        c for c in checks
        if c.get("status") in ("warning", "critical")
        and not c.get("muted")
        and is_worse(c["status"], previous.get(c.get("key")))
    ]


def next_alert_state(
    checks: List[Dict[str, Any]], previous: Dict[str, Any]
) -> Dict[str, Any]:
    """The per-check state to persist after a scan.

    Normally the new status, so a recovery resets the de-duping and the next
    failure is news again. The exception is a muted check that is still bad,
    which keeps whatever state it had: a mute *defers* an alert, it does not
    cancel it. Recording "critical" while nobody was told would mean that when
    the mute expires the check is no longer worse than last time, and the mail
    nobody ever received would never arrive at all.
    """
    return {
        c["key"]: (
            previous.get(c["key"])
            if c.get("muted") and c.get("status") in ("warning", "critical")
            else c.get("status")
        )
        for c in checks
    }


# --------------------------------------------------------------------------- #
# Metric collectors — each returns a check dict and never raises.
# --------------------------------------------------------------------------- #

def _check(key: str, label: str, status: str, value, message: str, action: str = "") -> Dict[str, Any]:
    return {"key": key, "label": label, "status": status, "value": value, "message": message, "action": action}


def _disk_check() -> Dict[str, Any]:
    """Every filesystem this deployment writes to, not just the root one.

    `shutil.disk_usage("/")` reads whatever is behind the container's root. On a
    default Docker install that is the host disk, so it was usually right by
    accident. Photos (`uploads_data`) and pre-migration database dumps
    (`migration_backups`) are named volumes, and a town that puts either on a
    second disk was having the wrong one watched -- the root filesystem stays
    comfortable while the volume taking a photo per report fills.
    """
    try:
        from app.services.system_probes import read_disks, worst_disk

        worst = worst_disk(read_disks())
        if not worst:
            return _check("disk", "Disk space", "unknown", None, "Could not read disk usage.")
        pct = worst["percent"]
        status = classify_metric(pct, warn=80, crit=92)
        free_gb = round(worst["free"] / (1024 ** 3), 1)
        where = worst.get("label") or worst.get("path")
        return _check(
            "disk", "Disk space", status, pct,
            f"{where} is {pct}% full ({free_gb} GB free).",
            "Delete old backups/logs or expand the volume before it fills." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] disk check failed: {e}")
        return _check("disk", "Disk space", "unknown", None, "Could not read disk usage.")


def _memory_check() -> Dict[str, Any]:
    """The limit that kills this container, not the RAM in the machine.

    `/proc/meminfo` is the host's -- it is not namespaced, so a container reads
    the whole server's memory no matter how small its own cap. compose caps the
    backend at 1G; on a 32GB server, a backend at 990MB and one allocation away
    from being OOM-killed mid-report reported 3% used and a green tick. The
    cgroup limit is read first and the host is only the fallback, for a
    deployment that genuinely runs uncapped.
    """
    try:
        from app.services.system_probes import read_memory

        reading = read_memory()
        pct = reading["percent"]
        if pct is None:
            return _check("memory", "Memory", "unknown", None, "Could not read memory usage.")
        status = classify_metric(pct, warn=85, crit=95)
        limit_gb = round((reading["limit_bytes"] or 0) / (1024 ** 3), 2)
        scope = ("this container's limit" if reading["scope"] == "container"
                 else "the server's RAM")
        return _check(
            "memory", "Memory", status, pct,
            f"Memory is {pct}% of {scope} ({limit_gb} GB).",
            "Raise the container's memory limit or reduce what is running; at 100% it is "
            "killed and restarted." if status != "ok" else "",
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
            "Restart the app if this keeps climbing, or raise the database connection limit before it runs out." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] db connection check failed: {e}")
        return _check("db_connections", "Database connections", "unknown", None, "Could not read connection stats.")


async def _backup_age_check() -> Dict[str, Any]:
    try:
        from datetime import datetime, timezone
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
            # Both replaces used to run, stripping the offset back off an ISO
            # string to produce a NAIVE datetime, which cannot be subtracted
            # from an aware `now`. The TypeError landed in the except below and
            # this check reported "unknown" on every single sweep -- so the one
            # check that verifies a town's backups are still running could never
            # fire, and a town whose backups stopped months ago looked exactly
            # like a town whose backups were fine.
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        status = classify_metric(round(hours, 1), warn=36, crit=72)
        return _check(
            "backup", "Backup freshness", status, round(hours, 1),
            f"Last backup was {round(hours)}h ago.",
            "Backups are overdue. Check that scheduled backups are running." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] backup age check failed: {e}")
        return _check("backup", "Backup freshness", "unknown", None, "Could not read backup status.")


async def _backup_tools_check() -> Dict[str, Any]:
    """Can a backup be taken and restored on this image, right now?

    Backup freshness only notices a broken backup after the next scheduled run
    has failed; 1.9.0-rc1 shipped without gpg and nobody knew until 02:00. This
    checks the programs (and a real gpg round trip) every scan, so an admin
    hears within 15 minutes of a bad deploy. Skipped when backups are not set up.
    """
    try:
        from app.services.backup_service import get_backup_config
        from app.services import runtime_tools
        if not await get_backup_config():
            return _check("backup_tools", "Backups can run", "ok", "not configured",
                          "Backups are not set up, so there is nothing to check.")
        problems = runtime_tools.backup_readiness()
        if problems:
            return _check(
                "backup_tools", "Backups can run", "critical", len(problems),
                "Backups will fail on this server: " + "; ".join(problems) + ".",
                "Redeploy an image that includes these programs, then run a backup from "
                "Compliance > Database Backups to confirm.",
            )
        return _check("backup_tools", "Backups can run", "ok", 0,
                      "Backup programs are installed and encryption works.")
    except Exception as e:
        logger.warning(f"[proactive] backup tools check failed: {e}")
        return _check("backup_tools", "Backups can run", "unknown", None, "Could not check backup programs.")


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
            return _check("redis", "Cache (Redis)", "ok", used_mb, f"The cache is using {used_mb} MB (no limit set).")
        pct = round(used / max_mem * 100, 1)
        status = classify_metric(pct, warn=80, crit=92)
        return _check(
            "redis", "Cache (Redis)", status, pct,
            f"The cache is using {pct}% of its memory limit ({used_mb} MB).",
            "Raise the cache's memory limit (the Redis maxmemory setting) before it fills up." if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] redis check failed: {e}")
        return _check("redis", "Cache (Redis)", "unknown", None, "Could not reach Redis.")


# Names an admin recognizes, for the provider ids stored in settings.
_KMS_LABELS = {"google": "Google Cloud KMS", "azure": "Azure Key Vault", "aws": "AWS KMS"}


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
        if actual == selected and selected == "azure":
            return _azure_key_posture_check()
        if actual == selected:
            return _check("kms", "Resident data encryption", "ok", actual,
                          f"Resident data is being encrypted with your {_KMS_LABELS.get(actual, actual)} key.")

        return _check(
            "kms", "Resident data encryption", "critical", actual,
            f"Your {_KMS_LABELS.get(selected, selected)} key is not being used. New resident "
            f"data is being encrypted with this server's own key instead.",
            action=(
                "Act today. Check that the key still exists and has not been scheduled "
                "for deletion, and that its credentials have not expired. Records saved "
                "before this started may already be unreadable, and if a deletion is "
                "pending it can only be canceled inside the waiting period."
            ),
        )
    except Exception:
        logger.debug("KMS health probe failed", exc_info=True)
        return _check("kms", "Resident data encryption", "unknown", None,
                      "Could not determine which key is encrypting resident data.")


def _azure_key_posture_check() -> Dict[str, Any]:
    """The Azure key works; can it still be lost?

    Losing the key is losing every resident's contact details, in every backup
    too. Two settings decide whether a mistake is recoverable, and both are on
    the key itself, where the app can read them:

      * purge protection: without it ("...+Purgeable"), a deleted key can be
        purged at once, and nothing brings it back;
      * an expiry date (Azure Policy recommends one): past it, every unwrap is
        refused -- recoverable by extending the date, if someone notices first.
    """
    import time
    from app.core import azure_keyvault
    try:
        posture = azure_keyvault.key_posture()
    except Exception:
        return _check("kms", "Resident data encryption", "ok", "azure",
                      "Resident data is being encrypted with your Azure Key Vault key. "
                      "(Its deletion protection could not be read.)")
    level = posture.get("recovery_level") or ""
    if "Purgeable" in level or not level.startswith("Recoverable"):
        return _check(
            "kms", "Resident data encryption", "warning", "azure",
            "Your Azure key is in use, but purge protection is off: a deleted key "
            "could be purged immediately, and every resident's contact details "
            "with it, backups included.",
            action=("Turn on purge protection for the Key Vault (it cannot be turned "
                    "off again), and add a CanNotDelete lock on the vault. See "
                    "docs/DISASTER_RECOVERY.md, 'Losing the encryption key'."),
        )
    expires = posture.get("expires")
    if expires and expires - time.time() < 30 * 86400:
        days = max(0, int((expires - time.time()) // 86400))
        return _check(
            "kms", "Resident data encryption", "critical" if days < 7 else "warning", "azure",
            f"Your Azure key expires in {days} day(s). After that resident data "
            "cannot be decrypted until the date is extended.",
            action="Extend the key's expiration date in the Key Vault, or rotate the key.",
        )
    return _check("kms", "Resident data encryption", "ok", "azure",
                  f"Resident data is being encrypted with your Azure Key Vault key "
                  f"(purge protection on, {posture.get('recoverable_days') or '?'}-day recovery window).")


async def _redaction_check() -> Dict[str, Any]:
    """Is the detector a town chose the one actually blurring its photos?

    Redaction fails more quietly than anything else here. A cloud detector with
    no credentials returns an empty result, and so does a photo of an empty
    street -- the two are the same value. Photos get stored, the card stays
    green, and nobody finds out until a resident's face is on the public map.

    The dispatch now degrades to on-server detection rather than to nothing, so
    the harm is contained. But degraded is still not what the town selected: it
    is paying for Azure and getting the on-server fallback, which finds fewer
    faces. That is worth a warning rather than silence.

    The on-server plate model is checked too: selected but missing or broken,
    every photo is withheld (fail closed) -- safe, but not what anyone wants.
    """
    try:
        from app.services.image_redaction import (
            _usable, effective_provider, face_fallback, plate_detector, resolve_provider,
        )

        plate_warning = await _plate_model_check(plate_detector)

        selected = await resolve_provider()
        if not selected:
            return plate_warning or _check("redaction", "Photo redaction", "ok", "off",
                                           "Photo redaction is switched off, as configured.")

        actual, degraded_from = await effective_provider(selected)

        if degraded_from == actual:
            return _check(
                "redaction", "Photo redaction", "critical", "none",
                "No detector is available — resident photos are being stored "
                "without blurring faces or license plates.",
                action=(
                    "Check the Photo Redaction card. On-server detection needs no "
                    "account and works anywhere, so this usually means this server's "
                    "install is missing OpenCV, not that a credential is wrong."
                ),
            )

        if degraded_from:
            fallback = await face_fallback()
            name = "YuNet" if fallback == "yunet" else "OpenCV"
            return _check(
                "redaction", "Photo redaction", "warning", actual,
                f"Degraded: on-server fallback in use. {degraded_from} has no usable "
                f"credentials, so faces are being blurred on this server ({name}). "
                f"Photos are still redacted, less accurately.",
                action=(
                    f"Fix the {degraded_from} credentials on the Photo Redaction card, "
                    f"or choose on-server detection so the page matches what is running."
                ),
            )

        if plate_warning:
            return plate_warning
        return _check("redaction", "Photo redaction", "ok", actual,
                      f"Faces and plates are being blurred using {actual}.")
    except Exception:
        logger.debug("Redaction health probe failed", exc_info=True)
        return _check("redaction", "Photo redaction", "unknown", None,
                      "Could not determine which detector is redacting photos.")


async def _plate_model_check(plate_detector) -> Optional[Dict[str, Any]]:
    """Warn when an on-server plate detector is selected and cannot run."""
    mode = await plate_detector()
    if mode == "yolo":
        from app.services import onnx_detectors

        status = onnx_detectors.plate_holder.status()
        if status["present"] and not status["error"]:
            return None
        problem = ("its model file is missing" if not status["present"]
                   else f"its model failed to load ({status['error'][:120]})")
        return _check(
            "redaction", "Photo redaction", "warning", "plate-model-unavailable",
            f"The on-server license plate detector is selected but {problem}. "
            f"Photos are being held back for staff review until it works.",
            action=(f"Put {status['file']} in the models directory "
                    f"({onnx_detectors.models_dir()}) — see docs/PHOTO_REDACTION_MODELS.md — "
                    f"or choose text recognition on the Photo Redaction card."),
        )
    if mode == "redactor":
        from app.services.image_redaction import redactor_health

        health = await redactor_health()
        if health and health.get("status") == "ok":
            return None
        return _check(
            "redaction", "Photo redaction", "warning", "redactor-unavailable",
            "The experimental EgoBlur plate detector is selected but the redactor service "
            "is unreachable or has no model files. Photos are being held back.",
            action="See redactor/README.md, or choose the default plate detector.",
        )
    return None


async def _cpu_check(window: float = 0.4) -> Dict[str, Any]:
    """CPU, as a share of what this container is allowed rather than the host's.

    Reported, not alerted on: one short sample cannot tell a PDF being rendered
    from a server in trouble, and an email a day about a spike is an email
    nobody reads. It is here because "the site feels slow" is a real report and
    this is the number that answers it.
    """
    try:
        import asyncio

        from app.services.system_probes import (
            cpu_percent, read_cpu_allowance, read_cpu_seconds,
        )

        cores = read_cpu_allowance()
        before = read_cpu_seconds()
        if before is None:
            return _check("cpu", "CPU", "unknown", None, "Could not read CPU usage.")
        await asyncio.sleep(window)
        after = read_cpu_seconds()
        pct = cpu_percent(
            None if after is None else after - before, window, cores)
        if pct is None:
            return _check("cpu", "CPU", "unknown", None, "Could not read CPU usage.")
        allowance = f"{cores:g} core{'s' if cores and cores != 1 else ''}" if cores else "the server's cores"
        return _check("cpu", "CPU", "ok", pct,
                      f"CPU was {pct}% of {allowance} over the last {window:g}s.")
    except Exception as e:
        logger.warning(f"[proactive] cpu check failed: {e}")
        return _check("cpu", "CPU", "unknown", None, "Could not read CPU usage.")


async def _retention_check(db) -> Dict[str, Any]:
    """Has this town set a retention period, and said what a run removes?

    This belongs here rather than only on the compliance tab because the
    unconfigured state is silent everywhere else and does not resolve itself.
    Nothing is archived or deleted until both halves are set, which means every
    name, phone number and free-text description a resident has ever submitted
    is still on the record — and a town's own published privacy policy usually
    says otherwise. Data minimisation is an obligation in its own right; the
    absence of a policy is a live condition, not a blank field.

    Warning rather than critical, and the distinction is about direction. Nothing
    is being destroyed while this is unset, so it is recoverable — a town can
    configure it tomorrow and the records are all still there. Contrast
    `_kms_check`, which is critical because its failure window closes on data
    that cannot be got back. But it stays a warning permanently, and says what
    is actually happening rather than "not configured".
    """
    try:
        from app.services.retention_config import load_retention_config

        config = await load_retention_config(db)
        if config.configured:
            days = config.retention_days
            years = days / 365
            period = f"{years:.1f} years".replace(".0 ", " ") if days >= 365 else f"{days} days"
            return _check("retention", "Records retention", "ok", f"{days} days",
                          f"Closed requests are kept for {period}, then "
                          f"{'every field is cleared' if config.mode == 'purge' else 'the chosen fields are cleared'} "
                          f"({len(config.scrub_fields or [])} selected). One period for all "
                          f"records, set by this town.")

        return _check(
            "retention", "Records retention", "warning", None,
            config.detail or "No records-retention schedule is configured.",
            action=(
                "Open Settings → Compliance → Document Retention and set how long closed "
                "requests are kept, and what a run removes from them. Your clerk has the "
                "town's approved records retention schedule. Until both are set, resident "
                "personal data is kept indefinitely."
            ),
        )
    except Exception:
        logger.debug("Retention health probe failed", exc_info=True)
        return _check("retention", "Records retention", "unknown", None,
                      "Could not determine which retention schedule is in force.")


async def _translation_budget_check() -> Dict[str, Any]:
    """Is translation close to, or at, the town's spend budget?

    Warning at 80% of the day's or the month's character budget, critical at
    100%. At 100% residents are being served the source text instead of a
    translation -- deliberately, so a scraper cannot run up the bill -- and the
    admin is the one person who can decide whether that is right today. Read
    from the shared counters in services/translation_budget.py.
    """
    try:
        from app.services import translation_budget as tb

        u = await tb.usage()
        day, month = u["day"], u["month"]
        # Whichever period is closer to its ceiling is the one to talk about.
        worst = max((day, month), key=lambda v: (["ok", "warning", "critical"].index(tb.status_of(v)), v["percent"]))
        status = tb.status_of(worst)
        which = "today's" if worst is day else "this month's"
        resets = "at midnight UTC" if worst is day else "on the 1st (UTC)"
        message = (
            f"Translation has used {worst['used']:,} of {which} {worst['limit']:,}-character "
            f"budget ({worst['percent']:g}%)."
        )
        if status == "critical":
            message += f" Residents see untranslated text until it resets {resets}."
        return _check(
            "translation_budget", "Translation budget", status, worst["percent"], message,
            ("Raise the budget on Settings > Service Providers > Translation Provider if this use "
             "is expected; if it is not, the traffic is worth investigating before it resets.")
            if status != "ok" else "",
        )
    except Exception as e:
        logger.warning(f"[proactive] translation budget check failed: {e}")
        return _check("translation_budget", "Translation budget", "unknown", None,
                      "Could not read translation usage.")


async def _critical_facilities_check(db) -> Dict[str, Any]:
    """Is the store behind "near a hospital / school" current?

    Warning, not critical: an empty or stale store means reports lose their
    proximity context (and the AI its priority nudge), not that anything is
    lost. Only while a boundary is configured -- without one there is nothing
    to fetch, and the boundary has its own place in setup.
    """
    try:
        from datetime import datetime, timezone

        from app.services import critical_facilities as cf

        # In a savepoint: a database still without the table must not abort
        # the transaction the remaining health reads share.
        async with db.begin_nested():
            st = await cf.store_status(db)
        detail = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in st.items()}
        counts = ", ".join(
            f"{n} {cf.KIND_LABELS.get(k, k).lower()}" for k, n in sorted(st["counts"].items())
        ) or "none"
        error = f" Last error: {st['last_error']}" if st.get("last_error") else ""
        action = ("It keeps retrying on its own. If it keeps failing, check that the server can "
                  "reach the public OpenStreetMap (Overpass) servers, or set OVERPASS_URLS to one "
                  "the town trusts.")
        if not st["boundary_configured"]:
            check = _check("critical_facilities", "Critical facilities", "ok", "no boundary",
                           "No town boundary is set, so there is no area to load hospitals, "
                           "schools and fire stations for.")
        elif not st["total"]:
            since = st.get("failing_since")
            if since is None or datetime.now(timezone.utc) - since < cf.EMPTY_GRACE:
                # Not loaded yet: a new install, or the public Overpass
                # instance busy on the first tries. Retried hourly; not an
                # alert until it has kept failing for a day.
                check = _check("critical_facilities", "Critical facilities", "ok", 0,
                               "Loading the town's hospitals, schools and fire stations. "
                               "Retried every hour until it succeeds." + error)
            else:
                check = _check("critical_facilities", "Critical facilities", "warning", 0,
                               "No hospitals, schools or fire stations have loaded for over a "
                               "day, so reports show nothing near them." + error, action)
        else:
            refreshed = st.get("refreshed_at")
            age = datetime.now(timezone.utc) - refreshed if refreshed else None
            when = refreshed.strftime("%Y-%m-%d") if refreshed else "unknown"
            if age is None or age > cf.STALE_AFTER:
                check = _check("critical_facilities", "Critical facilities", "warning", st["total"],
                               f"Facility list last refreshed {when}, over "
                               f"{cf.STALE_AFTER.days} days ago ({counts})." + error, action)
            else:
                check = _check("critical_facilities", "Critical facilities", "ok", st["total"],
                               f"{st['total']} loaded, refreshed {when}: {counts}." + error)
        check["detail"] = detail
        return check
    except Exception:
        logger.debug("Critical facilities health probe failed", exc_info=True)
        return _check("critical_facilities", "Critical facilities", "unknown", None,
                      "Could not read the critical-facility store.")


async def _arcgis_sync_check(db) -> Dict[str, Any]:
    """Has an automatic ArcGIS sync been held back for review?

    Warning: the layer still shows its previous features, so nothing is
    broken, but the town's data has moved on and an admin has to decide.
    """
    try:
        from app.services import arcgis_import

        async with db.begin_nested():
            held = await arcgis_import.held_layers(db)
        if not held:
            return _check("arcgis_sync", "ArcGIS layer sync", "ok", 0,
                          "No automatic ArcGIS layer sync is waiting for review.")
        named = "; ".join(f"{name}: {reason}" for name, reason in held[:5])
        more = f" (and {len(held) - 5} more)" if len(held) > 5 else ""
        return _check(
            "arcgis_sync", "ArcGIS layer sync", "warning", len(held),
            f"Automatic sync held back the update for {len(held)} map layer"
            f"{'s' if len(held) != 1 else ''}, which keep their previous features. {named}{more}",
            "Open Admin Console > Map Layers, check the layer's source, then choose Apply anyway "
            "or turn auto-sync off.")
    except Exception:
        logger.debug("ArcGIS sync health probe failed", exc_info=True)
        return _check("arcgis_sync", "ArcGIS layer sync", "unknown", None,
                      "Could not read the map layers' sync state.")


# Every key `collect_checks` can emit. Named here so the mute route can refuse
# a key that is not a real check -- muting is a write, and without an allowlist
# any admin request could insert arbitrary rows into the health table.
CHECK_KEYS = (
    "disk",
    "memory",
    "cpu",
    "db_connections",
    "backup",
    "backup_tools",
    "redis",
    "kms",
    "redaction",
    "retention",
    "translation_budget",
    "critical_facilities",
    "arcgis_sync",
)


async def collect_checks(db) -> List[Dict[str, Any]]:
    """Run all proactive checks. Never raises; failed probes return 'unknown'."""
    checks = [
        _disk_check(),
        _memory_check(),
        await _cpu_check(),
        await _db_connection_check(db),
        await _backup_age_check(),
        await _backup_tools_check(),
        await _redis_check(),
        await _kms_check(),
        await _redaction_check(),
        await _retention_check(db),
        await _translation_budget_check(),
        await _critical_facilities_check(db),
        await _arcgis_sync_check(db),
    ]
    return checks


async def evaluate(db) -> Dict[str, Any]:
    """Full proactive-health evaluation for the API/alerting layers."""
    from datetime import datetime, timezone
    checks = await collect_checks(db)

    # Mute state rides along; it does not filter. `overall_status` below is
    # computed from the real statuses, and a muted check keeps its own -- so
    # the panel still shows the problem, marked muted, and only the mail
    # stops. A mute that dropped the row would be a dismiss button that
    # deletes evidence, which is the failure this subsystem exists to prevent.
    try:
        from app.services import health_mutes

        await health_mutes.annotate(db, checks)
    except Exception:
        logger.debug("Could not read health mutes", exc_info=True)
        for c in checks:
            c.setdefault("muted", False)
            c.setdefault("muted_until", None)

    overall = rollup_status(checks)
    return {
        "overall_status": overall,
        "summary": clerk_summary(overall),
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
