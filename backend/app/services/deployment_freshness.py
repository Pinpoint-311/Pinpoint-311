"""Whether the code running is the code on disk.

Four separate incidents in one day, all the same shape: the source was updated
and the process kept serving what it had loaded at boot.

  * the API served pre-merge code because it was restarted before the merge, and
    reported "[migrate] schema is up to date" from a tree three revisions old
  * Caddy ran a nine-day-old config because git replaces a file rather than
    writing through it, so the bind mount kept pointing at the old inode
  * both demo clones emailed administrators a false alert for two days after the
    bug was fixed, from Python loaded before the fix existed

Every one was found by accident, and every one looked like a different problem
while it lasted -- a stale alert, a routing failure, a migration that had
supposedly already run. What they have in common is that nothing anywhere
compared the running process with the files beside it.

Deliberately mtime and not a git revision. This runs where the source is a bind
mount, `.git` may not be mounted at all, and the question is not "which commit
is checked out" but "has anything changed since I read it" -- which is what a
timestamp answers and a revision does not, since an uncommitted edit moves no
SHA.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional, Tuple

# A rebuild rewrites a lot of files at once and the clock is not exact; a
# process is not "stale" because a file landed a second after it booted.
GRACE_SECONDS = 90

_APP_ROOT = Path(__file__).resolve().parent.parent


def newest_source_mtime(root: Optional[Path] = None) -> float:
    """The most recent mtime of any .py under the application tree.

    Only .py: __pycache__ is written BY the running process, so counting it
    would report every process as stale the moment it imported anything.
    """
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(root or _APP_ROOT):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            try:
                newest = max(newest, os.stat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return newest


# Captured at import, which is as close to "when this process loaded its code"
# as anything available.
PROCESS_LOADED_AT = time.time()
SOURCE_AT_LOAD = newest_source_mtime()


def staleness(now: Optional[float] = None) -> Tuple[bool, float]:
    """(is stale, seconds by which the source is newer than this process)."""
    current = newest_source_mtime()
    drift = current - PROCESS_LOADED_AT
    return (drift > GRACE_SECONDS, drift)
