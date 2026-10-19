"""release.lock: the images an instance runs, written only by the updater.

```dotenv
PINPOINT_VERSION=v1.8.0
BACKEND_IMAGE=ghcr.io/pinpoint-311/pinpoint-311-backend@sha256:…
FRONTEND_IMAGE=ghcr.io/pinpoint-311/pinpoint-311-frontend@sha256:…
PREVIOUS_PINPOINT_VERSION=v1.7.2
PREVIOUS_BACKEND_IMAGE=…
PREVIOUS_FRONTEND_IMAGE=…
```

``PINPOINT_APP_VERSION`` (and its ``PREVIOUS_`` twin), when present, is the
version the image's own label stamps and ``/api/health/quick`` reports. It can
differ from the release tag (``v1.8.0`` vs ``1.8.0``, or any tag scheme), and a
rollback's health check needs the one the app will actually report.

Compose reads it as an ``--env-file``; the ``PREVIOUS_*`` keys are ignored by
compose and are what ``pinpoint-updater rollback`` returns to. Rewrites are
atomic (temp file in the same directory, fsync, rename, fsync the directory),
so a crash or full disk leaves either the old file or the new one, never half.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

KEYS = ("PINPOINT_VERSION", "BACKEND_IMAGE", "FRONTEND_IMAGE")
OPTIONAL = ("PINPOINT_APP_VERSION",)
PREVIOUS = "PREVIOUS_"
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:/@+-]*$")


class LockFileError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageSet:
    version: str
    backend: str
    frontend: str
    app_version: Optional[str] = None

    def to_env(self) -> dict[str, str]:
        env = {"PINPOINT_VERSION": self.version, "BACKEND_IMAGE": self.backend, "FRONTEND_IMAGE": self.frontend}
        if self.app_version:
            env["PINPOINT_APP_VERSION"] = self.app_version
        return env

    @property
    def expected_version(self) -> str:
        """What /api/health/quick should report when these images run."""
        return self.app_version or self.version

    def same_images(self, other: "ImageSet") -> bool:
        return self.backend == other.backend and self.frontend == other.frontend

    @property
    def digest_pinned(self) -> bool:
        return "@sha256:" in self.backend and "@sha256:" in self.frontend

    def as_dict(self) -> dict[str, str]:
        return {"version": self.version, "app_version": self.app_version,
                "backend": self.backend, "frontend": self.frontend}


@dataclass
class LockState:
    current: ImageSet
    previous: Optional[ImageSet] = None
    extra: dict[str, str] = field(default_factory=dict)


def _parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = _LINE.match(raw)
        if not m:
            raise LockFileError(f"unparseable line in release.lock: {raw[:80]!r}")
        key, value = m.group(1), m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def read_lock(path: Path) -> LockState:
    try:
        values = _parse(Path(path).read_text())
    except FileNotFoundError:
        raise LockFileError(f"{path} does not exist") from None
    except OSError as exc:
        raise LockFileError(f"cannot read {path}: {exc.strerror}") from None
    missing = [k for k in KEYS if not values.get(k)]
    if missing:
        raise LockFileError(f"{path} is missing {', '.join(missing)}")
    current = ImageSet(values["PINPOINT_VERSION"], values["BACKEND_IMAGE"], values["FRONTEND_IMAGE"],
                       values.get("PINPOINT_APP_VERSION") or None)
    previous = None
    if all(values.get(PREVIOUS + k) for k in KEYS):
        previous = ImageSet(
            values[PREVIOUS + "PINPOINT_VERSION"], values[PREVIOUS + "BACKEND_IMAGE"], values[PREVIOUS + "FRONTEND_IMAGE"],
            values.get(PREVIOUS + "PINPOINT_APP_VERSION") or None,
        )
    known = KEYS + OPTIONAL
    extra = {k: v for k, v in values.items()
             if k not in known and not (k.startswith(PREVIOUS) and k[len(PREVIOUS):] in known)}
    return LockState(current, previous, extra)


def render_lock(state: LockState, header: str = "") -> str:
    lines = [
        "# Written by pinpoint-updater. Do not edit by hand: the updater rewrites it",
        "# atomically after a verified, health-checked upgrade or rollback.",
    ]
    if header:
        lines.append(f"# {header}")
    pairs = list(state.current.to_env().items())
    if state.previous:
        pairs += [(PREVIOUS + k, v) for k, v in state.previous.to_env().items()]
    pairs += sorted(state.extra.items())
    for key, value in pairs:
        if not _SAFE_VALUE.match(value):
            raise LockFileError(f"refusing to write unsafe value for {key}: {value[:60]!r}")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def write_lock(path: Path, state: LockState, header: str = "") -> None:
    """Atomically replace ``path`` with ``state``."""
    path = Path(path)
    content = render_lock(state, header)
    directory = path.parent
    try:
        mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        mode = 0o640
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
