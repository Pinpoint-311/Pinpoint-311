"""Where step outcomes go.

``Reporter`` is the interface Phase 3 implements to post progress back to the
instance (``/api/internal/updater/*``); today there is the JSONL log every run
appends to and the console printer. Everything a reporter receives has been
redacted.
"""

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO, Iterable, Optional

from pinpoint_updater.models import RunContext, RunOutcome, StepResult
from pinpoint_updater.redact import redact


class Reporter(ABC):
    @abstractmethod
    def step(self, run: RunContext, result: StepResult) -> None:
        """Called as each step finishes (and once more for each dry-run step)."""

    @abstractmethod
    def finished(self, run: RunContext, outcome: RunOutcome) -> None:
        """Called once, at the end of a run, with the whole outcome."""


class NullReporter(Reporter):
    def step(self, run, result):
        pass

    def finished(self, run, outcome):
        pass


class MultiReporter(Reporter):
    def __init__(self, reporters: Iterable[Reporter]):
        self.reporters = list(reporters)

    def step(self, run, result):
        for r in self.reporters:
            try:
                r.step(run, result)
            except Exception as exc:  # a reporter must never break an upgrade
                print(f"pinpoint-updater: reporter {type(r).__name__} failed: {redact(str(exc))}", file=sys.stderr)

    def finished(self, run, outcome):
        for r in self.reporters:
            try:
                r.finished(run, outcome)
            except Exception as exc:
                print(f"pinpoint-updater: reporter {type(r).__name__} failed: {redact(str(exc))}", file=sys.stderr)


class JsonlReporter(Reporter):
    """Append one JSON object per step and one per outcome to
    ``<log_dir>/<instance>.jsonl``. Opened in append mode per write, so lines
    from concurrent runs of different instances never interleave in a file."""

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)

    def _write(self, instance: str, record: dict) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(redact(record), sort_keys=True, default=str)
        path = self.log_dir / f"{instance}.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        try:
            os.write(fd, (line + "\n").encode())
        finally:
            os.close(fd)

    def step(self, run, result):
        self._write(run.instance, {
            "type": "step", "run_id": run.run_id, "instance": run.instance, "action": run.action,
            "tag": run.tag, **result.as_dict(),
        })

    def finished(self, run, outcome):
        record = outcome.as_dict(run)
        record["steps"] = [s["name"] + ":" + s["status"] for s in record["steps"]]
        self._write(run.instance, {"type": "outcome", **record})


_SYMBOL = {"ok": "ok  ", "failed": "FAIL", "needs_approval": "HOLD", "skipped": "skip",
           "warning": "warn", "planned": "plan"}


class ConsoleReporter(Reporter):
    """Human progress lines. Silent in --json mode (the final JSON is the output)."""

    def __init__(self, stream: Optional[IO[str]] = None, quiet: bool = False):
        self.stream = stream or sys.stdout
        self.quiet = quiet

    def step(self, run, result):
        if self.quiet:
            return
        detail = redact(result.detail)
        first, *rest = (detail or "").splitlines() or [""]
        print(f"  [{_SYMBOL.get(result.status, result.status)}] {result.name:<10} {first}", file=self.stream)
        for line in rest[:12]:
            print(f"                    {line}", file=self.stream)
        self.stream.flush()

    def finished(self, run, outcome):
        if self.quiet:
            return
        print(f"\n{outcome.outcome.upper()}: {redact(outcome.summary)}", file=self.stream)
        self.stream.flush()
