"""``pinpoint-updater`` command line. Exit codes: see exitcodes.py / README."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from pinpoint_updater import __version__, exitcodes, steps
from pinpoint_updater.config import DEFAULT_CONFIG_PATH, ConfigError, UpdaterConfig, load_config
from pinpoint_updater.engine import Engine, InstanceNotReady
from pinpoint_updater.health import AppProbe, ProbeError
from pinpoint_updater.lockfile import LockFileError, read_lock
from pinpoint_updater.models import RunContext, StepResult
from pinpoint_updater.redact import redact
from pinpoint_updater.reporting import ConsoleReporter, JsonlReporter, MultiReporter
from pinpoint_updater import release_report
from pinpoint_updater.request_source import (CliRequestSource, HttpRequestSource, LostTrackMarker, RequestSource,
                                             RequestSourceError)
from pinpoint_updater.runner import Runner
from pinpoint_updater.sources import ReleaseSource, SourceError, make_source

ALLOW_INSECURE_ENV = "PINPOINT_UPDATER_ALLOW_INSECURE"

INSECURE_BANNER = """\
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!  --insecure-skip-verify: IMAGE SIGNATURES WILL NOT BE CHECKED.          !!
!!  Anything at these references will be deployed, signed or not.          !!
!!  For throwaway test stacks only. This run is recorded as insecure.      !!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"""


class Hooks:
    """Injection points for tests (and nothing else)."""

    source_factory: Optional[Callable[[UpdaterConfig], ReleaseSource]] = None
    runner_factory: Optional[Callable[[], Runner]] = None
    probe_factory: Optional[Callable[[str], AppProbe]] = None
    deps_overrides: dict = {}
    request_source: Optional[RequestSource] = None
    # Build the console source for `poll` (tests hand in a fake transport).
    http_source_factory: Optional[Callable[[UpdaterConfig], RequestSource]] = None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pinpoint-updater",
        description="Verified, backed-up, health-checked upgrades of self-hosted Pinpoint 311 instances.",
        epilog="Exit codes: 0 ok, 1 error, 2 usage/config, 3 refused (nothing changed), 4 needs approval, "
               "5 rolled back, 6 rollback failed, 7 locked, 8 not confirmed, 9 migration failed.",
    )
    p.add_argument("--config", "-c", type=Path, default=Path(os.environ.get("PINPOINT_UPDATER_CONFIG", DEFAULT_CONFIG_PATH)))
    p.add_argument("--json", action="store_true", help="machine-readable output on stdout")
    p.add_argument("--log-dir", type=Path, help="override log_dir from the config")
    p.add_argument("--insecure-skip-verify", action="store_true",
                   help=f"skip cosign verification (test stacks only; requires {ALLOW_INSECURE_ENV}=1)")
    p.add_argument("--version", action="version", version=f"pinpoint-updater {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("releases", help="list releases from the configured source")
    r.add_argument("--instance", help="annotate with this instance's current version and schema compatibility")
    r.add_argument("--limit", type=int, default=10)
    r.add_argument("--resolve", type=int, default=5, help="with --instance: how many releases to resolve for compatibility")

    v = sub.add_parser("verify", help="resolve a release and verify both image signatures")
    v.add_argument("instance")
    v.add_argument("tag")

    pl = sub.add_parser("plan", help="dry run: every check and the steps an upgrade would take; changes nothing")
    pl.add_argument("instance")
    pl.add_argument("tag")
    pl.add_argument("--allow-destructive", action="store_true")

    u = sub.add_parser("upgrade", help="upgrade an instance to a release")
    u.add_argument("instance")
    u.add_argument("tag")
    u.add_argument("--yes", "-y", action="store_true", help="do not prompt; this is the operator's approval")
    u.add_argument("--allow-destructive", action="store_true",
                   help="approve a destructive migration that stopped a previous run with needs_approval")
    u.add_argument("--reason", help="recorded in the log")

    rb = sub.add_parser("rollback", help="return an instance to the previous release in its release.lock")
    rb.add_argument("instance")
    rb.add_argument("--yes", "-y", action="store_true")
    rb.add_argument("--reason")

    s = sub.add_parser("status", help="what an instance runs and whether it is healthy")
    s.add_argument("instance")

    sub.add_parser("poll", help="process pending requests from the request source (systemd timer entry point)")
    return p


def _out(args, payload: dict, human: Callable[[], None]) -> None:
    if args.json:
        print(json.dumps(redact(payload), indent=2, default=str))
    else:
        human()


def _confirm_factory(args) -> Optional[Callable[[list[StepResult]], bool]]:
    if getattr(args, "yes", False):
        return None
    if args.json or not sys.stdin.isatty():
        return lambda _steps: False

    def ask(_steps: list[StepResult]) -> bool:
        try:
            answer = input("Proceed? Type 'yes' to continue: ")
        except EOFError:
            return False
        return answer.strip().lower() == "yes"

    return ask


def main(argv: Optional[list[str]] = None, hooks: Optional[Hooks] = None) -> int:
    hooks = hooks or Hooks()
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exitcodes.USAGE if exc.code not in (0, None) else exitcodes.OK

    if args.insecure_skip_verify:
        if os.environ.get(ALLOW_INSECURE_ENV) != "1":
            print(f"pinpoint-updater: --insecure-skip-verify is refused unless {ALLOW_INSECURE_ENV}=1 is set",
                  file=sys.stderr)
            return exitcodes.USAGE
        print(INSECURE_BANNER, file=sys.stderr)

    try:
        cfg = load_config(args.config)
        if args.log_dir:
            cfg = cfg.model_copy(update={"log_dir": args.log_dir})
    except ConfigError as exc:
        print(f"pinpoint-updater: {exc}", file=sys.stderr)
        return exitcodes.USAGE

    try:
        source = hooks.source_factory(cfg) if hooks.source_factory else make_source(cfg.release_source)
    except ConfigError as exc:
        print(f"pinpoint-updater: {exc}", file=sys.stderr)
        return exitcodes.USAGE
    try:
        return _dispatch(args, cfg, source, hooks)
    except (ConfigError, InstanceNotReady, LockFileError) as exc:
        print(f"pinpoint-updater: {redact(str(exc))}", file=sys.stderr)
        return exitcodes.USAGE
    except Exception as exc:  # last resort: never print a raw traceback with secrets in it
        print(f"pinpoint-updater: unexpected error: {exc.__class__.__name__}: {redact(str(exc))}", file=sys.stderr)
        return exitcodes.ERROR
    finally:
        try:
            source.close()
        except Exception:
            pass


def _engine(args, cfg, source, hooks, name) -> Engine:
    cfg.instance(name)  # raises ConfigError for an unknown name
    runner = hooks.runner_factory() if hooks.runner_factory else Runner()
    probe = hooks.probe_factory(cfg.instances[name].app_url) if hooks.probe_factory else None
    reporters = [JsonlReporter(cfg.log_dir), ConsoleReporter(quiet=args.json)]
    return Engine(config=cfg, name=name, source=source, runner=runner,
                  reporter=MultiReporter(reporters), probe=probe, insecure=args.insecure_skip_verify,
                  deps_overrides=dict(hooks.deps_overrides))


def _run_and_print(args, engine: Engine, run: RunContext, fn) -> int:
    if not args.json:
        what = f"{run.action} {run.instance}" + (f" → {run.tag}" if run.tag else "")
        print(f"pinpoint-updater: {what} (run {run.run_id})")
    outcome = fn()
    if args.json:
        print(json.dumps(redact(outcome.as_dict(run)), indent=2, default=str))
    return exitcodes.for_outcome(outcome.outcome)


def _dispatch(args, cfg: UpdaterConfig, source: ReleaseSource, hooks: Hooks) -> int:
    requests = hooks.request_source or CliRequestSource()
    cmd = args.command

    if cmd == "releases":
        return _releases(args, cfg, source, hooks)

    if cmd == "poll":
        if hooks.request_source is None and any(i.token_file for i in cfg.instances.values()):
            # An instance with a console token: claim and run what admins filed there.
            requests = (hooks.http_source_factory or HttpRequestSource)(cfg)
        try:
            return _poll(args, cfg, source, hooks, requests)
        finally:
            requests.close()

    engine = _engine(args, cfg, source, hooks, args.instance)

    if cmd == "status":
        info = engine.status()

        def human():
            lock = info.get("lock") or {}
            cur = (lock.get("current") or {})
            prev = (lock.get("previous") or {})
            print(f"{info['instance']} (project {info['project']}, {info['dir']})")
            if info.get("error"):
                print(f"  error: {info['error']}")
                return
            print(f"  release.lock: {cur.get('version')}  backend {cur.get('backend')}")
            print(f"                          frontend {cur.get('frontend')}")
            print(f"  previous:     {prev.get('version') or '-'}")
            h = info.get("health") or {}
            print(f"  health:       " + (h.get("error") or f"version {h.get('version')!r}, db_revision {h.get('db_revision')!r}"))
            for c in info.get("containers", []):
                print(f"  {c.get('Service', '?'):<10} {c.get('State')}/{c.get('Health') or '-'}  {c.get('Image')}")
            for d in info.get("drift", []):
                print(f"  DRIFT: {d}")
            if info.get("locked_by_other_run"):
                print("  an upgrade is running right now")
            if info.get("last_outcome"):
                lo = info["last_outcome"]
                print(f"  last run:     {lo.get('action')} {lo.get('tag')} → {lo.get('outcome')} at {lo.get('finished_at')}")

        _out(args, info, human)
        if info.get("error"):
            return exitcodes.USAGE
        return exitcodes.OK

    if cmd == "verify":
        run = RunContext(instance=args.instance, action="verify", tag=args.tag, insecure=args.insecure_skip_verify)
        return _run_and_print(args, engine, run, lambda: engine.verify(run, args.tag))

    if cmd == "plan":
        run = RunContext(instance=args.instance, action="plan", tag=args.tag, insecure=args.insecure_skip_verify)
        return _run_and_print(args, engine, run, lambda: engine.plan(run, args.tag, args.allow_destructive))

    if cmd in ("upgrade", "rollback"):
        if isinstance(requests, CliRequestSource):
            request = requests.build(args.instance, cmd, getattr(args, "tag", None), confirmed=args.yes,
                                     allow_destructive=getattr(args, "allow_destructive", False), reason=args.reason)
        else:  # pragma: no cover - Phase 3 sources do not take CLI requests
            raise ConfigError("upgrade/rollback from the CLI need the CLI request source")
        engine.approval = requests.approval_policy(args.instance)
        extra = requests.reporter(request)
        engine.reporter = MultiReporter([engine.reporter, extra])
        run = RunContext(instance=args.instance, action=cmd, tag=request.tag, requested_by=request.requested_by,
                         request_id=request.id, insecure=args.insecure_skip_verify)
        confirm = _confirm_factory(args)
        if cmd == "upgrade":
            return _run_and_print(args, engine, run, lambda: engine.upgrade(run, request, confirm))
        return _run_and_print(args, engine, run, lambda: engine.rollback(run, request, confirm))

    raise ConfigError(f"unknown command {cmd}")  # pragma: no cover


def _releases(args, cfg, source, hooks) -> int:
    try:
        releases = source.list_releases(args.limit)
    except SourceError as exc:
        print(f"pinpoint-updater: {redact(str(exc))}", file=sys.stderr)
        return exitcodes.ERROR
    rows = [r.as_dict() for r in releases]
    context: dict = {}
    if args.instance:
        inst = cfg.instance(args.instance)
        try:
            context["current"] = read_lock(inst.lock_path).current.as_dict()
        except LockFileError as exc:
            context["current_error"] = str(exc)
        probe = hooks.probe_factory(inst.app_url) if hooks.probe_factory else AppProbe(inst.app_url)
        try:
            health = probe.quick()
        except ProbeError as exc:
            health = {}
            context["health_error"] = str(exc)
        context["db_revision"] = health.get("db_revision")
        current_v = steps.norm_version((context.get("current") or {}).get("version"))
        for i, row in enumerate(rows):
            row["current"] = steps.norm_version(row["tag"]) == current_v
            if i >= args.resolve:
                continue
            try:
                rel = source.resolve(row["tag"])
            except (SourceError, ValueError) as exc:
                row["resolve_error"] = str(exc)
                continue
            ok, detail = steps.compatibility(rel, health or steps._UNREACHABLE)
            row.update({"db_revision": rel.db_revision, "min_db_revision": rel.min_db_revision,
                        "compatible": ok, "compatibility": detail,
                        "backend_digest": rel.backend_digest, "frontend_digest": rel.frontend_digest})

    def human():
        if args.instance:
            cur = context.get("current") or {}
            print(f"{args.instance}: running {cur.get('version', '?')}, db_revision {context.get('db_revision')!r}")
        for row in rows:
            marks = []
            if row.get("current"):
                marks.append("current")
            if row.get("prerelease"):
                marks.append("prerelease")
            if "compatible" in row:
                marks.append("compatible" if row["compatible"] else "INCOMPATIBLE")
            date = (row.get("published_at") or "")[:10]
            print(f"  {row['tag']:<16} {date:<10} {row.get('name') or ''}" + (f"  [{', '.join(marks)}]" if marks else ""))
            if row.get("compatible") is False:
                print(f"      {row.get('compatibility')}")

    _out(args, {"provider": cfg.release_source.provider, "releases": rows, **context}, human)
    return exitcodes.OK


def _publish(args, cfg, source, hooks, requests: RequestSource, name: str, engine: Engine,
             force: bool = False) -> Optional[str]:
    """Hand the verified release list and what release.lock says runs to the
    instance's console. Returns an error string instead of raising: a release
    list that could not be built must not stop requests from running."""
    if not isinstance(requests, HttpRequestSource) or not requests.enabled(name):
        return None
    try:
        rows = release_report.build_cached(cfg, name, source, engine.verifier, engine.probe,
                                           insecure=args.insecure_skip_verify, force=force)
    except SourceError as exc:
        rows = None
        error = f"release list unavailable: {redact(str(exc))}"
    else:
        error = None
    try:
        if rows is not None:
            requests.publish_releases(name, rows, release_report.current_images(cfg, name))
        else:
            # Still check in and report what runs, so the console shows the updater as connected.
            requests.publish_releases(name, [], release_report.current_images(cfg, name))
    except (RequestSourceError, ConfigError) as exc:
        return redact(str(exc))
    return error


def _poll(args, cfg, source, hooks, requests: RequestSource) -> int:
    """systemd timer entry point, once per instance:

    1. publish the verified release list to the console (HTTP source only);
    2. claim and run each approved request (upgrade, rollback, restart),
       reporting every step back; one claim wins, so two updaters never run
       the same request;
    3. record the instance's status.

    With the CLI request source nothing is ever pending, so this only records
    status. A console that cannot be reached is reported and skipped; it never
    stops the other instances."""
    summary = {}
    worst = exitcodes.OK
    for name in cfg.instances:
        engine = _engine(args, cfg, source, hooks, name)
        base_reporter = engine.reporter
        entry: dict = {"pending": 0, "ran": []}
        publish_error = _publish(args, cfg, source, hooks, requests, name, engine)
        if publish_error:
            entry["publish_error"] = publish_error
        try:
            pending = requests.pending(name)
        except (RequestSourceError, ConfigError) as exc:
            pending = []
            entry["request_error"] = redact(str(exc))
            worst = max(worst, exitcodes.ERROR)
        entry["pending"] = len(pending)
        for req in pending:
            try:
                if not requests.claim(req):
                    entry["ran"].append({"request": req.id, "outcome": "claimed_elsewhere"})
                    continue
            except RequestSourceError as exc:
                entry.setdefault("errors", []).append(redact(str(exc)))
                continue
            engine.approval = requests.approval_policy_for(req)
            engine.reporter = MultiReporter([LostTrackMarker(req), base_reporter, requests.reporter(req)])
            run = RunContext(instance=name, action=req.action, tag=req.tag, requested_by=req.requested_by,
                             request_id=req.id, insecure=args.insecure_skip_verify)
            try:
                # Heartbeats renew the console's lease while long steps run.
                with requests.heartbeat(req):
                    if req.action == "upgrade":
                        outcome = engine.upgrade(run, req)
                    elif req.action == "rollback":
                        outcome = engine.rollback(run, req)
                    else:
                        outcome = engine.restart(run, req)
            except (InstanceNotReady, LockFileError) as exc:
                # Claimed but cannot act: say so to the console rather than
                # leaving the request "claimed" forever.
                from pinpoint_updater.models import RunOutcome
                outcome = RunOutcome("refused", f"{redact(str(exc))}; nothing changed")
                engine.reporter.finished(run, outcome)
            finally:
                engine.reporter = base_reporter
            entry["ran"].append({"request": req.id, "action": req.action, "outcome": outcome.outcome,
                                 **({"console_lost_track": True} if req.console_lost else {})})
            worst = max(worst, exitcodes.for_outcome(outcome.outcome))
        if entry["ran"] and any(r.get("outcome") not in (None, "claimed_elsewhere") for r in entry["ran"]):
            # What runs may have changed: tell the console now, not at the next hourly rebuild.
            err = _publish(args, cfg, source, hooks, requests, name, engine, force=True)
            if err:
                entry["publish_error"] = err
        st = engine.status()
        entry.update({"health": st.get("health"), "drift": st.get("drift"), "error": st.get("error")})
        summary[name] = entry
    _out(args, summary, lambda: [print(f"{n}: {json.dumps(redact(s), default=str)}") for n, s in summary.items()])
    return worst
