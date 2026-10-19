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


# ---- the safeguards built on it -------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_tools_matches_the_test_list():
    rt = pytest.importorskip("app.services.runtime_tools")
    assert set(REQUIRED) <= set(rt.REQUIRED_TOOLS)
    assert set(rt.BACKUP_TOOLS) <= set(rt.REQUIRED_TOOLS)


def test_selfcheck_reports_a_missing_tool(monkeypatch):
    rt = pytest.importorskip("app.services.runtime_tools")
    sc = pytest.importorskip("app.cli.selfcheck")
    monkeypatch.setattr(rt.shutil, "which", lambda name: None if name == "gpg" else f"/usr/bin/{name}")
    out = sc.run(tools_only=True)
    assert out["ok"] is False and any("gpg is not installed" in p for p in out["problems"])
    assert sc.main(["--tools-only"]) == 1


def test_selfcheck_passes_when_everything_is_there(monkeypatch):
    rt = pytest.importorskip("app.services.runtime_tools")
    sc = pytest.importorskip("app.cli.selfcheck")
    monkeypatch.setattr(rt.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(rt, "gpg_roundtrip", lambda timeout=15.0: "")
    assert sc.run(tools_only=True) == {"ok": True, "problems": [], "tools_only": True}


def test_gpg_roundtrip_really_encrypts_when_gpg_exists():
    rt = pytest.importorskip("app.services.runtime_tools")
    if shutil.which("gpg") is None:
        pytest.skip("gpg not installed here")
    assert rt.gpg_roundtrip() == ""


def test_proactive_health_flags_backups_that_cannot_run(monkeypatch):
    import asyncio
    ph = pytest.importorskip("app.services.proactive_health")
    bs = pytest.importorskip("app.services.backup_service")
    rt = pytest.importorskip("app.services.runtime_tools")

    async def configured():
        return {"BACKUP_S3_BUCKET": "b"}
    monkeypatch.setattr(bs, "get_backup_config", configured)
    monkeypatch.setattr(rt, "backup_readiness", lambda: ["gpg is not installed (encrypting and decrypting backups)"])
    out = asyncio.run(ph._backup_tools_check())
    assert out["key"] == "backup_tools" and out["status"] == "critical"
    assert "gpg is not installed" in out["message"]

    monkeypatch.setattr(rt, "backup_readiness", lambda: [])
    assert asyncio.run(ph._backup_tools_check())["status"] == "ok"

    async def unconfigured():
        return None
    monkeypatch.setattr(bs, "get_backup_config", unconfigured)
    assert asyncio.run(ph._backup_tools_check())["status"] == "ok"


def test_proactive_scan_includes_the_backup_tools_check():
    import inspect
    ph = pytest.importorskip("app.services.proactive_health")
    assert "_backup_tools_check()" in inspect.getsource(ph.collect_checks)


def test_release_gates_run_the_selfcheck_in_the_built_image():
    gh = (ROOT / ".github/workflows/build-publish.yml").read_text()
    gl = (ROOT / ".gitlab-ci.yml").read_text()
    for text in (gh, gl):
        assert "app.cli.selfcheck --tools-only" in text
    # GitHub: before the push step, so a failing image is never published.
    assert gh.index("app.cli.selfcheck") < gh.index("- name: Build and push")
