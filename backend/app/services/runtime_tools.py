"""The external programs this image must provide, checked at runtime.

1.9.0-rc1 shipped without gnupg, and the first anyone knew was the 02:00 backup
failing at "Encrypting backup". One definition of what the image needs, used by:

* `python -m app.cli.selfcheck` -- run by the release gate inside the freshly
  built image, and by pinpoint-updater after every upgrade before it commits;
* the proactive health scan's "Backups can run" check, every 15 minutes;
* tests/test_image_tools.py.

The gpg probe is a real symmetric encrypt/decrypt of a few bytes in a temporary
directory, so "gpg exists but cannot run" (no writable home, broken agent) is
caught too, not just a missing binary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Dict, List

# program -> what needs it. Debian packages are listed in tests/test_image_tools.py.
REQUIRED_TOOLS: Dict[str, str] = {
    "gpg": "encrypting and decrypting backups",
    "pg_dump": "database backups and pre-migration dumps",
    "pg_restore": "backup restore and restore verification",
    "gzip": "pre-migration dumps",
    "tesseract": "on-server text detection in photos",
}

# The subset without which a backup cannot be taken or restored.
BACKUP_TOOLS = ("gpg", "pg_dump", "pg_restore")


def missing_tools(names=None) -> List[str]:
    """Required programs that are not on PATH."""
    return sorted(n for n in (names or REQUIRED_TOOLS) if shutil.which(n) is None)


def gpg_roundtrip(timeout: float = 15.0) -> str:
    """'' if gpg can encrypt and decrypt with a passphrase here, else a reason."""
    if shutil.which("gpg") is None:
        return "gpg is not installed"
    try:
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            plain = os.path.join(home, "probe.txt")
            enc, out = plain + ".gpg", plain + ".out"
            with open(plain, "w") as f:
                f.write("pinpoint-selfcheck")
            base = ["gpg", "--homedir", home, "--batch", "--yes", "--pinentry-mode", "loopback",
                    "--passphrase", "selfcheck-probe"]
            r = subprocess.run(base + ["--symmetric", "--cipher-algo", "AES256", "-o", enc, plain],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                return f"gpg could not encrypt: {(r.stderr or '').strip()[:200]}"
            r = subprocess.run(base + ["--decrypt", "-o", out, enc],
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                return f"gpg could not decrypt: {(r.stderr or '').strip()[:200]}"
            with open(out) as f:
                if f.read() != "pinpoint-selfcheck":
                    return "gpg round trip returned different bytes"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"gpg probe failed: {type(exc).__name__}"
    return ""


def backup_readiness() -> List[str]:
    """Problems that would stop a backup from being taken or restored here."""
    problems = [f"{t} is not installed ({REQUIRED_TOOLS[t]})" for t in missing_tools(BACKUP_TOOLS)]
    if "gpg" not in missing_tools(["gpg"]):
        reason = gpg_roundtrip()
        if reason:
            problems.append(reason)
    return problems
