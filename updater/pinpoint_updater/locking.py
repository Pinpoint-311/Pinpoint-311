"""One run per instance at a time.

An ``flock`` on a file in the instance directory. Non-blocking: a second run
fails fast with a clear message instead of queueing behind an upgrade that may
take an hour. The kernel releases the lock if the process dies, so a crashed
run never leaves a stale lock behind.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

LOCK_NAME = ".pinpoint-updater.lock"


class InstanceLocked(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, directory: Path, instance: str):
        self.path = Path(directory) / LOCK_NAME
        self.instance = instance
        self._fd: int | None = None

    def acquire(self) -> "InstanceLock":
        # O_NOFOLLOW: whoever owns the instance directory must not be able to
        # aim this at another file (another instance's release.lock, say) and
        # have the updater truncate it.
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o640)
        except OSError as exc:
            if os.path.islink(self.path):
                raise InstanceLocked(f"{self.path} is a symlink; refusing to use it as the instance lock") from None
            raise exc
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise InstanceLocked(
                f"another pinpoint-updater run holds the lock for {self.instance} ({self.path})"
            ) from None
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return self

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "InstanceLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()

    def available(self) -> bool:
        """Probe without holding: True when no other run has it."""
        try:
            self.acquire()
        except InstanceLocked:
            return False
        self.release()
        return True
