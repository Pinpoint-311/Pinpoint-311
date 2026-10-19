"""The upgrade steps, each a small function returning a ``StepResult``.

Ordering and semantics are ported from centralizedhosting/orchestrator:

* preflight compatibility window — rollout.py ``_precheck_compatibility``:
  the instance's observed ``db_revision`` must be exactly ``min_db_revision`` or
  ``db_revision`` of the release (set membership, not a range: Alembic
  revisions are not ordered strings);
* migrate-or-not — rollout.py ``_needs_migration``: unknown means yes, because
  the migrator is idempotent and skipping it on a stale schema is the failure;
* backup → pull → migrate → recreate — migrator.py, for the reasons in its
  module docstring (snapshot while the old schema is intact; a registry outage
  costs nothing before anything stops; expand migrations run before new code
  serves);
* migration exit codes — migrator.py ``GATE_BLOCKED``/``GATE_NO_BACKUP``, owned
  by backend/app/db/migrate.py (2 = destructive migration pending, needs a
  human; 3 = its pre-migration dump failed, nothing applied);
* post-upgrade health — rollout.py ``_upgrade_step``: the instance must report
  the release's version and db_revision ("migrations did not land" otherwise).
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from pinpoint_updater.compose import Compose
from pinpoint_updater.config import InstanceConfig, UpdaterConfig
from pinpoint_updater.cosign import CosignVerifier
from pinpoint_updater.health import AppProbe, ProbeError
from pinpoint_updater.lockfile import ImageSet
from pinpoint_updater.models import (
    FAILED, NEEDS_APPROVAL, OK, PLANNED, SKIPPED, WARNING, StepResult, Timer,
)
from pinpoint_updater.redact import redact
from pinpoint_updater.sources import ReleaseSource, ResolvedRelease

GATE_BLOCKED = 2
GATE_NO_BACKUP = 3
ALLOW_DESTRUCTIVE_ENV = "PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION"

_UNREACHABLE: dict = {}


@dataclass
class Deps:
    """Everything a step touches, injectable for tests."""

    config: UpdaterConfig
    name: str
    instance: InstanceConfig
    source: ReleaseSource
    verifier: CosignVerifier
    compose: Compose
    probe: AppProbe
    insecure: bool = False
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    disk_usage: Callable[[Any], Any] = shutil.disk_usage


def images_for(release: ResolvedRelease) -> ImageSet:
    return ImageSet(version=release.tag, backend=release.backend_ref, frontend=release.frontend_ref,
                    app_version=release.version)


def norm_version(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = str(v).strip()
    return v[1:] if v[:1] in ("v", "V") and v[1:2].isdigit() else v


def _check(name: str, ok: bool, detail: str, *, warn: bool = False) -> dict:
    return {"name": name, "ok": ok, "status": (WARNING if warn else (OK if ok else FAILED)), "detail": redact(detail)}


# --------------------------------------------------------------------------
# 1. preflight
# --------------------------------------------------------------------------

def read_health(deps: Deps) -> dict:
    """One pre-upgrade read, shared by the compatibility gate and the migration
    decision (rollout.py ``_pre_upgrade_health``: probing twice lets the two
    checks disagree about the schema they saw)."""
    try:
        return deps.probe.quick()
    except ProbeError:
        return _UNREACHABLE


def compatibility(release: ResolvedRelease, health: dict) -> tuple[bool, str]:
    """rollout.py ``_precheck_compatibility``, with "unreachable" a failure: the
    updater always applies, so it is never in render-only mode."""
    if health is _UNREACHABLE:
        return False, "instance unreachable for the pre-flight schema check"
    observed = health.get("db_revision")
    if not release.min_db_revision:
        return True, (f"release declares no min_db_revision; observed {observed!r} "
                      "(the migrator still refuses anything destructive)")
    if observed and observed not in {release.min_db_revision, release.db_revision}:
        return False, (f"db_revision {observed} outside compatibility window "
                       f"[{release.min_db_revision} .. {release.db_revision}]")
    if not observed:
        return True, "no db_revision reported (fresh database); the migrator will create the schema"
    return True, f"db_revision {observed} inside [{release.min_db_revision} .. {release.db_revision}]"


def needs_migration(release: ResolvedRelease, health: dict) -> bool:
    """rollout.py ``_needs_migration``."""
    if not release.db_revision or health is _UNREACHABLE:
        return True
    return health.get("db_revision") != release.db_revision


def disk_check(deps: Deps) -> dict:
    need = deps.instance.min_free_gb
    for path in (deps.config.disk_path, deps.instance.dir):
        try:
            usage = deps.disk_usage(str(path))
        except OSError:
            continue
        free_gb = usage.free / 1024 ** 3
        return _check("disk", free_gb >= need, f"{free_gb:.1f} GB free on {path} (need {need:g} GB)")
    return _check("disk", False, "could not measure free disk space")


def preflight(deps: Deps, release: ResolvedRelease, *, lock_ok: bool, health: dict) -> StepResult:
    """Every check runs (so a dry run shows them all); the step fails if any does.
    Nothing here changes the instance."""
    t = Timer()
    inst = deps.instance
    checks: list[dict] = []

    missing = [str(p) for p in (inst.lock_path, inst.env_path, *inst.compose_paths) if not p.exists()]
    checks.append(_check("files", not missing, "missing: " + ", ".join(missing) if missing else "lock, env and compose files present"))
    checks.append(_check("lock", lock_ok, "instance lock held" if lock_ok else "another run holds the instance lock"))

    refs = [release.backend_ref, release.frontend_ref]
    if deps.insecure:
        checks.append(_check("signature", True, "SKIPPED: --insecure-skip-verify (no signature was checked)", warn=True))
    else:
        pinned = all("@sha256:" in r for r in refs)
        checks.append(_check("digests", pinned, "both images pinned by digest" if pinned else "release is not digest-pinned"))
        for v in deps.verifier.verify_all(refs, inst.require_attestations):
            checks.append(_check(v.kind, v.ok, v.detail))

    if release.version_mismatch:
        checks.append(_check("stamp", False, f"backend and frontend images disagree: {release.version_mismatch}"))
    elif not release.stamp_complete:
        checks.append(_check("stamp", True, "backend image lacks a complete version/db_revision stamp", warn=True))
    else:
        checks.append(_check("stamp", True, f"version {release.version}, db_revision {release.db_revision}, "
                                            f"min_db_revision {release.min_db_revision}"))

    ok, detail = compatibility(release, health)
    checks.append(_check("schema", ok, detail))
    checks.append(disk_check(deps))
    if inst.backup.mode == "off":
        checks.append(_check("backup", True, "backups disabled for this instance (backup.mode: off)", warn=True))
    else:
        checks.append(_check("backup", True, f"backup.mode: {inst.backup.mode}"))

    failed = [c for c in checks if not c["ok"]]
    status = FAILED if failed else (WARNING if any(c["status"] == WARNING for c in checks) else OK)
    detail_lines = [f"{c['name']}: {c['detail']}" for c in (failed or checks)]
    return StepResult("preflight", status, "\n".join(detail_lines), {"checks": checks}, t.elapsed())


# --------------------------------------------------------------------------
# 2. backup
# --------------------------------------------------------------------------

def _last_json(text: str) -> Optional[dict]:
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return None


def backup_command(inst: InstanceConfig) -> list[str]:
    cmd = list(inst.backup.command)
    if inst.backup.mode == "verify":
        cmd.append("--verify")
    return cmd


def backup(deps: Deps, current: ImageSet) -> StepResult:
    """The instance's own encrypted off-site backup, run from the CURRENT image
    in a one-off container, then (mode verify) restored into a scratch database
    and compared table by table. An unverified backup stops the upgrade."""
    t = Timer()
    inst = deps.instance
    if inst.backup.mode == "off":
        return StepResult("backup", WARNING, "no backup taken (backup.mode: off)", {}, t.elapsed())
    result = deps.compose.one_off(inst.backend_service, backup_command(inst), current, inst.backup.timeout)
    report = _last_json(result.stdout) or {}
    data = {"report": redact(report), "exit_code": result.returncode}
    if result.returncode != 0 or report.get("status") != "ok":
        why = report.get("message") or result.tail(800) or f"exit {result.returncode}"
        return StepResult("backup", FAILED, f"backup failed; refusing to continue without a restore point: {why}",
                          data, t.elapsed())
    if inst.backup.mode == "verify" and not report.get("verified"):
        return StepResult("backup", FAILED, "backup was taken but not verified by a restore; refusing to continue",
                          data, t.elapsed())
    name = report.get("backup_name", "?")
    extra = f", restore verified ({report.get('tables', '?')} tables match)" if report.get("verified") else ""
    data["backup_name"] = name
    return StepResult("backup", OK, f"backed up as {name}{extra}", data, t.elapsed())


# --------------------------------------------------------------------------
# 3. pull
# --------------------------------------------------------------------------

def pull(deps: Deps, images: ImageSet) -> StepResult:
    t = Timer()
    result = deps.compose.pull(images, deps.instance.pull_timeout)
    if not result.ok:
        return StepResult("pull", FAILED, f"image pull failed: {result.tail()}", {}, t.elapsed())
    return StepResult("pull", OK, f"pulled {images.backend} and {images.frontend}", {}, t.elapsed())


# --------------------------------------------------------------------------
# 4. migrate
# --------------------------------------------------------------------------

def migrate(deps: Deps, images: ImageSet, release: ResolvedRelease, health: dict,
            allow_destructive: bool = False) -> StepResult:
    """``python -m app.db.migrate`` in a one-off container from the NEW image.

    The command replaces the image's entrypoint (which would run the same
    migrator and then serve), so the exit code is the migrator's own."""
    t = Timer()
    inst = deps.instance
    if not needs_migration(release, health):
        return StepResult("migrate", SKIPPED, f"already at {release.db_revision}", {}, t.elapsed())
    env = {ALLOW_DESTRUCTIVE_ENV: "1"} if allow_destructive else {}
    result = deps.compose.one_off(inst.backend_service, inst.migrate_command, images, inst.migrate_timeout, env=env)
    data = {"exit_code": result.returncode, "from": health.get("db_revision"), "to": release.db_revision}
    if result.returncode == GATE_BLOCKED:
        return StepResult(
            "migrate", NEEDS_APPROVAL,
            f"{deps.name} is at {health.get('db_revision')} and {release.tag} contains a migration that drops or "
            "rewrites data. Nothing was applied; the current version is still serving. Review the plan below, "
            f"then re-run with --allow-destructive.\n{result.tail(1500)}",
            data, t.elapsed())
    if result.returncode == GATE_NO_BACKUP:
        return StepResult(
            "migrate", FAILED,
            f"the migrator could not take its pre-migration dump, so nothing was applied. {result.tail(1200)}",
            data, t.elapsed())
    if result.returncode != 0:
        return StepResult("migrate", FAILED, f"migration failed (exit {result.returncode}): {result.tail()}",
                          data, t.elapsed())
    return StepResult("migrate", OK, f"schema at {release.db_revision or 'head'}", data, t.elapsed())


# --------------------------------------------------------------------------
# 5. recreate
# --------------------------------------------------------------------------

def recreate(deps: Deps, images: ImageSet, name: str = "recreate") -> StepResult:
    t = Timer()
    result = deps.compose.recreate(images)
    if not result.ok:
        return StepResult(name, FAILED, f"compose up failed: {result.tail()}", {}, t.elapsed())
    return StepResult(name, OK, f"{', '.join(deps.instance.services)} on {images.version}", {}, t.elapsed())


# --------------------------------------------------------------------------
# 6. health
# --------------------------------------------------------------------------

def _health_round(deps: Deps, images: ImageSet, expect_version: Optional[str],
                  expect_db: Optional[str]) -> list[dict]:
    checks: list[dict] = []
    try:
        quick = deps.probe.quick()
    except ProbeError as exc:
        return [_check("health/quick", False, str(exc))]
    got_v = quick.get("version")
    if expect_version:
        ok = norm_version(got_v) == norm_version(expect_version)
        checks.append(_check("version", ok, f"reports {got_v!r}" + ("" if ok else f", expected {expect_version!r}")))
    if expect_db:
        got = quick.get("db_revision")
        ok = got == expect_db
        checks.append(_check("db_revision", ok, f"{got!r}" + ("" if ok else f" != release {expect_db!r} (migrations did not land)")))
    for path in ("/", "/api/services/"):
        code = deps.probe.status(path)
        checks.append(_check(f"GET {path}", code == 200, f"HTTP {code}"))
    if all(c["ok"] for c in checks):
        inst = deps.instance
        if inst.worker_ping:
            r = deps.compose.exec(inst.worker_service, inst.worker_ping, images, timeout=30)
            checks.append(_check("worker", r.ok, "worker answered ping" if r.ok else f"no heartbeat: {r.tail(300)}"))
    if all(c["ok"] for c in checks) and inst.selfcheck:
        # Can the new image do its job (backups, models)? A failure fails the
        # health step, so the upgrade rolls back instead of committing it.
        for svc in (inst.backend_service, inst.worker_service):
            r = deps.compose.exec(svc, inst.selfcheck, images, timeout=60)
            checks.append(_check(f"selfcheck {svc}", r.ok,
                                 "image self-check passed" if r.ok else f"self-check failed: {r.tail(300)}"))
    return checks


def health(deps: Deps, images: ImageSet, *, expect_version: Optional[str], expect_db: Optional[str],
           name: str = "health", timeout: Optional[float] = None) -> StepResult:
    """Every check must pass in the same round; retried until the deadline
    (``health_timeout``, two minutes by default)."""
    t = Timer()
    inst = deps.instance
    deadline = deps.monotonic() + (inst.health_timeout if timeout is None else timeout)
    attempts = 0
    while True:
        attempts += 1
        checks = _health_round(deps, images, expect_version, expect_db)
        if all(c["ok"] for c in checks):
            return StepResult(name, OK, "; ".join(f"{c['name']} {c['detail']}" for c in checks),
                              {"checks": checks, "attempts": attempts}, t.elapsed())
        if deps.monotonic() >= deadline:
            bad = [c for c in checks if not c["ok"]]
            return StepResult(name, FAILED,
                              "unhealthy after {:.0f}s: ".format(t.elapsed()) + "; ".join(f"{c['name']}: {c['detail']}" for c in bad),
                              {"checks": checks, "attempts": attempts}, t.elapsed())
        deps.sleep(inst.health_interval)


# --------------------------------------------------------------------------
# dry-run descriptions
# --------------------------------------------------------------------------

def planned(name: str, detail: str, argv: Optional[list[str]] = None) -> StepResult:
    data = {"command": redact(argv)} if argv else {}
    return StepResult(name, PLANNED, detail, data)
