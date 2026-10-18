"""End to end against a real, throwaway compose project.

Opt-in (``PINPOINT_UPDATER_E2E=1``): builds tiny local images from
tests/e2e_app tagged as four "releases", starts a uniquely named compose
project bound to a free loopback port, drives the real CLI through upgrade,
failed-health rollback, gated migration and operator rollback, then removes the
project, its volume and every image it built.

Signatures cannot be checked on local images, so this runs with
``--insecure-skip-verify`` under ``PINPOINT_UPDATER_ALLOW_INSECURE=1`` — the
same gate an operator would have to pass.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

from pinpoint_updater import cli, exitcodes
from pinpoint_updater.compose import Compose
from pinpoint_updater.config import load_config
from pinpoint_updater.health import AppProbe, ProbeError
from pinpoint_updater.lockfile import ImageSet, LockState, read_lock, write_lock
from pinpoint_updater.runner import Runner
from pinpoint_updater.sources import ResolvedRelease

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("PINPOINT_UPDATER_E2E") != "1", reason="set PINPOINT_UPDATER_E2E=1"),
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available"),
]

APP = Path(__file__).parent / "e2e_app"
RELEASES = {
    # tag: build args
    "r1": {"APP_VERSION": "1.0.0", "DB_REV": "rev1"},
    "r2": {"APP_VERSION": "2.0.0", "DB_REV": "rev2", "MIN_DB_REV": "rev1"},
    "r3": {"APP_VERSION": "3.0.0", "DB_REV": "rev2", "MIN_DB_REV": "rev2", "BROKEN": "1"},
    "r4": {"APP_VERSION": "4.0.0", "DB_REV": "rev4", "MIN_DB_REV": "rev2", "DESTRUCTIVE": "1"},
}


def _docker(*args, check=True, timeout=600):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=check)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalSource:
    """Release source over locally built tags (no registry, no digests)."""

    provider = "local"

    def __init__(self, prefix):
        self.prefix = prefix

    def resolve(self, tag):
        args = RELEASES[tag]
        return ResolvedRelease(
            tag=tag, version=args["APP_VERSION"], backend_image=f"{self.prefix}-backend:{tag}",
            frontend_image=f"{self.prefix}-frontend:{tag}", backend_digest="", frontend_digest="",
            db_revision=args["DB_REV"], min_db_revision=args.get("MIN_DB_REV"),
            frontend_version=args["APP_VERSION"], stamp_complete=True)

    def stamp_for_ref(self, ref):
        tag = ref.rsplit(":", 1)[1]
        a = RELEASES[tag]
        return {"version": a["APP_VERSION"], "db_revision": a["DB_REV"], "min_db_revision": a.get("MIN_DB_REV")}

    def list_releases(self, limit=20):
        return []

    def close(self):
        pass


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    uid = uuid.uuid4().hex[:8]
    prefix = f"pp-upd-e2e-{uid}"
    project = f"pp-upd-e2e-{uid}"
    built: list[str] = []
    inst_dir = tmp_path_factory.mktemp("instance")
    port = _free_port()
    try:
        for tag, args in RELEASES.items():
            build_args = []
            for k, v in args.items():
                build_args += ["--build-arg", f"{k}={v}"]
            b, f = f"{prefix}-backend:{tag}", f"{prefix}-frontend:{tag}"
            _docker("build", "-q", "-t", b, "-t", f, *build_args, str(APP))
            built += [b, f]

        (inst_dir / ".env.e2e").write_text(f"E2E_PORT={port}\n")
        r1 = ImageSet("r1", f"{prefix}-backend:r1", f"{prefix}-frontend:r1", app_version="1.0.0")
        write_lock(inst_dir / "release.lock", LockState(current=r1))
        config = {
            "release_source": {"provider": "github", "api": "https://api.github.com", "project": "x/y",
                               "registry": "localhost/e2e"},
            "trust": {"key": "/nonexistent/cosign.pub"},
            "log_dir": str(inst_dir / "log"),
            "disk_path": str(inst_dir),
            "instances": {"e2e": {
                "project": project, "dir": str(inst_dir), "compose": [str(APP / "docker-compose.yml")],
                "env_file": ".env.e2e", "app_url": f"http://127.0.0.1:{port}",
                "backup": {"mode": "verify", "command": ["python", "/app/fakeapp.py", "backup"]},
                "migrate_command": ["python", "/app/fakeapp.py", "migrate"],
                "worker_ping": ["python", "/app/fakeapp.py", "ping"],
                "health_timeout": 25, "health_interval": 1, "min_free_gb": 0.1,
            }},
        }
        cfg_path = inst_dir / "instances.yml"
        cfg_path.write_text(yaml.safe_dump(config))

        # Bring the "currently deployed" r1 up the way an operator would.
        cfg = load_config(cfg_path)
        result = Compose(cfg.instances["e2e"], Runner()).recreate(r1)
        assert result.ok, result.tail()
        probe = AppProbe(f"http://127.0.0.1:{port}")
        import time
        for _ in range(60):
            try:
                if probe.quick().get("db_revision") == "rev1":
                    break
            except ProbeError:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("r1 never came up")
        yield {"cfg_path": cfg_path, "dir": inst_dir, "prefix": prefix, "project": project, "probe": probe}
    finally:
        subprocess.run(["docker", "compose", "-p", project, "-f", str(APP / "docker-compose.yml"),
                        "--env-file", str(inst_dir / ".env.e2e"), "--env-file", str(inst_dir / "release.lock"),
                        "down", "-v", "--remove-orphans", "--timeout", "2"],
                       capture_output=True, text=True, timeout=300)
        if built:
            subprocess.run(["docker", "rmi", "-f", *built], capture_output=True, text=True, timeout=300)


def _cli(stack, *args):
    hooks = cli.Hooks()
    hooks.source_factory = lambda cfg: LocalSource(stack["prefix"])
    return cli.main(["-c", str(stack["cfg_path"]), "--insecure-skip-verify", *args], hooks)


@pytest.fixture(autouse=True)
def _allow_insecure(monkeypatch):
    monkeypatch.setenv(cli.ALLOW_INSECURE_ENV, "1")


def test_e2e_upgrade_rollback_gate(stack, capsys):
    lock_path = stack["dir"] / "release.lock"
    probe = stack["probe"]

    # 1. good upgrade r1 -> r2: migrate runs from the new image, lock committed
    assert _cli(stack, "upgrade", "e2e", "r2", "--yes") == exitcodes.OK, capsys.readouterr()
    assert probe.quick() == {"status": "ok", "version": "2.0.0", "db_revision": "rev2"}
    lock = read_lock(lock_path)
    assert lock.current.version == "r2" and lock.previous.version == "r1"

    # 2. r3 is unhealthy (/api/services/ 500, worker ping fails) -> rolled back to r2
    assert _cli(stack, "upgrade", "e2e", "r3", "--yes") == exitcodes.ROLLED_BACK
    assert probe.quick()["version"] == "2.0.0"
    assert read_lock(lock_path).current.version == "r2"

    # 3. r4 carries a destructive migration -> needs approval, nothing recreated
    assert _cli(stack, "upgrade", "e2e", "r4", "--yes") == exitcodes.NEEDS_APPROVAL
    assert probe.quick() == {"status": "ok", "version": "2.0.0", "db_revision": "rev2"}
    assert read_lock(lock_path).current.version == "r2"

    # 4. operator rollback r2 -> r1 (schema stays at rev2; the db is never restored)
    assert _cli(stack, "rollback", "e2e", "--yes") == exitcodes.OK
    assert probe.quick()["version"] == "1.0.0"
    lock = read_lock(lock_path)
    assert lock.current.version == "r1" and lock.previous.version == "r2"

    # 5. status sees no drift; the JSONL log has every run
    capsys.readouterr()
    hooks = cli.Hooks()
    hooks.source_factory = lambda cfg: LocalSource(stack["prefix"])
    assert cli.main(["-c", str(stack["cfg_path"]), "--json", "status", "e2e"], hooks) == exitcodes.OK
    status = json.loads(capsys.readouterr().out)
    assert status["drift"] == [] and {c["Service"] for c in status["containers"]} == {"backend", "worker", "frontend"}
    outcomes = [json.loads(l)["outcome"] for l in (stack["dir"] / "log" / "e2e.jsonl").read_text().splitlines()
                if json.loads(l)["type"] == "outcome"]
    assert outcomes == ["succeeded", "rolled_back", "needs_approval", "succeeded"]
