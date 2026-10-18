"""End to end through the console: a real backend, a real updater poll, a real
throwaway compose project.

Opt-in: ``PINPOINT_UPDATER_E2E=1`` and ``PINPOINT_UPDATER_E2E_BACKEND_IMAGE``
(an image of backend/, e.g. ``pinpoint-311-backend:latest``; the repo's
backend/ is mounted over /app so the code under test is this checkout's).

Starts a throwaway PostGIS and the backend on a private network with the
backend on a free loopback port, creates two admins, then drives the same
throwaway "town" stack the Phase 2 e2e uses:

1. alice creates an updater token in the admin API; it goes in token_file;
2. ``poll`` checks in (the console now shows an updater);
3. alice files a restart (one admin) -> ``poll`` restarts backend, worker and
   frontend of that project only -> the console shows succeeded with steps;
4. a verified release list naming r2 is reported (local images cannot carry
   a cosign signature, so the test reports it as the updater would for a
   signed release), alice requests r2, alice's own approval is refused, bob
   approves -> ``poll`` upgrades -> succeeded, the town serves 2.0.0.

Everything it starts is removed afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

from pinpoint_updater import cli, exitcodes
from pinpoint_updater.lockfile import read_lock
from test_e2e import LocalSource, _allow_insecure, _free_port, stack  # noqa: F401  (fixtures)

BACKEND_IMAGE = os.environ.get("PINPOINT_UPDATER_E2E_BACKEND_IMAGE")
REPO = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("PINPOINT_UPDATER_E2E") != "1", reason="set PINPOINT_UPDATER_E2E=1"),
    pytest.mark.skipif(not BACKEND_IMAGE, reason="set PINPOINT_UPDATER_E2E_BACKEND_IMAGE"),
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available"),
]

MAKE_ADMINS = r"""
import asyncio, json
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import User
from app.core.auth import create_session_token
async def main():
    out = {}
    async with SessionLocal() as s:
        for name in ("alice", "bob"):
            u = User(username=name, email=f"{name}@e2e.invalid", role="admin", is_active=True)
            s.add(u)
        await s.commit()
        for name in ("alice", "bob"):
            u = (await s.execute(select(User).where(User.username == name))).scalar_one()
            out[name] = create_session_token(u)
    print("TOKENS" + json.dumps(out))
asyncio.run(main())
"""


def _docker(*args, check=True, timeout=300):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=check)


@pytest.fixture(scope="module")
def console():
    uid = uuid.uuid4().hex[:8]
    net, db, be = f"pp-con-e2e-{uid}", f"pp-con-e2e-db-{uid}", f"pp-con-e2e-be-{uid}"
    port = _free_port()
    env = ["-e", f"DATABASE_URL=postgresql+asyncpg://t:t@{db}:5432/t",
           "-e", "SECRET_KEY=" + uuid.uuid4().hex + uuid.uuid4().hex,
           "-e", "REDIS_URL=redis://127.0.0.1:1/0", "-e", "UPLOAD_DIR=/tmp/uploads"]
    try:
        _docker("network", "create", net)
        _docker("run", "-d", "--rm", "--name", db, "--network", net, "-e", "POSTGRES_USER=t", "-e", "POSTGRES_PASSWORD=t",
                "-e", "POSTGRES_DB=t", "ghcr.io/baosystems/postgis:15-3.3")
        for _ in range(60):
            if _docker("exec", db, "pg_isready", "-U", "t", check=False).returncode == 0:
                break
            time.sleep(1)
        time.sleep(2)
        mount = ["-v", f"{REPO / 'backend'}:/app"]
        _docker("run", "--rm", "--network", net, *env, *mount, "--entrypoint", "python", BACKEND_IMAGE,
                "-m", "app.db.migrate", timeout=600)
        _docker("run", "-d", "--rm", "--name", be, "--network", net, *env, *mount, "-p", f"127.0.0.1:{port}:8000",
                "--entrypoint", "uvicorn", BACKEND_IMAGE, "app.main:app", "--host", "0.0.0.0", "--port", "8000")
        base = f"http://127.0.0.1:{port}"
        for _ in range(90):
            try:
                if httpx.get(f"{base}/api/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail("backend never came up:\n" + _docker("logs", be, check=False).stderr[-3000:])
        out = _docker("exec", be, "python", "-c", MAKE_ADMINS).stdout
        tokens = json.loads(out.split("TOKENS", 1)[1])
        yield {"base": base, "tokens": tokens, "backend": be}
    finally:
        _docker("rm", "-f", be, check=False)
        _docker("rm", "-f", db, check=False)
        _docker("network", "rm", net, check=False)


def _admin(console, who):
    return httpx.Client(base_url=console["base"], timeout=30,
                        headers={"Authorization": f"Bearer {console['tokens'][who]}"})


def _poll(stack, capsys):
    capsys.readouterr()
    hooks = cli.Hooks()
    hooks.source_factory = lambda cfg: LocalSource(stack["prefix"])
    code = cli.main(["-c", str(stack["cfg_path"]), "--insecure-skip-verify", "--json", "poll"], hooks)
    out = capsys.readouterr().out
    return code, json.loads(out[out.index("{"):])


def test_console_request_flows_through_the_updater(stack, console, capsys):
    alice, bob = _admin(console, "alice"), _admin(console, "bob")

    # Nothing can be requested before an updater checks in.
    r = alice.post("/api/system/upgrade-requests", json={"action": "restart", "reason": "e2e restart"})
    assert r.status_code == 409, r.text

    # 1. token -> token_file; register the console on the instance
    created = alice.post("/api/system/updater-tokens", json={"label": "e2e"}).json()
    (stack["dir"] / "updater.token").write_text(created["token"] + "\n")
    os.chmod(stack["dir"] / "updater.token", 0o600)
    cfg = yaml.safe_load(stack["cfg_path"].read_text())
    cfg["instances"]["e2e"]["token_file"] = "updater.token"
    cfg["instances"]["e2e"]["api_url"] = console["base"]
    stack["cfg_path"].write_text(yaml.safe_dump(cfg))

    # 2. first poll: checks in
    code, out = _poll(stack, capsys)
    assert code == exitcodes.OK, out
    state = alice.get("/api/system/releases").json()["updater"]
    assert state["connected"] is True and state["current"]["version"] == "r1"

    # 3. a restart: one admin, this project only
    restart = alice.post("/api/system/upgrade-requests", json={"action": "restart", "reason": "e2e restart"}).json()
    assert restart["status"] == "approved"
    before = _docker("ps", "-q", "--filter", f"label=com.docker.compose.project={stack['project']}").stdout.split()
    code, out = _poll(stack, capsys)
    assert out["e2e"]["ran"] == [{"request": str(restart["id"]), "action": "restart", "outcome": "succeeded"}], out
    detail = alice.get(f"/api/system/upgrade-requests/{restart['id']}").json()
    assert detail["status"] == "succeeded" and [s["step"] for s in detail["steps"]] == ["restart", "health"]
    after = _docker("ps", "-q", "--filter", f"label=com.docker.compose.project={stack['project']}").stdout.split()
    assert sorted(before) == sorted(after)  # restarted in place, not recreated

    # 4. an upgrade with two-person approval
    report = {"releases": [{"tag": "r2", "version": "2.0.0", "name": "r2", "signature_verified": True,
                            "gate_passed": True, "compatible": True, "compatibility": "inside window"}]}
    r = httpx.put(f"{console['base']}/api/internal/updater/releases", json=report,
                  headers={"Authorization": f"Bearer {created['token']}"})
    assert r.status_code == 200, r.text
    # ...and the same call through a proxy is refused.
    r = httpx.put(f"{console['base']}/api/internal/updater/releases", json=report,
                  headers={"Authorization": f"Bearer {created['token']}", "X-Forwarded-For": "203.0.113.7"})
    assert r.status_code == 404
    up = alice.post("/api/system/upgrade-requests",
                    json={"action": "upgrade", "target_tag": "r2", "reason": "e2e upgrade"}).json()
    assert up["status"] == "pending_approval", up
    assert alice.post(f"/api/system/upgrade-requests/{up['id']}/approve").status_code == 403
    code, out = _poll(stack, capsys)
    assert out["e2e"]["ran"] == [], "an unapproved request must not run"
    assert bob.post(f"/api/system/upgrade-requests/{up['id']}/approve").json()["status"] == "approved"
    code, out = _poll(stack, capsys)
    assert out["e2e"]["ran"] == [{"request": str(up["id"]), "action": "upgrade", "outcome": "succeeded"}], out
    detail = alice.get(f"/api/system/upgrade-requests/{up['id']}").json()
    assert detail["status"] == "succeeded"
    steps = [s["step"] for s in detail["steps"]]
    assert steps[0] == "resolve" and "backup" in steps and "migrate" in steps and steps[-1] == "commit"
    assert stack["probe"].quick()["version"] == "2.0.0"
    assert read_lock(stack["dir"] / "release.lock").current.version == "r2"
    assert alice.get("/api/system/releases").json()["updater"]["current"]["version"] == "r2"

    # The audit trail has the whole story.
    events = alice.get("/api/audit/logs", params={"limit": 100}).json()
    names = {e.get("event_type") for e in (events.get("logs") if isinstance(events, dict) else events) or []}
    assert {"updater_token_created", "upgrade_request_created", "upgrade_request_approved",
            "upgrade_request_claimed", "upgrade_request_finished"} <= names
