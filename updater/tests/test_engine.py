"""The upgrade state machine, end to end against fakes."""

from __future__ import annotations

import json

import pytest

from conftest import (
    BACKUP_OK, OLD, OLDER, UNREACHABLE, FakeProbe, FakeRunner, FakeSource, base_config, good_runner, healthy,
    is_compose, is_cosign, is_one_off, make_instance_dir, release,
)
from pinpoint_updater.config import parse_config
from pinpoint_updater.engine import Engine, InstanceNotReady
from pinpoint_updater.lockfile import read_lock
from pinpoint_updater.locking import InstanceLock
from pinpoint_updater.models import RunContext
from pinpoint_updater.reporting import JsonlReporter, MultiReporter, Reporter
from pinpoint_updater.request_source import CliRequestSource


class Recorder(Reporter):
    def __init__(self):
        self.steps, self.outcomes = [], []

    def step(self, run, result):
        self.steps.append(result)

    def finished(self, run, outcome):
        self.outcomes.append(outcome)


def engine(cfg, runner, probe, source=None, insecure=False, **overrides):
    rec = Recorder()
    e = Engine(config=cfg, name="town", source=source or FakeSource(), runner=runner,
               reporter=MultiReporter([rec, JsonlReporter(cfg.log_dir)]), probe=probe, insecure=insecure,
               deps_overrides={"sleep": lambda s: None, **overrides})
    return e, rec


def request(action="upgrade", tag="v1.8.0", yes=True, destructive=False):
    return CliRequestSource().build("town", action, tag, confirmed=yes, allow_destructive=destructive)


def run_ctx(action="upgrade", tag="v1.8.0"):
    return RunContext(instance="town", action=action, tag=tag)


def upgrade(e, **kw):
    req = request(**kw)
    return e.upgrade(run_ctx(tag=req.tag), req)


def statuses(outcome):
    return [(s.name, s.status) for s in outcome.steps]


# -- the happy path ------------------------------------------------------------

def test_good_upgrade_runs_every_step_in_order_and_commits_the_lock(cfg):
    runner = good_runner()
    probe = FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")])
    e, rec = engine(cfg, runner, probe)
    out = upgrade(e)

    assert out.outcome == "succeeded", out.summary
    assert statuses(out) == [("resolve", "ok"), ("preflight", "ok"), ("backup", "ok"), ("pull", "ok"),
                             ("migrate", "ok"), ("recreate", "ok"), ("health", "ok"), ("commit", "ok")]

    lock = read_lock(cfg.instances["town"].lock_path)
    assert lock.current.version == "v1.8.0" and lock.current.digest_pinned
    assert lock.current.backend.endswith("3" * 64) and lock.current.frontend.endswith("4" * 64)
    assert lock.previous == OLD

    # both digests verified, keyless policy on the argv
    cosign = [c for c in runner.calls if is_cosign(c)]
    assert len(cosign) == 2 and all("--certificate-oidc-issuer" in c and c[-1].count("@sha256:") == 1 for c in cosign)

    # backup ran from the CURRENT image, migrate from the NEW one
    backup = next(e_ for c, e_ in runner.compose_calls() if "app.cli.backup" in c)
    migrate = next(e_ for c, e_ in runner.compose_calls() if "app.db.migrate" in c)
    assert backup["BACKEND_IMAGE"] == OLD.backend
    assert migrate["BACKEND_IMAGE"].endswith("3" * 64)

    order = [next(w for w in ("app.cli.backup", "pull", "app.db.migrate", "up", "exec") if w in c)
             for c, _ in runner.compose_calls()]
    # exec: the worker ping, then the image self-check in backend and worker
    assert order == ["app.cli.backup", "pull", "app.db.migrate", "up", "exec", "exec", "exec"]

    # outcome + steps were reported and logged
    assert rec.outcomes[-1].outcome == "succeeded"
    log = (cfg.log_dir / "town.jsonl").read_text().splitlines()
    assert json.loads(log[-1])["type"] == "outcome" and json.loads(log[-1])["outcome"] == "succeeded"


def test_every_docker_call_is_scoped_to_the_instance(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")]))
    upgrade(e)
    inst = cfg.instances["town"]
    docker = [c for c in runner.calls if c[0] == "docker"]
    assert docker
    for c in docker:
        assert c[:4] == ["docker", "compose", "-p", "pinpoint-town"]
        assert c[c.index("--project-directory") + 1] == str(inst.dir)
        files = [c[i + 1] for i, a in enumerate(c) if a == "-f"]
        assert files == [str(p) for p in inst.compose_paths]
        envs = [c[i + 1] for i, a in enumerate(c) if a == "--env-file"]
        assert envs == [str(inst.env_path), str(inst.lock_path)]
    # recreate touches only the app services: no down, no volumes, no db
    up = next(c for c in docker if "up" in c)
    assert up[-3:] == ["backend", "worker", "frontend"] and "down" not in up and "--volumes" not in up


def test_noop_when_already_on_the_release(tmp_path):
    from pinpoint_updater.lockfile import ImageSet, LockState
    rel = release()
    make_instance_dir(tmp_path, LockState(current=ImageSet("v1.8.0", rel.backend_ref, rel.frontend_ref)))
    cfg = parse_config(base_config(tmp_path))
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.8.0", "bbb")]), source=FakeSource(rel))
    out = upgrade(e)
    assert out.outcome == "noop" and runner.calls == []


# -- stops before anything changes ------------------------------------------------

def _nothing_changed(runner, cfg):
    assert runner.compose_calls() == []
    assert read_lock(cfg.instances["town"].lock_path).current == OLD


def test_bad_signature_stops_before_anything_changes(cfg):
    runner = good_runner().on(lambda a: is_cosign(a) and "pinpoint-311-frontend" in a[-1], 1, "",
                              "Error: no matching signatures: none of the expected identities matched")
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    out = upgrade(e)
    assert out.outcome == "refused"
    assert statuses(out)[-1] == ("preflight", "failed")
    assert "no matching signatures" in out.steps[-1].detail
    _nothing_changed(runner, cfg)


def test_missing_attestation_stops_when_required(tmp_path):
    make_instance_dir(tmp_path)
    cfg = parse_config(base_config(tmp_path, require_attestations=True))
    runner = good_runner().on(lambda a: is_cosign(a) and a[1] == "verify-attestation", 1, "", "no attestations")
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    out = upgrade(e)
    assert out.outcome == "refused"
    assert any(c[1] == "verify-attestation" and "--type" in c for c in runner.calls if is_cosign(c))
    _nothing_changed(runner, cfg)


def test_schema_outside_window_stops(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "zzz_unrelated")]))
    out = upgrade(e)
    assert out.outcome == "refused"
    assert "outside compatibility window [aaa .. bbb]" in out.steps[-1].detail
    _nothing_changed(runner, cfg)


def test_unreachable_instance_stops(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([UNREACHABLE]))
    out = upgrade(e)
    assert out.outcome == "refused" and "unreachable" in out.steps[-1].detail
    _nothing_changed(runner, cfg)


def test_low_disk_stops(cfg):
    class Usage:
        free = 1 * 1024 ** 3

    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]), disk_usage=lambda p: Usage())
    out = upgrade(e)
    assert out.outcome == "refused" and "disk" in out.steps[-1].detail
    _nothing_changed(runner, cfg)


def test_failed_backup_stops_before_pull(cfg):
    runner = FakeRunner().on(is_one_off("app.cli.backup"), 1,
                             '{"status": "error", "message": "Backup not configured"}\n')
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    out = upgrade(e)
    assert out.outcome == "refused" and "Backup not configured" in out.steps[-1].detail
    assert [c for c in runner.calls if "pull" in c] == []
    assert read_lock(cfg.instances["town"].lock_path).current == OLD


def test_unverified_backup_stops(cfg):
    runner = FakeRunner().on(is_one_off("app.cli.backup"), 0, '{"status": "ok", "backup_name": "x", "verified": false}')
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    assert upgrade(e).outcome == "refused"


def test_unconfirmed_upgrade_changes_nothing(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    out = upgrade(e, yes=False)
    assert out.outcome == "not_confirmed"
    _nothing_changed(runner, cfg)


def test_refuses_an_instance_without_its_lock_or_env_file(cfg):
    cfg.instances["town"].env_path.unlink()
    e, _ = engine(cfg, good_runner(), FakeProbe([healthy("1.7.0", "aaa")]))
    with pytest.raises(InstanceNotReady):
        upgrade(e)
    with pytest.raises(InstanceNotReady):
        e.plan(run_ctx("plan"), "v1.8.0")


def test_a_second_run_is_locked_out(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    with InstanceLock(cfg.instances["town"].dir, "town"):
        out = upgrade(e)
    assert out.outcome == "locked"
    assert runner.calls == []


# -- migration gate -----------------------------------------------------------------

def test_gated_migration_is_needs_approval_with_no_recreate(cfg):
    runner = good_runner().on(is_one_off("app.db.migrate"), 2, "",
                              "[migrate] 1 destructive revision pending: drop_column service_requests.legacy")
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    out = upgrade(e)
    assert out.outcome == "needs_approval"
    assert statuses(out)[-1] == ("migrate", "needs_approval")
    assert "drop_column" in out.steps[-1].detail
    assert [c for c in runner.calls if "up" in c] == []
    assert read_lock(cfg.instances["town"].lock_path).current == OLD


def test_allow_destructive_passes_the_gate_variable(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")]))
    assert upgrade(e, destructive=True).outcome == "succeeded"
    migrate = next(c for c in runner.calls if "app.db.migrate" in c)
    assert "PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION=1" in migrate


def test_migrator_backup_failure_and_errors_are_failures_not_rollbacks(cfg):
    for rc in (3, 1):
        runner = good_runner().on(is_one_off("app.db.migrate"), rc, "", "boom")
        e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
        out = upgrade(e)
        assert out.outcome == "migration_failed"
        assert [c for c in runner.calls if "up" in c] == []
        assert "db_backup_20261018_120000.sql.gpg" in out.summary


def test_migration_skipped_when_already_at_the_release_schema(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "bbb"), healthy("1.8.0", "bbb")]))
    out = upgrade(e)
    assert out.outcome == "succeeded" and ("migrate", "skipped") in statuses(out)
    assert not any("app.db.migrate" in c for c in runner.calls)


# -- health and rollback ----------------------------------------------------------------

def test_failed_health_rolls_back_to_the_previous_digests(cfg):
    runner = good_runner()
    # pre: old ok; post-upgrade: still reports old version (new never came up); rollback: old ok
    probe = FakeProbe([healthy("1.7.0", "aaa"), healthy("1.7.0", "bbb"), healthy("1.7.0", "bbb")])
    e, rec = engine(cfg, runner, probe)
    out = upgrade(e)
    assert out.outcome == "rolled_back", out.summary
    assert ("health", "failed") in statuses(out) and ("rollback", "ok") in statuses(out)
    ups = [env for c, env in runner.compose_calls() if "up" in c]
    assert len(ups) == 2
    assert ups[0]["BACKEND_IMAGE"].endswith("3" * 64)
    assert ups[1]["BACKEND_IMAGE"] == OLD.backend and ups[1]["FRONTEND_IMAGE"] == OLD.frontend
    assert read_lock(cfg.instances["town"].lock_path).current == OLD
    assert "not restored" in out.summary and "db_backup_20261018_120000.sql.gpg" in out.summary


def test_failed_worker_heartbeat_rolls_back(cfg):
    runner = good_runner().on(is_compose("exec"), 1, "", "Error: No nodes replied within time constraint")
    probe = FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")])
    e, _ = engine(cfg, runner, probe)
    out = upgrade(e)
    # the rollback's own health also pings the (still broken) worker
    assert out.outcome == "rollback_failed"
    assert "worker" in next(s for s in out.steps if s.name == "health").detail


def test_failing_home_page_rolls_back(cfg):
    runner = good_runner()
    probe = FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb"), healthy("1.7.0", "bbb")],
                      statuses={"/": 502, "/api/services/": 200})
    e, _ = engine(cfg, runner, probe)
    out = upgrade(e)
    assert "GET /: HTTP 502" in next(s for s in out.steps if s.name == "health").detail


def test_health_is_retried_until_the_deadline(tmp_path):
    make_instance_dir(tmp_path)
    cfg = parse_config(base_config(tmp_path, health_timeout=120, health_interval=5))
    clock = {"t": 0.0}
    probe = FakeProbe([healthy("1.7.0", "aaa"), UNREACHABLE, UNREACHABLE, healthy("1.8.0", "bbb")])
    e, _ = engine(cfg, good_runner(), probe, monotonic=lambda: clock["t"],
                  sleep=lambda s: clock.__setitem__("t", clock["t"] + s))
    out = upgrade(e)
    assert out.outcome == "succeeded"
    assert next(s for s in out.steps if s.name == "health").data["attempts"] == 3


def test_failed_recreate_rolls_back(cfg):
    calls = {"n": 0}

    def up(args, env):
        calls["n"] += 1
        return (1, "", "Error response from daemon: pull access denied") if calls["n"] == 1 else (0, "", "")

    runner = good_runner()
    runner.rules.insert(0, (is_compose("up"), up))
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa"), healthy("1.7.0", "aaa")]))
    out = upgrade(e)
    assert out.outcome == "rolled_back" and ("recreate", "failed") in statuses(out)


# -- operator rollback ------------------------------------------------------------------

def test_operator_rollback_swaps_the_lock(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa"), healthy("1.6.0", "aaa")]))
    req = request("rollback", tag=None)
    out = e.rollback(run_ctx("rollback", None), req)
    assert out.outcome == "succeeded", out.summary
    lock = read_lock(cfg.instances["town"].lock_path)
    assert lock.current == OLDER and lock.previous == OLD
    up = next(env for c, env in runner.compose_calls() if "up" in c)
    assert up["BACKEND_IMAGE"] == OLDER.backend


def test_operator_rollback_verifies_signatures_first(cfg):
    runner = good_runner().on(is_cosign, 1, "", "invalid signature")
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    out = e.rollback(run_ctx("rollback", None), request("rollback", tag=None))
    assert out.outcome == "refused"
    _nothing_changed(runner, cfg)


# -- plan ----------------------------------------------------------------------------

def test_plan_changes_nothing_and_lists_the_steps(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]))
    out = e.plan(run_ctx("plan"), "v1.8.0")
    assert out.outcome == "planned"
    assert [s.name for s in out.steps] == ["resolve", "preflight", "backup", "pull", "migrate", "recreate", "health", "commit"]
    assert runner.compose_calls() == []  # only cosign ran
    assert read_lock(cfg.instances["town"].lock_path).current == OLD
    mig = next(s for s in out.steps if s.name == "migrate")
    assert "app.db.migrate" in mig.data["command"] and "-p" in mig.data["command"]


def test_plan_shows_a_refusal(cfg):
    e, _ = engine(cfg, good_runner(), FakeProbe([healthy("1.7.0", "zzz")]))
    assert e.plan(run_ctx("plan"), "v1.8.0").outcome == "refused"


def test_insecure_mode_skips_cosign_and_says_so(cfg):
    runner = good_runner()
    e, _ = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")]), insecure=True)
    out = upgrade(e)
    assert out.outcome == "succeeded"
    assert not any(is_cosign(c) for c in runner.calls)
    pre = next(s for s in out.steps if s.name == "preflight")
    assert pre.status == "warning" and "insecure-skip-verify" in pre.detail


def test_rollback_health_expects_the_version_the_app_reports_not_the_tag(tmp_path):
    """Found by the e2e run: tags and image version labels need not match
    (release-7 vs 1.7.0); the rollback health check must expect the label."""
    from pinpoint_updater.lockfile import ImageSet, LockState
    current = ImageSet("release-7", OLD.backend, OLD.frontend, app_version="1.7.0")
    make_instance_dir(tmp_path, LockState(current=current))
    cfg = parse_config(base_config(tmp_path))
    probe = FakeProbe([healthy("1.7.0", "aaa"), healthy("1.7.0", "bbb"), healthy("1.7.0", "bbb")])
    e, _ = engine(cfg, good_runner(), probe, source=FakeSource(release(tag="release-8", version="1.8.0", frontend_version="1.8.0")))
    out = upgrade(e, tag="release-8")
    assert out.outcome == "rolled_back", out.summary


def test_committed_lock_records_the_app_version(cfg):
    e, _ = engine(cfg, good_runner(), FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")]))
    assert upgrade(e).outcome == "succeeded"
    lock = read_lock(cfg.instances["town"].lock_path)
    assert lock.current.app_version == "1.8.0" and lock.current.version == "v1.8.0"
    assert "PINPOINT_APP_VERSION=1.8.0" in cfg.instances["town"].lock_path.read_text()


def test_failed_image_selfcheck_rolls_back(cfg):
    """1.9.0-rc1 shipped without gpg: the new image ran, answered health, and
    could not take a backup. The self-check in the health step catches that and
    the upgrade rolls back instead of committing release.lock."""
    runner = good_runner()
    calls = {"n": 0}

    def first_selfcheck(args):
        # Fail only the first self-check round (the new image); the rollback's
        # own health (old image) passes.
        if is_compose("exec")(args) and "app.cli.selfcheck" in args:
            calls["n"] += 1
            return calls["n"] <= 2   # backend + worker of the new image
        return False
    runner.on(first_selfcheck, 1, '{"ok": false, "problems": ["gpg is not installed"]}', "")
    probe = FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb"), healthy("1.7.0", "bbb")])
    e, _ = engine(cfg, runner, probe)
    out = upgrade(e)
    assert out.outcome == "rolled_back", out.summary
    detail = next(s for s in out.steps if s.name == "health").detail
    assert "selfcheck backend" in detail and "gpg is not installed" in detail
    assert read_lock(cfg.instances["town"].lock_path).current == OLD


def test_selfcheck_runs_in_backend_and_worker_after_upgrade(cfg):
    runner = good_runner()
    probe = FakeProbe([healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")])
    e, _ = engine(cfg, runner, probe)
    out = upgrade(e)
    assert out.outcome == "succeeded", out.summary
    execs = [c for c in runner.calls if c[:2] == ["docker", "compose"] and "app.cli.selfcheck" in c]
    services = {c[c.index("-T") + 1] for c in execs}
    assert services == {"backend", "worker"}


# -- adversarial review 2026-10-19 ----------------------------------------------------

def _console_request(tag):
    from pinpoint_updater.request_source import UpgradeRequest
    return UpgradeRequest(instance="town", action="upgrade", tag=tag, requested_by="alice", source="http",
                          approvals=["bob"], policy="two_person")


def test_a_console_request_cannot_downgrade(cfg):
    """A compromised backend (or one misused admin) must not move the town
    back onto an older signed release with a known flaw: the console's way
    back is rollback, to the previous release only."""
    from pinpoint_updater.request_source import TwoPersonApproval
    runner = good_runner()
    e, rec = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]),
                    source=FakeSource(release("v1.6.0", db="aaa", min_db="aaa")))
    e.approval = TwoPersonApproval()
    out = e.upgrade(run_ctx(tag="v1.6.0"), _console_request("v1.6.0"))
    assert out.outcome == "refused" and "older than" in out.steps[-1].detail
    assert not runner.calls  # no cosign, no backup, no compose
    assert read_lock(cfg.instance("town").lock_path).current.version == "v1.7.0"


def test_an_operator_on_the_host_may_still_downgrade(cfg):
    runner = good_runner()
    e, rec = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa"), healthy("1.6.0", "aaa")]),
                    source=FakeSource(release("v1.6.0", db="aaa", min_db="aaa")))
    out = e.upgrade(run_ctx(tag="v1.6.0"), request(tag="v1.6.0"))
    assert out.outcome == "succeeded", statuses(out)


def test_a_version_the_lock_cannot_hold_is_refused_before_anything_changes(cfg):
    """Found at the commit, it would leave the new release serving with the
    old lock (and an exception instead of a report)."""
    runner = good_runner()
    e, rec = engine(cfg, runner, FakeProbe([healthy("1.7.0", "aaa")]),
                    source=FakeSource(release(version="1.8.0\nBACKEND_IMAGE=evil")))
    out = upgrade(e)
    assert out.outcome == "refused" and "unsafe value" in out.steps[-1].detail
    assert not runner.subcommand_calls("up") and not runner.subcommand_calls("run")
