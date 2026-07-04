"""PII-safe telemetry — ORCHESTRATOR_PLAN.md A5.

The one endpoint the state's panel scrapes fleet-wide, so the rule is hard:
**metadata only, never resident data**. Response fields are limited to build
info, uptime, HTTP status counts, integration health counts, and API-usage
aggregates. The panel additionally sanitizes on its side, but nothing
PII-shaped may originate here.
"""

import hmac
import time
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models import ApiUsageRecord, UptimeRecord

router = APIRouter()

_process_started = time.time()
# Status-class counters ("2xx", "4xx", ...) filled by the middleware in
# app.main. In-process only — silo tenancy means one process set per town.
request_counts: Counter = Counter()


def record_request(status_code: int) -> None:
    request_counts[f"{status_code // 100}xx"] += 1


def require_panel_token(x_panel_token: str = Header(default="")) -> str:
    settings = get_settings()
    if not settings.provisioning_token:
        raise HTTPException(status_code=404, detail="Telemetry API is not enabled")
    if not hmac.compare_digest(x_panel_token, settings.provisioning_token):
        raise HTTPException(status_code=401, detail="Invalid panel token")
    return "panel"


@router.get("")
async def get_telemetry(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_panel_token),
):
    settings = get_settings()

    db_revision = None
    try:
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        db_revision = result.scalar_one_or_none()
    except Exception:
        pass

    # Latest health status per integration (counts only, no messages — vendor
    # error bodies can echo request contents).
    integration_health: dict[str, str] = {}
    try:
        since = datetime.utcnow() - timedelta(hours=24)
        result = await db.execute(
            select(UptimeRecord.service_name, UptimeRecord.status)
            .where(UptimeRecord.checked_at >= since)
            .order_by(UptimeRecord.checked_at)
        )
        for service_name, status in result.all():
            integration_health[service_name] = status  # last write wins = latest
    except Exception:
        pass

    # API usage/cost aggregates (30 days) — the api_usage table already holds
    # only counters, never request contents.
    api_usage: dict[str, dict[str, int]] = {}
    try:
        since = datetime.utcnow() - timedelta(days=30)
        result = await db.execute(
            select(
                ApiUsageRecord.service_name,
                func.sum(ApiUsageRecord.api_calls),
                func.sum(ApiUsageRecord.tokens_input),
                func.sum(ApiUsageRecord.tokens_output),
                func.sum(ApiUsageRecord.characters),
            )
            .where(ApiUsageRecord.created_at >= since)
            .group_by(ApiUsageRecord.service_name)
        )
        for service, calls, tin, tout, chars in result.all():
            api_usage[service] = {
                "calls": int(calls or 0),
                "tokens_input": int(tin or 0),
                "tokens_output": int(tout or 0),
                "characters": int(chars or 0),
            }
    except Exception:
        pass

    return {
        "version": settings.app_version,
        "git_sha": settings.git_sha,
        "db_revision": db_revision,
        "min_db_revision": settings.min_db_revision,
        "uptime_seconds": int(time.time() - _process_started),
        "request_counts": dict(request_counts),
        "integration_health": integration_health,
        "api_usage": api_usage,
        "timestamp": datetime.utcnow().isoformat(),
    }
