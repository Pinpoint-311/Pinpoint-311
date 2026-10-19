"""The one place the updater starts a process.

Arguments are always a list and ``shell=False`` always: nothing the updater
handles (a tag, a digest, a path from config) is ever interpreted by a shell.
Tests replace the ``Runner`` with a fake that records the argv.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from pinpoint_updater.redact import redact

# Variables the compose files interpolate for image pins. They are always passed
# explicitly by the caller, never inherited from whatever environment the
# updater happened to be started in.
_SCRUBBED = (
    "BACKEND_IMAGE", "FRONTEND_IMAGE", "PINPOINT_VERSION", "PINPOINT_APP_VERSION",
)
# ...and nothing inherited may change which project, files or behaviour
# compose uses: every COMPOSE_* variable (COMPOSE_FILE, COMPOSE_PROJECT_NAME,
# COMPOSE_PROFILES, COMPOSE_ENV_FILES, COMPOSE_REMOVE_ORPHANS, ...). DOCKER_HOST
# is kept on purpose: it is how an operator points the updater at a rootless
# daemon or a socket proxy.
_SCRUBBED_PREFIXES = ("COMPOSE_",)


def _scrubbed(name: str) -> bool:
    return name in _SCRUBBED or name.startswith(_SCRUBBED_PREFIXES)


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def tail(self, n: int = 1500) -> str:
        text = ((self.stderr or "") + ("\n" if self.stderr and self.stdout else "") + (self.stdout or "")).strip()
        return redact(text[-n:])

    def describe(self) -> str:
        return redact(" ".join(self.args))


@dataclass
class Runner:
    calls: list[list[str]] = field(default_factory=list)

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        input: Optional[str] = None,
    ) -> CommandResult:
        if isinstance(args, (str, bytes)) or not all(isinstance(a, str) for a in args):
            raise TypeError("Runner.run takes a list of str arguments, never a shell string")
        argv = list(args)
        self.calls.append(argv)
        full_env = {k: v for k, v in os.environ.items() if not _scrubbed(k)}
        if env:
            full_env.update(env)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=full_env,
                cwd=cwd,
                input=input,
                stdin=None if input is not None else subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            return CommandResult(argv, 124, out, f"timed out after {timeout}s", time.monotonic() - started)
        except FileNotFoundError:
            return CommandResult(argv, 127, "", f"{argv[0]}: not found", time.monotonic() - started)
        except OSError as exc:
            return CommandResult(argv, 126, "", f"{argv[0]}: {exc}", time.monotonic() - started)
        return CommandResult(argv, proc.returncode, proc.stdout or "", proc.stderr or "", time.monotonic() - started)
