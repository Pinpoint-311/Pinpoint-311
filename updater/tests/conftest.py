"""Fakes for docker / cosign / registry / the instance's HTTP endpoints."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pinpoint_updater.config import parse_config  # noqa: E402
from pinpoint_updater.health import ProbeError  # noqa: E402
from pinpoint_updater.lockfile import ImageSet, LockState, write_lock  # noqa: E402
from pinpoint_updater.redact import clear_registered_secrets  # noqa: E402
from pinpoint_updater.runner import CommandResult  # noqa: E402
from pinpoint_updater.sources import ResolvedRelease  # noqa: E402

D_OLD_B = "sha256:" + "1" * 64
D_OLD_F = "sha256:" + "2" * 64
D_NEW_B = "sha256:" + "3" * 64
D_NEW_F = "sha256:" + "4" * 64
REG = "ghcr.io/pinpoint-311"
OLD = ImageSet("v1.7.0", f"{REG}/pinpoint-311-backend@{D_OLD_B}", f"{REG}/pinpoint-311-frontend@{D_OLD_F}")
OLDER = ImageSet("v1.6.0", f"{REG}/pinpoint-311-backend@sha256:{'5' * 64}", f"{REG}/pinpoint-311-frontend@sha256:{'6' * 64}")


@pytest.fixture(autouse=True)
def _clean_secrets():
    clear_registered_secrets()
    yield
    clear_registered_secrets()


def base_config(tmp_path: Path, **instance_overrides) -> dict:
    inst_dir = tmp_path / "pinpoint-town"
    inst = {
        "project": "pinpoint-town",
        "dir": str(inst_dir),
        "compose": ["docker-compose.yml", "docker-compose.town.yml"],
        "env_file": ".env.town",
        "app_url": "http://127.0.0.1:58003",
        "health_timeout": 0,
        "health_interval": 0,
    }
    inst.update(instance_overrides)
    return {
        "release_source": {"provider": "github", "api": "https://api.github.com",
                           "project": "Pinpoint-311/Pinpoint-311", "registry": REG},
        "trust": {"issuer": "https://token.actions.githubusercontent.com",
                  "identity": r"^https://github\.com/Pinpoint-311/Pinpoint-311/\.github/workflows/build-publish\.yml@refs/tags/v"},
        "instances": {"town": inst},
        "log_dir": str(tmp_path / "log"),
        "disk_path": str(tmp_path),
    }


def make_instance_dir(tmp_path: Path, lock: Optional[LockState] = None) -> Path:
    d = tmp_path / "pinpoint-town"
    d.mkdir(exist_ok=True)
    (d / "docker-compose.yml").write_text("services: {}\n")
    (d / "docker-compose.town.yml").write_text("services: {}\n")
    (d / ".env.town").write_text("DB_PASSWORD=x\n")
    write_lock(d / "release.lock", lock or LockState(current=OLD, previous=OLDER))
    return d


@pytest.fixture
def cfg(tmp_path):
    make_instance_dir(tmp_path)
    return parse_config(base_config(tmp_path))


def release(tag="v1.8.0", db="bbb", min_db="aaa", **kw) -> ResolvedRelease:
    defaults = dict(
        tag=tag, version=tag.lstrip("v"), backend_image=f"{REG}/pinpoint-311-backend",
        frontend_image=f"{REG}/pinpoint-311-frontend", backend_digest=D_NEW_B, frontend_digest=D_NEW_F,
        git_sha="abc123", db_revision=db, min_db_revision=min_db, frontend_version=tag.lstrip("v"),
        stamp_complete=True,
    )
    defaults.update(kw)
    return ResolvedRelease(**defaults)


class FakeSource:
    provider = "fake"

    def __init__(self, rel: Optional[ResolvedRelease] = None, stamps: Optional[dict] = None):
        self.rel = rel or release()
        self.stamps = stamps or {}
        self.resolved: list[str] = []

    def resolve(self, tag):
        self.resolved.append(tag)
        return self.rel

    def stamp_for_ref(self, ref):
        return self.stamps.get(ref, {"version": None, "db_revision": None, "min_db_revision": None})

    def list_releases(self, limit=20):
        return []

    def close(self):
        pass


@dataclass
class FakeRunner:
    """Answers argv by rule. Rules: list of (predicate, result-or-callable)."""

    rules: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    envs: list = field(default_factory=list)

    def on(self, pred: Callable[[list[str]], bool], rc: int = 0, stdout: str = "", stderr: str = ""):
        self.rules.insert(0, (pred, (rc, stdout, stderr)))
        return self

    def run(self, args, *, timeout, env=None, cwd=None, input=None):
        assert isinstance(args, list) and all(isinstance(a, str) for a in args), args
        self.calls.append(list(args))
        self.envs.append(dict(env or {}))
        for pred, res in self.rules:
            if pred(args):
                rc, out, err = res(args, env) if callable(res) else res
                return CommandResult(list(args), rc, out, err)
        return CommandResult(list(args), 0, "", "")

    # convenience views
    def compose_calls(self):
        return [(c, e) for c, e in zip(self.calls, self.envs) if c[:2] == ["docker", "compose"]]

    def subcommand_calls(self, sub):
        out = []
        for c, e in self.compose_calls():
            i = c.index("--env-file", c.index("--env-file") + 1) + 2
            if c[i] == sub:
                out.append((c[i:], e))
        return out


def is_cosign(args):
    return args[0] == "cosign"


def is_compose(sub):
    def pred(args):
        if args[:2] != ["docker", "compose"]:
            return False
        i = args.index("--env-file", args.index("--env-file") + 1) + 2
        return args[i] == sub
    return pred


def is_one_off(word):
    def pred(args):
        return is_compose("run")(args) and word in args
    return pred


BACKUP_OK = '{"status": "ok", "backup_name": "db_backup_20261018_120000.sql.gpg", "verified": true, "tables": 42}'


def good_runner() -> FakeRunner:
    r = FakeRunner()
    r.on(is_one_off("app.cli.backup"), 0, "log line\n" + BACKUP_OK + "\n")
    return r


class FakeProbe:
    """quick() answers come from a list (last one repeats); status() from a map."""

    def __init__(self, quicks: list, statuses: Optional[dict] = None):
        self.quicks = list(quicks)
        self.statuses = statuses or {"/": 200, "/api/services/": 200}
        self.quick_calls = 0

    def quick(self):
        self.quick_calls += 1
        value = self.quicks[0] if len(self.quicks) == 1 else self.quicks.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def status(self, path):
        return self.statuses.get(path, 404)

    def close(self):
        pass


def healthy(version, db):
    return {"status": "ok", "version": version, "db_revision": db}


UNREACHABLE = ProbeError("unreachable")
