"""Phase 3: the console request channel (HttpRequestSource), poll, restart.

A fake console behind httpx.MockTransport implements the backend side of
/api/internal/updater/* (backend/app/api/updater_internal.py): bearer token,
approved requests, one claim wins, steps, outcome, releases.
"""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest
import yaml

from conftest import (D_NEW_B, FakeProbe, FakeSource, base_config, good_runner, healthy, is_compose, is_cosign,
                      make_instance_dir)
from pinpoint_updater import cli, exitcodes
from pinpoint_updater.config import ConfigError, parse_config
from pinpoint_updater.lockfile import read_lock
from pinpoint_updater.models import RunContext, RunOutcome, StepResult
from pinpoint_updater.request_source import (ConsoleApproval, HttpRequestSource, RequestSourceError,
                                             TwoPersonApproval, UpgradeRequest)
from pinpoint_updater.sources import ReleaseInfo

TOKEN = "ppu_" + "s3cr3t" * 7


class FakeConsole:
    def __init__(self, requests=None, token=TOKEN):
        self.token = token
        self.requests = {str(r["id"]): {"status": "approved", **r} for r in (requests or [])}
        self.steps: dict[str, list] = {}
        self.outcomes: dict[str, dict] = {}
        self.releases = None
        self.calls: list[tuple[str, str, dict]] = []
        self.fail: dict[str, list[int]] = {}   # path suffix -> status codes to answer first
        self.lease: float | None = None        # seconds without a report before a request expires
        self.last: dict[str, float] = {}
        self.heartbeats: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path, dict(request.headers)))
        for suffix, codes in self.fail.items():
            if path.endswith(suffix) and codes:
                return httpx.Response(codes.pop(0), json={"detail": f"boom {self.token}"})
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"detail": "Invalid or revoked updater token"})
        assert path.startswith("/api/internal/updater/")
        rest = path[len("/api/internal/updater"):]
        body = json.loads(request.content) if request.content else None
        if rest == "/requests" and request.method == "GET":
            return httpx.Response(200, json={"requests": [
                {k: v for k, v in r.items() if k != "status"} for r in self.requests.values() if r["status"] == "approved"]})
        if rest == "/releases" and request.method == "PUT":
            self.releases = body
            return httpx.Response(200, json={"ok": True})
        parts = rest.strip("/").split("/")
        rid, kind = parts[1], parts[2]
        req = self.requests.get(rid)
        if req is None:
            return httpx.Response(404, json={"detail": "No such request"})
        if kind == "claim":
            if req["status"] != "approved":
                return httpx.Response(409, json={"detail": "not claimable"})
            req["status"] = "claimed"
            self.last[rid] = time.monotonic()
            return httpx.Response(200, json={"claimed": True})
        if (req["status"] in ("claimed", "running") and self.lease is not None
                and time.monotonic() - self.last.get(rid, 0) > self.lease):
            req["status"] = "lease_expired"
        if req["status"] not in ("claimed", "running"):
            return httpx.Response(409, json={"detail": f"request is {req['status']}; not applied"})
        self.last[rid] = time.monotonic()
        if kind == "heartbeat":
            self.heartbeats[rid] = self.heartbeats.get(rid, 0) + 1
            return httpx.Response(200, json={"ok": True})
        if kind == "steps":
            req["status"] = "running"
            self.steps.setdefault(rid, []).append(body)
            return httpx.Response(200, json={"ok": True})
        if kind == "outcome":
            req["status"] = body["outcome"]
            self.outcomes[rid] = body
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)


def _cfg(tmp_path, **inst):
    make_instance_dir(tmp_path)
    (tmp_path / "pinpoint-town" / "updater.token").write_text(TOKEN + "\n")
    overrides = {"token_file": "updater.token", "api_url": "http://127.0.0.1:58004"}
    overrides.update(inst)
    return base_config(tmp_path, **overrides)


def _source(cfg_dict, console, **kw):
    return HttpRequestSource(parse_config(cfg_dict), transport=httpx.MockTransport(console.handler),
                             sleep=lambda s: None, **kw)


# ---------------------------------------------------------------------------
# HttpRequestSource
# ---------------------------------------------------------------------------

def test_pending_parses_requests_and_drops_malformed_ones(tmp_path, capsys):
    console = FakeConsole([
        {"id": 7, "action": "upgrade", "tag": "v1.8.0", "requested_by": "alice", "reason": "patch",
         "approvals": ["bob"], "allow_destructive": True, "policy": "two_person"},
        {"id": 8, "action": "restart", "tag": "ignored", "requested_by": "carol", "approvals": ["carol"],
         "allow_destructive": True, "policy": "single"},
        {"id": 9, "action": "rm -rf", "requested_by": "x"},
        {"id": 10, "action": "upgrade", "tag": "../../etc", "requested_by": "x"},
        {"id": "abc", "action": "upgrade", "tag": "v1", "requested_by": "x"},
    ])
    src = _source(_cfg(tmp_path), console)
    reqs = src.pending("town")
    assert [(r.id, r.action, r.tag) for r in reqs] == [("7", "upgrade", "v1.8.0"), ("8", "restart", None)]
    up, restart = reqs
    assert up.approvals == ["bob"] and up.allow_destructive and up.policy == "two_person" and up.source == "http"
    assert restart.allow_destructive is False  # only an upgrade carries a destructive migration
    method, path, headers = console.calls[0]
    assert (method, path) == ("GET", "/api/internal/updater/requests")
    assert headers["authorization"] == f"Bearer {TOKEN}" and headers["user-agent"].startswith("pinpoint-updater/")
    assert str(console.calls[0]) and "ignoring" in capsys.readouterr().err
    src.close()


def test_claim_is_true_only_for_the_winner(tmp_path):
    console = FakeConsole([{"id": 3, "action": "restart", "requested_by": "a", "approvals": ["a"]}])
    src = _source(_cfg(tmp_path), console)
    (req,) = src.pending("town")
    assert src.claim(req) is True
    assert src.claim(req) is False          # 409: someone (or a cancel) won
    gone = UpgradeRequest(instance="town", action="restart", tag=None, requested_by="a", source="http", id="99")
    assert src.claim(gone) is False         # 404


def test_a_bad_token_and_server_errors_are_reported_with_the_token_masked(tmp_path):
    console = FakeConsole(token="ppu_" + "other" * 9)
    src = _source(_cfg(tmp_path), console)
    with pytest.raises(RequestSourceError) as exc:
        src.pending("town")
    assert "401" in str(exc.value) and "revoked" in str(exc.value)

    console = FakeConsole()
    console.fail["/requests"] = [500]
    src = _source(_cfg(tmp_path), console)
    with pytest.raises(RequestSourceError) as exc:
        src.pending("town")
    assert "500" in str(exc.value) and TOKEN not in str(exc.value) and "***" in str(exc.value)


def test_redirects_are_not_followed(tmp_path):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    src = HttpRequestSource(parse_config(_cfg(tmp_path)), transport=httpx.MockTransport(handler))
    with pytest.raises(RequestSourceError):
        src.pending("town")
    assert seen == ["http://127.0.0.1:58004/api/internal/updater/requests"]


def test_an_unreachable_backend_and_a_missing_token_file(tmp_path):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    src = HttpRequestSource(parse_config(_cfg(tmp_path)), transport=httpx.MockTransport(handler))
    with pytest.raises(RequestSourceError) as exc:
        src.pending("town")
    assert "ConnectError" in str(exc.value)

    cfg = _cfg(tmp_path, token_file="missing.token")
    with pytest.raises(ConfigError):
        HttpRequestSource(parse_config(cfg)).pending("town")


def test_instances_without_a_token_file_are_skipped(tmp_path):
    console = FakeConsole([{"id": 1, "action": "restart", "requested_by": "a", "approvals": ["a"]}])
    cfg = base_config(tmp_path)
    make_instance_dir(tmp_path)
    src = HttpRequestSource(parse_config(cfg), transport=httpx.MockTransport(console.handler))
    assert src.pending("town") == [] and console.calls == []
    src.publish_releases("town", [{"tag": "v1"}])
    assert console.calls == []


def test_the_reporter_posts_steps_and_retries_the_outcome(tmp_path):
    console = FakeConsole([{"id": 5, "action": "restart", "requested_by": "a", "approvals": ["a"]}])
    src = _source(_cfg(tmp_path), console)
    (req,) = src.pending("town")
    assert src.claim(req)
    rep = src.reporter(req)
    run = RunContext(instance="town", action="restart", request_id="5")
    rep.step(run, StepResult("restart", "ok", f"restarted; token {TOKEN} must not leak"))
    console.fail["/outcome"] = [502, 503]
    rep.finished(run, RunOutcome("succeeded", "town restarted"))
    assert console.steps["5"][0]["name"] == "restart" and TOKEN not in json.dumps(console.steps["5"])
    assert console.outcomes["5"]["outcome"] == "succeeded" and console.outcomes["5"]["request_id"] == "5"


@pytest.mark.parametrize("action,policy,floor,expected", [
    ("restart", "two_person", None, ConsoleApproval),
    ("upgrade", "single", None, ConsoleApproval),
    ("upgrade", "two_person", None, TwoPersonApproval),
    ("rollback", "two_person", None, TwoPersonApproval),
    ("upgrade", "single", True, TwoPersonApproval),   # the host pins two-person approval
])
def test_approval_policy_per_request(tmp_path, action, policy, floor, expected):
    src = _source(_cfg(tmp_path, require_two_person_approval=floor), FakeConsole())
    req = UpgradeRequest(instance="town", action=action, tag="v1.8.0", requested_by="alice", source="http",
                         approvals=["alice"], policy=policy)
    assert isinstance(src.approval_policy_for(req), expected)


def test_api_url_must_be_loopback(tmp_path):
    with pytest.raises(ConfigError):
        parse_config(_cfg(tmp_path, api_url="https://town.example.gov"))


# ---------------------------------------------------------------------------
# poll, end to end against the fake console
# ---------------------------------------------------------------------------

class ListingSource(FakeSource):
    listed = 0

    def list_releases(self, limit=20):
        ListingSource.listed += 1
        return [ReleaseInfo("v1.8.0", "1.8.0", "2026-10-10T00:00:00Z", "## notes", "https://example.test/r", False),
                ReleaseInfo("v1.7.0", "1.7.0", "2026-09-01T00:00:00Z", "older", None, False)]


def _poll(tmp_path, console, *, runner=None, probe=None, cfg=None, insecure=False, heartbeat=60.0):
    path = tmp_path / "instances.yml"
    path.write_text(yaml.safe_dump(cfg or _cfg(tmp_path)))
    h = cli.Hooks()
    h.source_factory = lambda c: ListingSource()
    runner = runner or good_runner()
    h.runner_factory = lambda: runner
    probe = probe or FakeProbe([healthy("1.7.0", "aaa"), healthy("1.7.0", "aaa"), healthy("1.8.0", "bbb")])
    h.probe_factory = lambda url: probe
    h.deps_overrides = {"sleep": lambda s: None}
    h.http_source_factory = lambda c: HttpRequestSource(c, transport=httpx.MockTransport(console.handler),
                                                        sleep=lambda s: None, heartbeat_interval=heartbeat)
    argv = ["-c", str(path), "--json"] + (["--insecure-skip-verify"] if insecure else []) + ["poll"]
    return cli.main(argv, h), runner


def test_poll_publishes_releases_then_runs_an_approved_upgrade(tmp_path, capsys):
    console = FakeConsole([{"id": 12, "action": "upgrade", "tag": "v1.8.0", "requested_by": "alice",
                            "reason": "patch", "approvals": ["bob"], "policy": "two_person"}])
    code, runner = _poll(tmp_path, console)
    out = json.loads(capsys.readouterr().out)
    assert code == exitcodes.OK, out
    assert out["town"]["ran"] == [{"request": "12", "action": "upgrade", "outcome": "succeeded"}]
    # Steps and the outcome reached the console, in order.
    names = [s["name"] for s in console.steps["12"]]
    assert names[0] == "resolve" and names[-1] == "commit" and "backup" in names and "health" in names
    assert console.outcomes["12"]["outcome"] == "succeeded"
    # The release list: verified (cosign ran), compatible, with what runs now.
    rel = console.releases
    first = rel["releases"][0]
    assert first["tag"] == "v1.8.0" and first["signature_verified"] is True and first["gate_passed"] is True
    assert first["compatible"] is True and first["backend_digest"] == D_NEW_B and first["notes"] == "## notes"
    assert rel["current"]["version"] == "v1.8.0"   # republished after the upgrade
    assert read_lock(tmp_path / "pinpoint-town" / "release.lock").current.version == "v1.8.0"
    assert any(is_cosign(c) for c in runner.calls)


def test_poll_restart_restarts_only_this_project_s_app_services(tmp_path, capsys):
    console = FakeConsole([{"id": 4, "action": "restart", "requested_by": "carol", "reason": "stuck worker",
                            "approvals": ["carol"], "policy": "single"}])
    probe = FakeProbe([healthy("1.7.0", "aaa")])
    code, runner = _poll(tmp_path, console, probe=probe)
    out = json.loads(capsys.readouterr().out)
    assert code == exitcodes.OK and out["town"]["ran"][0]["outcome"] == "succeeded"
    restarts = runner.subcommand_calls("restart")
    assert len(restarts) == 1 and restarts[0][0] == ["restart", "backend", "worker", "frontend"]
    full = next(c for c in runner.calls if is_compose("restart")(c))
    assert full[full.index("-p") + 1] == "pinpoint-town"
    assert not runner.subcommand_calls("up") and not runner.subcommand_calls("pull")
    assert [s["name"] for s in console.steps["4"]] == ["restart", "health"]
    assert read_lock(tmp_path / "pinpoint-town" / "release.lock").current.version == "v1.7.0"


def test_a_two_person_request_approved_only_by_its_requester_is_refused(tmp_path, capsys):
    console = FakeConsole([{"id": 6, "action": "upgrade", "tag": "v1.8.0", "requested_by": "alice",
                            "approvals": ["alice"], "policy": "two_person"}])
    code, runner = _poll(tmp_path, console)
    assert console.outcomes["6"]["outcome"] == "not_confirmed"
    assert "other than alice" in console.outcomes["6"]["summary"]
    assert not runner.subcommand_calls("up")


def test_a_restart_that_comes_back_unhealthy_is_an_error(tmp_path, capsys):
    console = FakeConsole([{"id": 2, "action": "restart", "requested_by": "a", "approvals": ["a"], "policy": "single"}])
    probe = FakeProbe([healthy("1.7.0", "aaa")], statuses={"/": 502, "/api/services/": 200})
    code, _ = _poll(tmp_path, console, probe=probe)
    assert console.outcomes["2"]["outcome"] == "error" and "not healthy" in console.outcomes["2"]["summary"]
    assert code == exitcodes.ERROR


def test_a_compose_restart_failure_is_reported(tmp_path, capsys):
    console = FakeConsole([{"id": 2, "action": "restart", "requested_by": "a", "approvals": ["a"], "policy": "single"}])
    runner = good_runner().on(is_compose("restart"), 1, "", "no such service")
    code, _ = _poll(tmp_path, console, runner=runner, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    assert console.outcomes["2"]["outcome"] == "error"
    assert console.steps["2"][0]["status"] == "failed" and "no such service" in console.steps["2"][0]["detail"]


def test_poll_survives_an_unreachable_console(tmp_path, capsys):
    console = FakeConsole()
    console.fail["/releases"] = [503]
    console.fail["/requests"] = [503]
    code, runner = _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    out = json.loads(capsys.readouterr().out)
    assert code == exitcodes.ERROR
    assert "503" in out["town"]["request_error"] and "503" in out["town"]["publish_error"]
    assert not runner.subcommand_calls("up")


def test_insecure_runs_never_claim_a_signature(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(cli.ALLOW_INSECURE_ENV, "1")
    console = FakeConsole()
    code, runner = _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]), insecure=True)
    first = console.releases["releases"][0]
    assert first["signature_verified"] is None and first["gate_passed"] is None
    assert not any(is_cosign(c) for c in runner.calls)


def test_verified_digests_are_cached_between_polls(tmp_path, capsys):
    console = FakeConsole()
    _, runner1 = _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    assert any(is_cosign(c) for c in runner1.calls)
    _, runner2 = _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    assert not any(is_cosign(c) for c in runner2.calls)
    assert console.releases["releases"][0]["signature_verified"] is True


# ---------------------------------------------------------------------------
# A one-minute timer stays cheap
# ---------------------------------------------------------------------------

def test_repeated_polls_with_nothing_new_call_no_release_api_and_no_cosign(tmp_path, capsys):
    console = FakeConsole()
    ListingSource.listed = 0
    _, first = _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    assert ListingSource.listed == 1 and any(is_cosign(c) for c in first.calls)
    for _ in range(3):
        _, again = _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
        assert not any(is_cosign(c) for c in again.calls)
    assert ListingSource.listed == 1
    # Still published every time, from the cache, with the badges intact.
    assert console.releases["releases"][0]["signature_verified"] is True
    assert sum(1 for m, p, _ in console.calls if m == "PUT") == 4


def test_the_cached_list_rechecks_the_schema_against_the_live_revision(tmp_path, capsys):
    console = FakeConsole()
    _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    assert console.releases["releases"][0]["compatible"] is True
    # The database moved somewhere the cached release cannot serve.
    _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "zzz")]))
    first = console.releases["releases"][0]
    assert first["compatible"] is False and "outside compatibility window" in first["compatibility"]


def test_the_list_is_rebuilt_after_the_refresh_interval_or_a_run(tmp_path, capsys):
    from pinpoint_updater import release_report

    console = FakeConsole()
    ListingSource.listed = 0
    _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    cache = tmp_path / "log" / "town.releases.json"
    data = json.loads(cache.read_text())
    data["built_at"] -= 3601
    cache.write_text(json.dumps(data))
    _, runner = _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    assert ListingSource.listed == 2
    assert not any(is_cosign(c) for c in runner.calls)  # digests already verified
    # A run forces a rebuild so the console sees what changed.
    console.requests = {"5": {"id": 5, "action": "restart", "requested_by": "a", "approvals": ["a"],
                              "policy": "single", "status": "approved"}}
    _poll(tmp_path, console, probe=FakeProbe([healthy("1.7.0", "aaa")]))
    assert ListingSource.listed == 3
    assert release_report  # imported for the cache path's owner


def test_the_timer_runs_every_minute():
    from pathlib import Path

    timer = (Path(__file__).resolve().parents[1] / "deploy" / "pinpoint-updater.timer").read_text()
    assert "OnUnitInactiveSec=1min" in timer and "RandomizedDelaySec=10s" in timer


# ---------------------------------------------------------------------------
# Heartbeats keep a long step alive past the console's lease
# ---------------------------------------------------------------------------

def _slow_restart(seconds):
    def slow(args, env):
        time.sleep(seconds)
        return 0, "", ""
    runner = good_runner()
    runner.rules.insert(0, (is_compose("restart"), slow))
    return runner


def _restart_console(lease):
    console = FakeConsole([{"id": 4, "action": "restart", "requested_by": "c", "approvals": ["c"], "policy": "single"}])
    console.lease = lease
    return console


def test_heartbeats_keep_a_step_longer_than_the_lease_alive(tmp_path, capsys):
    console = _restart_console(lease=0.25)
    code, _ = _poll(tmp_path, console, runner=_slow_restart(0.8), probe=FakeProbe([healthy("1.7.0", "aaa")]),
                    heartbeat=0.05)
    assert code == exitcodes.OK
    assert console.heartbeats["4"] >= 5
    assert console.outcomes["4"]["outcome"] == "succeeded"
    assert [s["name"] for s in console.steps["4"]] == ["restart", "health"]  # beats add no steps


def test_without_heartbeats_the_same_step_expires_and_the_run_says_console_lost_track(tmp_path, capsys):
    console = _restart_console(lease=0.25)
    code, _ = _poll(tmp_path, console, runner=_slow_restart(0.6), probe=FakeProbe([healthy("1.7.0", "aaa")]),
                    heartbeat=None)
    out = json.loads(capsys.readouterr().out)
    assert console.requests["4"]["status"] == "lease_expired" and "4" not in console.outcomes
    ran = out["town"]["ran"][0]
    assert ran["outcome"] == "succeeded" and ran["console_lost_track"] is True   # the run itself finished
    log = [json.loads(l) for l in (tmp_path / "log" / "town.jsonl").read_text().splitlines()]
    outcome = [r for r in log if r["type"] == "outcome"][-1]
    assert outcome["data"]["console"] == "lost track" and "console lost track" in outcome["summary"]


def test_a_refused_heartbeat_is_logged_loudly_and_the_run_continues(tmp_path, capsys):
    console = _restart_console(lease=None)
    console.fail["/heartbeat"] = [409] * 100
    code, runner = _poll(tmp_path, console, runner=_slow_restart(0.3), probe=FakeProbe([healthy("1.7.0", "aaa")]),
                         heartbeat=0.05)
    captured = capsys.readouterr()
    assert "CONSOLE LOST TRACK of request 4" in captured.err
    assert runner.subcommand_calls("restart")                       # the run was not abandoned
    assert "4" not in console.steps and "4" not in console.outcomes  # nothing posted after the 409
    out = json.loads(captured.out)
    assert out["town"]["ran"][0]["console_lost_track"] is True


def test_the_heartbeat_thread_stops_when_the_step_ends_or_raises(tmp_path):
    console = _restart_console(lease=None)
    src = _source(_cfg(tmp_path), console, heartbeat_interval=0.02)
    (req,) = src.pending("town")
    assert src.claim(req)
    before = threading.active_count()
    with src.heartbeat(req) as hb:
        time.sleep(0.15)
    assert hb.thread is not None and not hb.thread.is_alive() and hb.beats >= 3
    beats = console.heartbeats["4"]
    time.sleep(0.1)
    assert console.heartbeats["4"] == beats            # no beats after exit

    with pytest.raises(RuntimeError):
        with src.heartbeat(req) as hb2:
            time.sleep(0.05)
            raise RuntimeError("step blew up")
    assert not hb2.thread.is_alive()
    assert threading.active_count() <= before
    # Disabled: no thread at all.
    src0 = _source(_cfg(tmp_path), console, heartbeat_interval=None)
    with src0.heartbeat(req) as hb3:
        pass
    assert hb3.thread is None
