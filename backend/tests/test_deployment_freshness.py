"""Does the running process know its source has moved on?

Four incidents in one day had this shape and none of them announced it: an API
serving pre-merge code, a proxy on a nine-day-old config, and two clones
emailing an alert that had been fixed two days earlier. Each looked like a
different problem while it lasted.
"""
import os
import time
from pathlib import Path

import pytest

fresh = pytest.importorskip("app.services.deployment_freshness")


def test_a_freshly_loaded_process_is_not_stale():
    stale, _ = fresh.staleness()
    assert stale is False, (
        "this test process just imported its own source, so anything else is a "
        "clock or a walk that is looking at the wrong tree"
    )


def test_source_written_after_load_is_noticed(tmp_path):
    """The whole point. A file touched after boot means the process is behind."""
    (tmp_path / "thing.py").write_text("x = 1\n")
    before = fresh.newest_source_mtime(tmp_path)

    later = time.time() + 10_000
    os.utime(tmp_path / "thing.py", (later, later))
    after = fresh.newest_source_mtime(tmp_path)

    assert after > before
    assert after - fresh.PROCESS_LOADED_AT > fresh.GRACE_SECONDS


def test_pycache_is_not_evidence_of_a_change(tmp_path):
    """__pycache__ is written BY the running process. Counting it would report
    every process as stale the moment it imported anything -- a warning that is
    always on, which is a warning nobody reads."""
    (tmp_path / "thing.py").write_text("x = 1\n")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    compiled = cache / "thing.cpython-311.pyc"
    compiled.write_text("nonsense")
    later = time.time() + 10_000
    os.utime(compiled, (later, later))

    assert fresh.newest_source_mtime(tmp_path) < later


def test_a_rebuild_touching_many_files_is_allowed_a_grace(tmp_path):
    """A deploy rewrites the tree in one go and clocks are not exact. A second
    of drift is not a stale process, or the warning fires on every restart."""
    assert fresh.GRACE_SECONDS >= 30


def test_the_health_report_carries_it():
    """Wired, not merely written -- the failure being prevented is precisely
    that nobody is told."""
    source = Path("app/api/health.py").read_text()
    assert "check_running_code_is_current" in source
    assert '"running_code"' in source
