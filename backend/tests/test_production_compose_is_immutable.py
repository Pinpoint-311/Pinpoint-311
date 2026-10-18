"""Production runs signed images, not a checkout, and holds no host privileges.

Phase 1 of docs/design/secure-upgrades.md. The production compose file used to
bind-mount ./backend over the image's code, the whole repository at /project,
and the host's Docker socket into the internet-facing backend:

* every stack on a server ran whatever was on disk in one shared checkout, so
  "rebuild the image" changed nothing and one town's `git checkout` changed all
  of them;
* the socket made a compromise of the public web app a compromise of the host.

These are one line each to add back, usually for a good reason in the moment
("I just need to hot-fix this"). The YAML is parsed rather than grepped, so a
comment explaining the removal does not read as the mount itself.

The other half is that the running code reports the release it came from:
the image carries the stamp as env vars and /api/health/quick reads them.
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "docker-compose.yml"
DEV = ROOT / "docker-compose.dev.yml"
APP_SERVICES = ("backend", "worker", "frontend")

if not PROD.exists():  # backend-only checkout (e.g. inside the image)
    pytest.skip("compose files not in this checkout", allow_module_level=True)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _split_volume(entry) -> tuple:
    """(source, target) for a short ("src:dst[:mode]") or long-form volume.

    `${VAR:-default}` holds a colon of its own, so interpolations are masked
    before splitting.
    """
    if isinstance(entry, dict):
        return str(entry.get("source", "")), str(entry.get("target", ""))
    masked = re.sub(r"\$\{[^}]*\}", lambda m: "\0" * len(m.group(0)), entry)
    parts, start = [], 0
    for i, ch in enumerate(masked):
        if ch == ":":
            parts.append(entry[start:i])
            start = i + 1
    parts.append(entry[start:])
    if len(parts) == 1:
        return "", parts[0]
    return parts[0], parts[1]


@pytest.fixture(scope="module")
def prod() -> dict:
    return _load(PROD)


def _volumes(service: dict) -> list:
    return [_split_volume(v) for v in service.get("volumes") or []]


def test_the_volume_parser_handles_interpolated_sources():
    assert _split_volume("${TENANT_CADDY_PATH:-/a/b}:/etc/caddy/tenants") == (
        "${TENANT_CADDY_PATH:-/a/b}", "/etc/caddy/tenants")
    assert _split_volume("./Caddyfile:/etc/caddy/Caddyfile:ro") == ("./Caddyfile", "/etc/caddy/Caddyfile")
    assert _split_volume({"type": "bind", "source": ".", "target": "/project"}) == (".", "/project")


def test_no_service_mounts_the_docker_socket(prod):
    for name, service in prod["services"].items():
        for source, target in _volumes(service):
            assert "docker.sock" not in source and "docker.sock" not in target, (
                f"{name} mounts the Docker socket. That is root on the host for "
                f"whoever compromises {name}; upgrades and restarts belong to the "
                f"host updater (docs/RELEASES.md)."
            )


@pytest.mark.parametrize("name", ["backend", "worker"])
def test_the_backend_source_is_not_mounted_over_the_image(prod, name):
    for source, target in _volumes(prod["services"][name]):
        assert source.rstrip("/") not in ("./backend", "backend"), (
            f"{name} mounts ./backend: the code that runs would be whatever is on "
            f"disk, not the signed image. Use docker-compose.dev.yml for that."
        )
        assert target.rstrip("/") != "/app", f"{name} mounts something over the image's /app"


@pytest.mark.parametrize("name", ["backend", "worker"])
def test_the_repository_is_not_mounted(prod, name):
    for source, target in _volumes(prod["services"][name]):
        assert source.rstrip("/") not in (".", "./"), f"{name} mounts the repository root ({source}:{target})"
        assert target.rstrip("/") != "/project", f"{name} mounts something at /project"


@pytest.mark.parametrize("name", APP_SERVICES)
def test_production_runs_images_not_build_contexts(prod, name):
    service = prod["services"][name]
    assert "build" not in service, f"{name} builds from source in production; that belongs in docker-compose.dev.yml"
    variable = "FRONTEND_IMAGE" if name == "frontend" else "BACKEND_IMAGE"
    assert service.get("image", "").startswith("${" + variable), (
        f"{name} must take its image from {variable}, which release.lock pins by digest"
    )


def test_uploads_live_where_the_app_is_told_they_are(prod):
    """The uploads volume used to be nested under the /project mount. It is its
    own mount now, and UPLOAD_DIR must name the same path or photos go to the
    container's throwaway filesystem."""
    backend = prod["services"]["backend"]
    targets = {source: target for source, target in _volumes(backend)}
    assert "uploads_data" in targets, "the backend lost the uploads volume"
    assert backend["environment"]["UPLOAD_DIR"] == targets["uploads_data"]


@pytest.mark.parametrize("target", ["/backups", "/etc/caddy/tenants", "/etc/caddy/Caddyfile"])
def test_the_mounts_features_need_are_kept(prod, target):
    assert target in {t for _, t in _volumes(prod["services"]["backend"])}


def test_the_caddyfile_is_read_only_to_the_backend(prod):
    entries = [v for v in prod["services"]["backend"]["volumes"] if isinstance(v, str)]
    assert any(v.endswith(":/etc/caddy/Caddyfile:ro") for v in entries)


def test_contributors_keep_a_source_mounted_dev_stack():
    """Removing the source mount from production must not take the edit-and-
    reload loop away from contributors."""
    dev = _load(DEV)["services"]
    assert "build" in dev["backend"] and "build" in dev["frontend"]
    assert "./backend:/app" in dev["backend"]["volumes"]
    assert "--reload" in dev["backend"]["command"]
    # Dev builds must not overwrite the tag production stacks start from.
    for name in APP_SERVICES:
        assert not dev[name]["image"].endswith(":latest")


# ------------------------------------------------------- version from env ----

STAMP_LABELS = (
    "org.pinpoint311.app.version",
    "org.pinpoint311.app.git_sha",
    "org.pinpoint311.app.db_revision",
    "org.pinpoint311.app.min_db_revision",
)


@pytest.mark.parametrize("dockerfile", ["backend/Dockerfile", "frontend/Dockerfile"])
def test_every_image_carries_the_stamp_ci_and_the_orchestrator_use(dockerfile):
    text = (ROOT / dockerfile).read_text()
    for arg in ("PINPOINT_VERSION", "GIT_SHA", "DB_REVISION", "MIN_DB_REVISION"):
        assert f"ARG {arg}" in text, f"{dockerfile} does not accept the {arg} build arg"
    for label in STAMP_LABELS:
        assert label in text, f"{dockerfile} does not write {label}"
    workflow = (ROOT / ".github/workflows/build-publish.yml").read_text()
    for label in STAMP_LABELS:
        assert label in workflow, f"build-publish.yml no longer stamps {label}; the label keys must agree"


def test_the_backend_image_exports_the_stamp_as_env():
    text = (ROOT / "backend/Dockerfile").read_text()
    env_block = text[text.index("\nENV PINPOINT_VERSION"):]
    for var in ("PINPOINT_VERSION", "GIT_SHA", "DB_REVISION", "MIN_DB_REVISION"):
        assert f'{var}="${{{var}}}"' in env_block


@pytest.fixture
def clean_stamp_env(monkeypatch):
    for var in ("APP_VERSION", "PINPOINT_VERSION", "GIT_SHA", "DB_REVISION", "MIN_DB_REVISION"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_the_version_comes_from_the_image_env(clean_stamp_env):
    pytest.importorskip("pydantic_settings")
    from app.core.config import Settings

    clean_stamp_env.setenv("PINPOINT_VERSION", "1.8.0")
    clean_stamp_env.setenv("GIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    clean_stamp_env.setenv("DB_REVISION", "a5c7e9f1b3d4")
    clean_stamp_env.setenv("MIN_DB_REVISION", "c7d9e1f3a5b6")
    settings = Settings(_env_file=None)
    assert settings.app_version == "1.8.0"
    assert settings.git_sha == "0123456789abcdef0123456789abcdef01234567"
    assert settings.build_db_revision == "a5c7e9f1b3d4"
    assert settings.min_db_revision == "c7d9e1f3a5b6"


def test_an_explicit_app_version_still_wins(clean_stamp_env):
    """The orchestrator's compose template sets APP_VERSION."""
    pytest.importorskip("pydantic_settings")
    from app.core.config import Settings

    clean_stamp_env.setenv("PINPOINT_VERSION", "1.8.0")
    clean_stamp_env.setenv("APP_VERSION", "1.8.0-hosted")
    assert Settings(_env_file=None).app_version == "1.8.0-hosted"


def test_an_unstamped_build_reports_null_not_a_made_up_version(clean_stamp_env):
    """A build without the args still has the ENV lines, set to empty strings."""
    pytest.importorskip("pydantic_settings")
    from app.core.config import Settings

    for var in ("PINPOINT_VERSION", "GIT_SHA", "DB_REVISION", "MIN_DB_REVISION"):
        clean_stamp_env.setenv(var, "")
    settings = Settings(_env_file=None)
    assert (settings.app_version, settings.git_sha, settings.build_db_revision, settings.min_db_revision) == (
        None, None, None, None)


def test_health_quick_reports_the_settings_stamp():
    source = (ROOT / "backend/app/api/health.py").read_text()
    quick = source[source.index('@router.get("/quick")'):source.index('@router.get("/version")')]
    assert '"version": settings.app_version' in quick
    assert '"git_sha": settings.git_sha' in quick
    assert "git" not in quick.replace("git_sha", ""), "the health check must not shell out to git"
