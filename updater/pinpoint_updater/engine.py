"""Runs the steps in order for one instance, under its lock.

The control flow mirrors orchestrator/rollout.py ``_upgrade_step`` and
``_run_phase`` for a single town: a gated migration is *needs_approval*, not a
failure, and is never rolled back (nothing past migrate ran, the old
containers are still serving); any failure after recreate restores the
previous digests. The database is never restored automatically: an additive
migration leaves a schema the old version still serves (that is what
``min_db_revision`` asserts), and a restore is offered to a human instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from pinpoint_updater import steps
from pinpoint_updater.compose import Compose
from pinpoint_updater.config import InstanceConfig, UpdaterConfig, validate_tag
from pinpoint_updater.cosign import CosignVerifier
from pinpoint_updater.health import AppProbe, ProbeError
from pinpoint_updater.lockfile import ImageSet, LockFileError, LockState, read_lock, write_lock
from pinpoint_updater.locking import InstanceLock, InstanceLocked
from pinpoint_updater.models import (
    ERROR, FAILED, GATED, MIGRATION_FAILED, NEEDS_APPROVAL, NOOP, OK, PLANNED_OUTCOME, REFUSED,
    ROLLBACK_FAILED, ROLLED_BACK, SUCCEEDED, VERIFIED, WARNING, RunContext, RunOutcome, StepResult, Timer,
)
from pinpoint_updater.redact import redact
from pinpoint_updater.reporting import Reporter
from pinpoint_updater.request_source import ApprovalPolicy, OperatorApproval, UpgradeRequest
from pinpoint_updater.runner import Runner
from pinpoint_updater.sources import ReleaseSource, ResolvedRelease, SourceError

# confirm(preflight_steps) -> bool. Called after preflight, before anything changes.
Confirm = Callable[[list[StepResult]], bool]


class InstanceNotReady(RuntimeError):
    """The instance's lock file or env file is missing: refuse to act."""


@dataclass
class Engine:
    config: UpdaterConfig
    name: str
    source: ReleaseSource
    runner: Runner
    reporter: Reporter
    probe: Optional[AppProbe] = None
    insecure: bool = False
    approval: ApprovalPolicy = field(default_factory=OperatorApproval)
    deps_overrides: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.instance: InstanceConfig = self.config.instance(self.name)
        self.compose = Compose(self.instance, self.runner)
        self.verifier = CosignVerifier(self.config.trust, self.runner)
        self.probe = self.probe or AppProbe(self.instance.app_url)
        self.deps = steps.Deps(
            config=self.config, name=self.name, instance=self.instance, source=self.source,
            verifier=self.verifier, compose=self.compose, probe=self.probe, insecure=self.insecure,
            **self.deps_overrides,
        )
        self.lock = InstanceLock(self.instance.dir, self.name)

    # -- helpers -------------------------------------------------------------

    def require_files(self) -> None:
        inst = self.instance
        missing = [str(p) for p in (inst.lock_path, inst.env_path) if not p.is_file()]
        if not inst.dir.is_dir():
            missing.insert(0, str(inst.dir))
        if missing:
            raise InstanceNotReady(
                f"refusing to act on {self.name}: missing {', '.join(missing)}. "
                "An instance is managed only once its release.lock and env file exist."
            )

    def _emit(self, run: RunContext, out: list[StepResult], result: StepResult) -> StepResult:
        result.detail = redact(result.detail)
        out.append(result)
        self.reporter.step(run, result)
        return result

    def _finish(self, run: RunContext, outcome: str, summary: str, out: list[StepResult], **data) -> RunOutcome:
        result = RunOutcome(outcome, redact(summary), out, redact(data))
        self.reporter.finished(run, result)
        return result

    def _resolve(self, run: RunContext, out: list[StepResult], tag: str) -> Optional[ResolvedRelease]:
        t = Timer()
        try:
            validate_tag(tag)
            release = self.source.resolve(tag)
        except (SourceError, ValueError) as exc:
            self._emit(run, out, StepResult("resolve", FAILED, f"cannot resolve {tag}: {exc}", {}, t.elapsed()))
            return None
        self._emit(run, out, StepResult(
            "resolve", OK, f"{tag} → backend {release.backend_digest[:19]}…, frontend {release.frontend_digest[:19]}…",
            {"release": release.as_dict()}, t.elapsed()))
        return release

    # -- verify ----------------------------------------------------------------

    def verify(self, run: RunContext, tag: str) -> RunOutcome:
        out: list[StepResult] = []
        release = self._resolve(run, out, tag)
        if not release:
            return self._finish(run, REFUSED, f"could not resolve {tag}", out)
        t = Timer()
        verdicts = self.verifier.verify_all([release.backend_ref, release.frontend_ref], self.instance.require_attestations)
        ok = all(v.ok for v in verdicts)
        self._emit(run, out, StepResult("verify", steps.OK if ok else steps.FAILED,
                                        "\n".join(v.detail for v in verdicts),
                                        {"verdicts": [v.as_dict() for v in verdicts]}, t.elapsed()))
        if not ok:
            return self._finish(run, REFUSED, f"{tag} failed signature verification", out, release=release.as_dict())
        return self._finish(run, VERIFIED, f"{tag} is signed by the trusted identity", out, release=release.as_dict())

    # -- plan (dry run) ----------------------------------------------------------

    def plan(self, run: RunContext, tag: str, allow_destructive: bool = False) -> RunOutcome:
        self.require_files()
        out: list[StepResult] = []
        state = read_lock(self.instance.lock_path)
        release = self._resolve(run, out, tag)
        if not release:
            return self._finish(run, REFUSED, f"could not resolve {tag}", out)
        new = steps.images_for(release)
        if new.same_images(state.current):
            return self._finish(run, NOOP, f"{self.name} already runs {tag}", out)
        health = steps.read_health(self.deps)
        pre = self._emit(run, out, steps.preflight(self.deps, release, lock_ok=self.lock.available(), health=health))
        inst = self.instance
        c = self.compose
        if inst.backup.mode == "off":
            self._emit(run, out, steps.planned("backup", "skipped (backup.mode: off)"))
        else:
            argv = c.argv("run", "--rm", "--no-deps", "-T", "--entrypoint", inst.backup.command[0],
                          inst.backend_service, *steps.backup_command(inst)[1:])
            self._emit(run, out, steps.planned("backup", f"{inst.backup.mode} backup from {state.current.version}", argv))
        self._emit(run, out, steps.planned("pull", f"{new.backend}, {new.frontend}",
                                           c.argv("pull", "--quiet", "--policy", "missing", *inst.services)))
        if steps.needs_migration(release, health):
            env = ["-e", f"{steps.ALLOW_DESTRUCTIVE_ENV}=1"] if allow_destructive else []
            self._emit(run, out, steps.planned(
                "migrate", f"{health.get('db_revision') if health else 'unknown'} → {release.db_revision or 'head'}"
                + (" (destructive migrations approved)" if allow_destructive else
                   " (a destructive migration would stop here as needs_approval)"),
                c.argv("run", "--rm", "--no-deps", "-T", *env, "--entrypoint", inst.migrate_command[0],
                       inst.backend_service, *inst.migrate_command[1:])))
        else:
            self._emit(run, out, steps.planned("migrate", f"skipped: already at {release.db_revision}"))
        self._emit(run, out, steps.planned("recreate", ", ".join(inst.services),
                                           c.argv("up", "-d", "--no-deps", "--no-build", *inst.services)))
        self._emit(run, out, steps.planned(
            "health", f"version {release.version}, db_revision {release.db_revision}, worker ping, "
                      f"GET / and /api/services/ for up to {inst.health_timeout}s"))
        self._emit(run, out, steps.planned("commit", f"rewrite {inst.lock_path} (previous: {state.current.version}); "
                                                     "on failure recreate from the previous digests"))
        if pre.status == FAILED:
            return self._finish(run, REFUSED, f"{tag} would be refused at preflight", out, release=release.as_dict())
        return self._finish(run, PLANNED_OUTCOME, f"{self.name} can move {state.current.version} → {tag}", out,
                            release=release.as_dict(), current=state.current.as_dict())

    # -- upgrade -------------------------------------------------------------------

    def upgrade(self, run: RunContext, request: UpgradeRequest, confirm: Optional[Confirm] = None) -> RunOutcome:
        self.require_files()
        try:
            self.lock.acquire()
        except InstanceLocked as exc:
            out: list[StepResult] = []
            self._emit(run, out, StepResult("preflight", FAILED, str(exc)))
            return self._finish(run, "locked", str(exc), out)
        try:
            return self._upgrade_locked(run, request, confirm)
        finally:
            self.lock.release()

    def _upgrade_locked(self, run: RunContext, request: UpgradeRequest, confirm: Optional[Confirm]) -> RunOutcome:
        out: list[StepResult] = []
        tag = request.tag or ""
        state = read_lock(self.instance.lock_path)
        current = state.current

        release = self._resolve(run, out, tag)
        if not release:
            return self._finish(run, REFUSED, f"could not resolve {tag}; nothing changed", out)
        new = steps.images_for(release)
        if new.same_images(current):
            return self._finish(run, NOOP, f"{self.name} already runs {tag}", out)

        # 1. preflight
        health = steps.read_health(self.deps)
        pre = self._emit(run, out, steps.preflight(self.deps, release, lock_ok=True, health=health))
        if pre.status == FAILED:
            return self._finish(run, REFUSED, f"preflight refused {tag}; nothing changed", out)

        if confirm is not None and confirm(out):
            if not request.approvals:
                request.approvals.append(request.requested_by)
        ok, why = self.approval.check(request)
        if not ok:
            self._emit(run, out, StepResult("approval", FAILED, why))
            return self._finish(run, "not_confirmed", f"{why}; nothing changed", out)

        # 2. backup (from the CURRENT image)
        b = self._emit(run, out, steps.backup(self.deps, current))
        if b.status == FAILED:
            return self._finish(run, REFUSED, "backup failed; nothing changed", out)
        backup_name = b.data.get("backup_name")
        restore_note = (f" A restore from backup {backup_name} is available if needed; it is never automatic."
                        if backup_name else "")

        # 3. pull
        if self._emit(run, out, steps.pull(self.deps, new)).status == FAILED:
            return self._finish(run, REFUSED, "pull failed; nothing changed", out, backup=backup_name)

        # 4. migrate (from the NEW image)
        m = self._emit(run, out, steps.migrate(self.deps, new, release, health, request.allow_destructive))
        if m.status == NEEDS_APPROVAL:
            return self._finish(run, GATED, f"{tag} needs approval for a destructive migration; "
                                            f"{current.version} is still serving", out, backup=backup_name)
        if m.status == FAILED:
            return self._finish(run, MIGRATION_FAILED,
                                f"migration to {tag} failed; containers were not recreated and {current.version} is "
                                f"still serving. Check the schema.{restore_note}", out, backup=backup_name)

        # 5. recreate + 6. health
        r = self._emit(run, out, steps.recreate(self.deps, new))
        h = None
        if r.status == OK:
            h = self._emit(run, out, steps.health(self.deps, new, expect_version=release.version,
                                                  expect_db=release.db_revision))
        if r.status != OK or (h is not None and h.status == FAILED):
            return self._roll_back(run, out, current, failed_to=tag, restore_note=restore_note, backup=backup_name)

        # 7. commit
        t = Timer()
        try:
            write_lock(self.instance.lock_path, LockState(current=new, previous=current, extra=state.extra),
                       header=f"{tag} via run {run.run_id}")
        except OSError as exc:
            self._emit(run, out, StepResult("commit", FAILED, f"could not rewrite {self.instance.lock_path}: {exc}. "
                                            f"The containers run {tag} but the lock still names {current.version}; "
                                            "fix the file before anything else recreates the stack.", {}, t.elapsed()))
            return self._finish(run, ERROR, f"{tag} is running but release.lock was not updated", out, backup=backup_name)
        self._emit(run, out, StepResult("commit", OK, f"{self.instance.lock_path} → {tag} (previous {current.version})",
                                        {"current": new.as_dict(), "previous": current.as_dict()}, t.elapsed()))
        return self._finish(run, SUCCEEDED, f"{self.name} upgraded {current.version} → {tag}", out,
                            backup=backup_name, current=new.as_dict(), previous=current.as_dict())

    def _roll_back(self, run, out, previous: ImageSet, *, failed_to: str, restore_note: str, backup) -> RunOutcome:
        r = self._emit(run, out, steps.recreate(self.deps, previous, name="rollback"))
        h = None
        if r.status == OK:
            h = self._emit(run, out, steps.health(self.deps, previous, expect_version=previous.expected_version,
                                                  expect_db=None, name="rollback-health"))
        if r.status == OK and h is not None and h.status == OK:
            return self._finish(run, ROLLED_BACK,
                                f"{failed_to} was unhealthy; rolled back to {previous.version} (previous digests). "
                                f"The database was not restored.{restore_note}", out, backup=backup)
        return self._finish(run, ROLLBACK_FAILED,
                            f"{failed_to} was unhealthy AND the rollback to {previous.version} did not come back "
                            f"healthy. Manual intervention needed now.{restore_note}", out, backup=backup)

    # -- rollback (operator) --------------------------------------------------------

    def rollback(self, run: RunContext, request: UpgradeRequest, confirm: Optional[Confirm] = None) -> RunOutcome:
        self.require_files()
        try:
            self.lock.acquire()
        except InstanceLocked as exc:
            out: list[StepResult] = []
            self._emit(run, out, StepResult("preflight", FAILED, str(exc)))
            return self._finish(run, "locked", str(exc), out)
        try:
            return self._rollback_locked(run, request, confirm)
        finally:
            self.lock.release()

    def _rollback_locked(self, run, request, confirm) -> RunOutcome:
        out: list[StepResult] = []
        state = read_lock(self.instance.lock_path)
        if not state.previous:
            self._emit(run, out, StepResult("preflight", FAILED, "release.lock records no previous release"))
            return self._finish(run, REFUSED, "nothing to roll back to", out)
        target, current = state.previous, state.current
        run.tag = target.version

        t = Timer()
        checks = []
        refs = [target.backend, target.frontend]
        if self.insecure:
            checks.append(steps._check("signature", True, "SKIPPED: --insecure-skip-verify", warn=True))
        else:
            for v in self.verifier.verify_all(refs, self.instance.require_attestations):
                checks.append(steps._check(v.kind, v.ok, v.detail))
        health = steps.read_health(self.deps)
        observed = health.get("db_revision") if health else None
        expect_version = target.expected_version
        try:
            stamp = self.source.stamp_for_ref(target.backend)
            if not target.app_version and stamp.get("version"):
                expect_version = stamp["version"]
            window = {stamp.get("min_db_revision"), stamp.get("db_revision")} - {None}
            if window and observed and observed not in window:
                checks.append(steps._check(
                    "schema", True,
                    f"db_revision {observed} is newer than {target.version}'s window {sorted(window)}; this is safe "
                    "only if the migrations since were additive (expand). The database is NOT restored.", warn=True))
            else:
                checks.append(steps._check("schema", True, f"db_revision {observed!r}; {target.version} window {sorted(window) or 'undeclared'}"))
        except SourceError as exc:
            checks.append(steps._check("schema", True, f"could not read {target.version}'s stamp: {exc}", warn=True))
        failed = [c for c in checks if not c["ok"]]
        status = FAILED if failed else (WARNING if any(c["status"] == WARNING for c in checks) else OK)
        self._emit(run, out, StepResult("preflight", status, "\n".join(f"{c['name']}: {c['detail']}" for c in checks),
                                        {"checks": checks}, t.elapsed()))
        if failed:
            return self._finish(run, REFUSED, f"{target.version} failed verification; nothing changed", out)

        if confirm is not None and confirm(out) and not request.approvals:
            request.approvals.append(request.requested_by)
        ok, why = self.approval.check(request)
        if not ok:
            self._emit(run, out, StepResult("approval", FAILED, why))
            return self._finish(run, "not_confirmed", f"{why}; nothing changed", out)

        if self._emit(run, out, steps.pull(self.deps, target)).status == FAILED:
            return self._finish(run, REFUSED, "pull failed; nothing changed", out)
        r = self._emit(run, out, steps.recreate(self.deps, target, name="recreate"))
        h = None
        if r.status == OK:
            h = self._emit(run, out, steps.health(self.deps, target, expect_version=expect_version,
                                                  expect_db=None))
        if r.status != OK or h.status == FAILED:
            back = self._roll_back(run, out, current, failed_to=target.version, restore_note="", backup=None)
            return back
        t = Timer()
        write_lock(self.instance.lock_path, LockState(current=target, previous=current, extra=state.extra),
                   header=f"rollback to {target.version} via run {run.run_id}")
        self._emit(run, out, StepResult("commit", OK, f"{self.instance.lock_path} → {target.version} "
                                                      f"(previous {current.version})", {}, t.elapsed()))
        return self._finish(run, SUCCEEDED, f"{self.name} rolled back {current.version} → {target.version}; "
                                            "the database was not restored", out)

    # -- restart (console) ------------------------------------------------------------

    def restart(self, run: RunContext, request: UpgradeRequest, confirm: Optional[Confirm] = None) -> RunOutcome:
        """``docker compose restart`` of backend, worker and frontend for THIS
        instance's project, then the usual health check against the version
        release.lock names. Images, schema and the lock are unchanged."""
        self.require_files()
        try:
            self.lock.acquire()
        except InstanceLocked as exc:
            out: list[StepResult] = []
            self._emit(run, out, StepResult("preflight", FAILED, str(exc)))
            return self._finish(run, "locked", str(exc), out)
        try:
            out = []
            state = read_lock(self.instance.lock_path)
            current = state.current
            run.tag = current.version
            if confirm is not None and confirm(out) and not request.approvals:
                request.approvals.append(request.requested_by)
            ok, why = self.approval.check(request)
            if not ok:
                self._emit(run, out, StepResult("approval", FAILED, why))
                return self._finish(run, "not_confirmed", f"{why}; nothing changed", out)
            t = Timer()
            result = self.compose.restart(current)
            services = ", ".join(self.instance.services)
            if not result.ok:
                self._emit(run, out, StepResult("restart", FAILED, f"compose restart failed: {result.tail()}",
                                                {}, t.elapsed()))
                return self._finish(run, ERROR, f"restart of {services} failed", out)
            self._emit(run, out, StepResult("restart", OK, f"{services} restarted (project {self.instance.project})",
                                            {}, t.elapsed()))
            h = self._emit(run, out, steps.health(self.deps, current, expect_version=current.expected_version,
                                                  expect_db=None))
            if h.status == FAILED:
                return self._finish(run, ERROR, f"{self.name} restarted but is not healthy: {h.detail}", out)
            return self._finish(run, SUCCEEDED, f"{self.name} restarted {services} on {current.version}", out)
        finally:
            self.lock.release()

    # -- status -----------------------------------------------------------------------

    def status(self) -> dict:
        inst = self.instance
        info: dict = {"instance": self.name, "project": inst.project, "dir": str(inst.dir)}
        try:
            self.require_files()
            state = read_lock(inst.lock_path)
            info["lock"] = {"current": state.current.as_dict(),
                            "previous": state.previous.as_dict() if state.previous else None}
        except (InstanceNotReady, LockFileError) as exc:
            info["error"] = str(exc)
            return info
        try:
            info["health"] = self.probe.quick()
        except ProbeError as exc:
            info["health"] = {"error": str(exc)}
        ps = self.compose.ps(state.current)
        containers = []
        if ps.ok:
            for line in ps.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue
                for c in parsed if isinstance(parsed, list) else [parsed]:
                    containers.append({k: c.get(k) for k in ("Service", "Image", "State", "Health", "Status")})
        info["containers"] = containers
        expected = {inst.backend_service: state.current.backend, inst.worker_service: state.current.backend,
                    inst.frontend_service: state.current.frontend}
        info["drift"] = [
            f"{c['Service']} runs {c['Image']}, lock says {expected[c['Service']]}"
            for c in containers if c.get("Service") in expected and c.get("Image") != expected[c["Service"]]
        ]
        info["locked_by_other_run"] = not self.lock.available()
        info["last_outcome"] = self._last_outcome()
        return redact(info)

    def _last_outcome(self) -> Optional[dict]:
        path = Path(self.config.log_dir) / f"{self.name}.jsonl"
        try:
            lines = path.read_text().splitlines()[-200:]
        except OSError:
            return None
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") == "outcome":
                return {k: rec.get(k) for k in ("run_id", "action", "tag", "outcome", "summary", "finished_at")}
        return None
