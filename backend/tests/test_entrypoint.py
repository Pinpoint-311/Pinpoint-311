"""The container entrypoint has to say why it refused to start.

The migrator's four exit codes are deliberately distinct so an operator can tell
what happened without digging -- 1 could not reach the database, 2 a destructive
migration needs a human, 3 the pre-migration backup failed. entrypoint.sh turns
that number into a sentence.

It could not. The script runs under `set -euo pipefail`, and

    python -m app.db.migrate
    status=$?

terminates the script on the first line the moment the migrator exits non-zero.
`status=$?` and the "refusing to start the API" line below it were unreachable
code. The exit code still propagated, so `docker compose ps` was correct and the
log said nothing: an operator saw a container that had stopped, with the one
sentence telling them what to do about it never printed.

Run for real, against a stand-in `python` on PATH, because the bug is in the
shell's control flow and nothing short of running the shell would have caught
it.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "scripts" / "entrypoint.sh"


@pytest.fixture(scope="module")
def entrypoint() -> Path:
    if not ENTRYPOINT.exists():
        pytest.skip("entrypoint.sh not present in this checkout")
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    return ENTRYPOINT


def _run(entrypoint: Path, tmp_path: Path, migrator_exit: int):
    """Run the entrypoint with `python` replaced by a script of our choosing."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    stub = fake_bin / "python"
    stub.write_text(f"#!/bin/sh\nexit {migrator_exit}\n")
    stub.chmod(0o755)

    return subprocess.run(
        ["bash", str(entrypoint), "/bin/echo", "API-STARTED"],
        capture_output=True, text=True, timeout=60,
        env={"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(tmp_path)},
    )


@pytest.mark.parametrize("code,meaning", [
    (1, "could not reach or read the database"),
    (2, "a destructive migration needs a human"),
    (3, "the pre-migration backup failed"),
])
def test_a_refusal_says_so_and_says_which_one(entrypoint, tmp_path, code, meaning):
    result = _run(entrypoint, tmp_path, migrator_exit=code)

    assert result.returncode == code, (
        f"the migrator's exit code {code} ({meaning}) did not propagate"
    )
    combined = result.stdout + result.stderr
    assert "refusing to start the API" in combined, (
        f"the container exited {code} and printed no explanation. This is the "
        f"whole diagnostic an operator gets, and `set -e` was killing the script "
        f"before it ran."
    )
    assert str(code) in combined, (
        "the message does not name the exit code, so it does not say which of "
        "the four reasons it was"
    )
    assert "API-STARTED" not in combined, "the API started anyway"


def test_a_clean_schema_check_starts_the_api(entrypoint, tmp_path):
    """The other direction. A script that refuses to start on success would be
    caught by literally any deployment, but the failure path above was not, so
    both are pinned."""
    result = _run(entrypoint, tmp_path, migrator_exit=0)

    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "API-STARTED" in combined, "the API was not exec'd after a clean check"
    assert "refusing to start" not in combined


def test_the_strict_shell_options_are_still_set(entrypoint):
    """`set -euo pipefail` is not the bug -- the bug was writing `status=$?`
    underneath it. Removing the strictness to fix the diagnostic would trade a
    missing message for silently ignored failures later in the script."""
    source = entrypoint.read_text()
    assert "set -euo pipefail" in source
