"""Sentry crash reporting, from the environment or from the saved credential.

The DSN used to be read only from the SENTRY_DSN environment variable, once, at
import. The setup page saves it as a credential instead (into the town's secret
store), and nothing ever read that back -- so a town that entered its DSN on the
"Crash reporting" card had no crash reporting at all, and no sign of it.

Now: the environment variable still wins when set (host-level configuration),
otherwise the saved credential is used. The API loads it at startup, the worker
when each worker process starts.
"""
import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _crash_reporting_wanted(event, hint):
    """Drop the event when the town has switched crash reporting off.

    Reads a cached snapshot rather than the database: this runs on the error
    path, and the error being reported may be that the database is unreachable.
    A process that has not yet read the switch sends the event, because
    swallowing the crash that stopped it from reading is the worse failure.
    """
    try:
        from app.services.capability_switches import wanted_sync

        if not wanted_sync("errors"):
            return None
    except Exception:
        # Never let this decide to lose a crash report.
        pass
    return event


def is_active() -> bool:
    import sentry_sdk
    return sentry_sdk.get_client().is_active()


def init(dsn: str, source: str) -> bool:
    """Start Sentry with `dsn`. Returns whether it is active afterwards."""
    import sentry_sdk

    if is_active():
        return True
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        environment=os.environ.get("ENVIRONMENT", "production"),
        send_default_pii=False,  # no resident or staff identity in reports
        before_send=_crash_reporting_wanted,
    )
    active = is_active()
    if active:
        logger.info("[Sentry] crash reporting on (DSN from %s)", source)
    return active


def init_from_env() -> bool:
    dsn = os.environ.get("SENTRY_DSN")
    return init(dsn, "environment") if dsn else False


async def _saved_dsn() -> Optional[str]:
    from app.services.secret_manager import get_secret
    try:
        return await asyncio.wait_for(get_secret("SENTRY_DSN"), timeout=15)
    except Exception as exc:
        logger.warning("[Sentry] could not read the saved DSN: %s", type(exc).__name__)
        return None


async def init_from_saved_credential() -> bool:
    """For the API's startup. No-op when already started from the environment."""
    if is_active() or init_from_env():
        return True
    dsn = await _saved_dsn()
    return init(dsn, "saved credential") if dsn else False


def init_in_worker(**_kwargs) -> None:
    """Celery worker_process_init / worker_init hook. Never raises."""
    try:
        if is_active() or init_from_env():
            return
        dsn = asyncio.run(_saved_dsn())
        if dsn:
            init(dsn, "saved credential")
    except Exception as exc:
        logger.warning("[Sentry] worker crash reporting not started: %s", type(exc).__name__)
