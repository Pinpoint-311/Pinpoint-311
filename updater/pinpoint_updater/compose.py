"""docker compose, scoped to exactly one instance.

Every invocation names the project (``-p``), the project directory, every
compose file and both env files explicitly, so nothing depends on the current
directory, a stray ``COMPOSE_*`` variable or a default ``docker-compose.yml``.
That is the fix for problem 4 of the design (restart buttons hitting the wrong
stack): there is no code path here that can reach another project.

Image pins travel as environment variables (``BACKEND_IMAGE`` etc.), which
compose gives precedence over ``--env-file`` values. That lets the updater run
a one-off container from a *candidate* release without touching release.lock,
which is only rewritten once the candidate is healthy.
"""

from __future__ import annotations

from typing import Optional, Sequence

from pinpoint_updater.config import InstanceConfig
from pinpoint_updater.lockfile import ImageSet
from pinpoint_updater.runner import CommandResult, Runner


class Compose:
    def __init__(self, instance: InstanceConfig, runner: Runner):
        self.instance = instance
        self.runner = runner

    def base_args(self) -> list[str]:
        inst = self.instance
        args = ["docker", "compose", "-p", inst.project, "--project-directory", str(inst.dir)]
        for path in inst.compose_paths:
            args += ["-f", str(path)]
        args += ["--env-file", str(inst.env_path), "--env-file", str(inst.lock_path)]
        return args

    def argv(self, *args: str) -> list[str]:
        return [*self.base_args(), *args]

    def run(self, args: Sequence[str], *, images: ImageSet, timeout: float,
            extra_env: Optional[dict[str, str]] = None) -> CommandResult:
        # Runner scrubs inherited COMPOSE_* and image variables.
        env = images.to_env()
        if extra_env:
            env.update(extra_env)
        return self.runner.run(self.argv(*args), timeout=timeout, env=env, cwd=str(self.instance.dir))

    # -- the operations the steps use ------------------------------------

    def pull(self, images: ImageSet, timeout: float) -> CommandResult:
        inst = self.instance
        # --policy missing: a digest is immutable, so an image already on disk is
        # by definition the right one (ported from orchestrator/migrator.py).
        return self.run(["pull", "--quiet", "--policy", "missing", *inst.services], images=images, timeout=timeout)

    def one_off(self, service: str, command: Sequence[str], images: ImageSet, timeout: float,
                env: Optional[dict[str, str]] = None) -> CommandResult:
        """A throwaway container: no deps started, removed afterwards, the image's
        entrypoint replaced by the command's first word so nothing but the named
        command runs."""
        if not command:
            raise ValueError("one_off needs a command")
        args = ["run", "--rm", "--no-deps", "-T"]
        for key, value in (env or {}).items():
            args += ["-e", f"{key}={value}"]
        args += ["--entrypoint", command[0], service, *command[1:]]
        return self.run(args, images=images, timeout=timeout)

    def recreate(self, images: ImageSet, timeout: float = 600) -> CommandResult:
        """``up -d`` for this instance's app services only. Never ``down``, never
        ``--volumes``: Postgres, Redis and the volumes keep running untouched
        (ported from orchestrator/stack.py apply_stack)."""
        return self.run(["up", "-d", "--no-deps", "--no-build", *self.instance.services], images=images, timeout=timeout)

    def restart(self, images: ImageSet, timeout: float = 300) -> CommandResult:
        """``restart`` of this instance's app services only (backend, worker,
        frontend). The console's restart request: Postgres, Redis and any
        shared proxy are never touched, and ``-p`` pins the project."""
        return self.run(["restart", *self.instance.services], images=images, timeout=timeout)

    def exec(self, service: str, command: Sequence[str], images: ImageSet, timeout: float) -> CommandResult:
        return self.run(["exec", "-T", service, *command], images=images, timeout=timeout)

    def ps(self, images: ImageSet, timeout: float = 60) -> CommandResult:
        return self.run(["ps", "--format", "json"], images=images, timeout=timeout)
