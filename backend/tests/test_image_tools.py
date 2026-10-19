"""The production image must ship the external programs the app shells out to.

1.9.0-rc1 dropped gnupg along with the Docker CLI's apt-key setup; the backend
then could not encrypt a single backup (backup_service runs `gpg`), and the
first anyone heard was the nightly failure email.
"""

import re
import shutil
from pathlib import Path

import pytest

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"

# program the code runs -> Debian package that provides it
REQUIRED = {
    "gpg": "gnupg",              # backup encrypt/decrypt (backup_service.py)
    "pg_dump": "postgresql-client",  # backups, pre-migration dumps
    "pg_restore": "postgresql-client",  # restore, restore verification
    "tesseract": "tesseract-ocr",  # on-server OCR (image_redaction)
}


def _apt_packages() -> set:
    text = DOCKERFILE.read_text()
    block = re.search(r"apt-get install -y(.*?)&& rm -rf", text, re.S)
    assert block, "no apt-get install block found"
    return {tok for tok in re.split(r"[\s\\]+", block.group(1))
            if tok and not tok.startswith("#") and re.fullmatch(r"[a-z0-9.+-]+", tok)}


def test_dockerfile_installs_every_required_tool():
    packages = _apt_packages()
    missing = sorted({pkg for pkg in REQUIRED.values() if pkg not in packages})
    assert not missing, f"Dockerfile no longer installs: {missing}"


def test_the_backup_service_still_uses_gpg():
    src = (Path(__file__).resolve().parents[1] / "app/services/backup_service.py").read_text()
    assert '"gpg"' in src  # if this changes, update REQUIRED


def test_tools_present_when_running_in_the_image():
    # Only meaningful inside the built image (where tests run in CI's image job
    # and in the prod-image test command); skipped on a bare host.
    if not Path("/.dockerenv").exists():
        pytest.skip("not running inside a container image")
    # gzip (pre-migration dumps, app/db/migrate.py) comes with the base image
    # rather than the apt block, so it is checked here only.
    absent = sorted(tool for tool in [*REQUIRED, "gzip"] if shutil.which(tool) is None)
    assert not absent, f"missing from the image: {absent}"
