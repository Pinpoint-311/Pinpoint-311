"""Structured results shared by the steps, the engine, reporters and the CLI."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Step statuses
OK = "ok"
FAILED = "failed"
NEEDS_APPROVAL = "needs_approval"
SKIPPED = "skipped"
WARNING = "warning"
PLANNED = "planned"  # dry run: the step would run


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class StepResult:
    name: str
    status: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0
    at: str = field(default_factory=utcnow)

    @property
    def ok(self) -> bool:
        return self.status in (OK, SKIPPED, WARNING, PLANNED)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Timer:
    def __init__(self) -> None:
        self.start = time.monotonic()

    def elapsed(self) -> float:
        return round(time.monotonic() - self.start, 2)


# Run outcomes (the CLI maps each to an exit code; see exitcodes.py)
SUCCEEDED = "succeeded"
NOOP = "noop"
REFUSED = "refused"            # stopped in preflight/backup/pull; nothing changed
GATED = "needs_approval"       # destructive migration held; old version serving
MIGRATION_FAILED = "migration_failed"
ROLLED_BACK = "rolled_back"    # new version unhealthy; previous digests restored
ROLLBACK_FAILED = "rollback_failed"
PLANNED_OUTCOME = "planned"
VERIFIED = "verified"
ERROR = "error"


@dataclass
class RunContext:
    instance: str
    action: str
    tag: Optional[str] = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=utcnow)
    requested_by: Optional[str] = None
    request_id: Optional[str] = None
    insecure: bool = False


@dataclass
class RunOutcome:
    outcome: str
    summary: str
    steps: list[StepResult] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    finished_at: str = field(default_factory=utcnow)

    def as_dict(self, run: Optional[RunContext] = None) -> dict[str, Any]:
        d = {
            "outcome": self.outcome,
            "summary": self.summary,
            "steps": [s.as_dict() for s in self.steps],
            "data": self.data,
            "finished_at": self.finished_at,
        }
        if run is not None:
            d = {"run_id": run.run_id, "instance": run.instance, "action": run.action, "tag": run.tag,
                 "requested_by": run.requested_by, "request_id": run.request_id,
                 "insecure_skip_verify": run.insecure, "started_at": run.started_at, **d}
        return d
