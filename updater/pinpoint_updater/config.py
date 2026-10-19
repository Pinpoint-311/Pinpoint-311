"""instances.yml: what the updater manages and whom it trusts.

Validated strictly (unknown keys are errors) because a typo in a trust policy
or a compose path should stop the updater at load time, not halfway through an
upgrade.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from pinpoint_updater.redact import register_secret

INSTANCE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# Compose's own project-name grammar.
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SERVICE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
# Release tags land in registry URL paths; keep them to the registry's grammar.
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")

DEFAULT_CONFIG_PATH = Path("/etc/pinpoint-updater/instances.yml")


class ConfigError(ValueError):
    """instances.yml is missing, unreadable or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _read_secret_file(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        value = Path(path).read_text().strip()
    except OSError as exc:
        raise ConfigError(f"cannot read credential file {path}: {exc.strerror}") from exc
    register_secret(value)
    return value or None


class ReleaseSourceConfig(_Strict):
    provider: Literal["github", "gitlab"]
    # https://api.github.com, https://gitlab.com/api/v4, https://gitlab.example.gov/api/v4
    api: str
    # owner/repo on GitHub; group/subgroup/project path (or numeric id) on GitLab
    project: str
    # registry host + namespace: ghcr.io/pinpoint-311, registry.gitlab.com/group/project
    registry: str
    backend_image: str = "pinpoint-311-backend"
    frontend_image: str = "pinpoint-311-frontend"
    # How a release tag maps to an image tag. "version" strips a leading "v"
    # (docker/metadata-action's semver pattern publishes v1.8.0 as 1.8.0);
    # "tag" uses the release tag verbatim.
    image_tag: Literal["version", "tag"] = "version"
    include_prereleases: bool = False
    # Optional read-only credentials, each in its own file (never inline).
    api_token_file: Optional[Path] = None
    registry_token_file: Optional[Path] = None
    # GitLab deploy tokens authenticate as their own username; GHCR ignores it.
    registry_username: str = "pinpoint-updater"
    timeout: float = 30.0

    @field_validator("api")
    @classmethod
    def _https_api(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and _is_loopback_host(parsed.hostname)):
            raise ValueError("release_source.api must be an https:// URL")
        return v.rstrip("/")

    @field_validator("registry")
    @classmethod
    def _registry_host(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if "://" in v:
            raise ValueError("release_source.registry is host/namespace, without a scheme")
        head, _, _rest = v.partition("/")
        if "." not in head and ":" not in head and head != "localhost":
            # Ported from orchestrator/upstream.py split_image: a reference with no
            # registry host means Docker Hub, which nobody configured.
            raise ValueError("release_source.registry must start with a registry host, e.g. ghcr.io/owner")
        return v

    @field_validator("backend_image", "frontend_image")
    @classmethod
    def _image_name(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9]+(?:[._/-][a-z0-9]+)*$", v):
            raise ValueError(f"{v!r} is not a valid image repository name")
        return v

    def api_token(self) -> Optional[str]:
        return _read_secret_file(self.api_token_file)

    def registry_token(self) -> Optional[str]:
        return _read_secret_file(self.registry_token_file)

    def image_repo(self, which: Literal["backend", "frontend"]) -> str:
        name = self.backend_image if which == "backend" else self.frontend_image
        return f"{self.registry}/{name}"

    def image_tag_for(self, release_tag: str) -> str:
        if self.image_tag == "version" and release_tag[:1] in ("v", "V") and release_tag[1:2].isdigit():
            return release_tag[1:]
        return release_tag


class TrustConfig(_Strict):
    """Whom a signature has to come from.

    Keyless (Fulcio/Rekor): ``issuer`` + ``identity`` (a regexp over the signing
    certificate's SAN). Key-based: ``key`` (a path, KMS URI or anything cosign's
    ``--key`` accepts). Exactly one of the two.
    """

    issuer: Optional[str] = None
    identity: Optional[str] = None
    key: Optional[str] = None
    attestation_types: list[str] = Field(default_factory=lambda: ["spdxjson"])
    cosign_binary: str = "cosign"

    @model_validator(mode="after")
    def _one_policy(self) -> "TrustConfig":
        if self.key:
            if self.issuer or self.identity:
                raise ValueError("trust: set either key, or issuer + identity, not both")
            return self
        # Ported from orchestrator/supply_chain.py: keyless verification needs
        # both trust anchors. Either alone accepts signers nobody chose.
        if not (self.issuer and self.identity):
            raise ValueError(
                "trust: keyless verification needs both issuer and identity "
                "(or set key for key-based verification)"
            )
        if not self.identity.startswith("^"):
            # An unanchored regexp matches any identity that merely CONTAINS the
            # expected workflow URL, e.g. one from a repository named after it.
            raise ValueError("trust.identity must be an anchored regexp starting with '^'")
        try:
            re.compile(self.identity)
        except re.error as exc:
            raise ValueError(f"trust.identity is not a valid regexp: {exc}") from exc
        if not self.issuer.startswith("https://"):
            raise ValueError("trust.issuer must be an https:// URL")
        return self

    @field_validator("attestation_types")
    @classmethod
    def _types(cls, v: list[str]) -> list[str]:
        for t in v:
            if not re.match(r"^[a-z0-9]+$", t) and not t.startswith("https://"):
                raise ValueError(f"unknown attestation type {t!r}")
        return v

    @property
    def mode(self) -> str:
        return "key" if self.key else "keyless"


class BackupConfig(_Strict):
    # verify: create + restore into a scratch database + compare table counts
    # create: create and upload only
    # off:    no backup (recorded as a warning in every report)
    mode: Literal["verify", "create", "off"] = "verify"
    command: list[str] = Field(default_factory=lambda: ["python", "-m", "app.cli.backup"])
    timeout: int = 3600


class InstanceConfig(_Strict):
    project: str
    dir: Path
    compose: list[str] = Field(min_length=1)
    env_file: str
    lock_file: str = "release.lock"
    # Loopback URL of the instance's web entry (frontend, which proxies /api).
    app_url: str
    # The console request channel (Phase 3). With token_file set, `poll` claims
    # and runs requests admins filed in the console and publishes the release
    # list there. The token comes from Admin Console -> Version Control ->
    # Updater connection; the file holds only the token (mode 0600).
    token_file: Optional[str] = None
    # Loopback URL of the instance's BACKEND (its BACKEND_PORT), for
    # /api/internal/updater/*. Caddy answers 404 for that prefix, so this must
    # not go through Caddy. Defaults to app_url.
    api_url: Optional[str] = None
    # Host-side floor for the console's two-person rule. true: upgrades and
    # rollbacks always need an approver other than the requester, even if an
    # admin turns the setting off in the console. Unset: follow the console.
    require_two_person_approval: Optional[bool] = None
    backup: BackupConfig = Field(default_factory=BackupConfig)
    require_attestations: bool = False

    backend_service: str = "backend"
    worker_service: str = "worker"
    frontend_service: str = "frontend"
    # Run inside the worker container; exit 0 means the worker answered.
    # [] disables the heartbeat check.
    # Run inside the new backend and worker after an upgrade, before release.lock
    # is committed (app/cli/selfcheck.py): required programs, a real gpg round
    # trip, the backup dir and model files. Empty list disables it. 1.9.0-rc1
    # shipped without gpg and an upgrade would have committed it.
    selfcheck: list[str] = Field(default_factory=lambda: ["python", "-m", "app.cli.selfcheck"])
    worker_ping: list[str] = Field(
        default_factory=lambda: ["celery", "-A", "app.core.celery_app", "inspect", "ping", "--timeout", "10"]
    )
    migrate_command: list[str] = Field(default_factory=lambda: ["python", "-m", "app.db.migrate"])
    health_timeout: int = 120
    health_interval: float = 5.0
    min_free_gb: float = 5.0
    migrate_timeout: int = 1800
    pull_timeout: int = 1800

    @field_validator("project")
    @classmethod
    def _project(cls, v: str) -> str:
        if not PROJECT_RE.match(v):
            raise ValueError("project must be a compose project name: lowercase letters, digits, '-', '_'")
        return v

    @field_validator("dir")
    @classmethod
    def _abs_dir(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError("dir must be an absolute path")
        return v

    @field_validator("app_url", "api_url")
    @classmethod
    def _loopback(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not _is_loopback_host(parsed.hostname):
            raise ValueError("app_url and api_url must be loopback URLs (http://127.0.0.1:<port>)")
        return v.rstrip("/")

    @field_validator("backend_service", "worker_service", "frontend_service")
    @classmethod
    def _service(cls, v: str) -> str:
        if not SERVICE_RE.match(v):
            raise ValueError(f"{v!r} is not a compose service name")
        return v

    def path(self, p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else self.dir / p

    @property
    def compose_paths(self) -> list[Path]:
        return [self.path(c) for c in self.compose]

    @property
    def env_path(self) -> Path:
        return self.path(self.env_file)

    @property
    def lock_path(self) -> Path:
        return self.path(self.lock_file)

    @property
    def api_base(self) -> str:
        return self.api_url or self.app_url

    @property
    def token_path(self) -> Optional[Path]:
        return self.path(self.token_file) if self.token_file else None

    def updater_token(self) -> Optional[str]:
        """The console token, registered for redaction as it is read."""
        return _read_secret_file(self.token_path)

    @property
    def services(self) -> list[str]:
        return [self.backend_service, self.worker_service, self.frontend_service]


class UpdaterConfig(_Strict):
    release_source: ReleaseSourceConfig
    trust: TrustConfig
    instances: dict[str, InstanceConfig]
    log_dir: Path = Path("/var/log/pinpoint-updater")
    # Filesystem whose free space the preflight checks (Docker's data root).
    disk_path: Path = Path("/var/lib/docker")
    # How often `poll` rebuilds the release list it publishes to a console
    # (list, resolve, cosign verify). Between rebuilds it republishes the
    # cached list with the schema check redone locally, so a one-minute timer
    # costs one loopback health call, not registry and cosign traffic. A run
    # that changed the instance forces a rebuild.
    release_refresh_seconds: int = Field(default=3600, ge=60)

    @field_validator("instances")
    @classmethod
    def _names(cls, v: dict[str, InstanceConfig]) -> dict[str, InstanceConfig]:
        if not v:
            raise ValueError("instances: at least one instance is required")
        for name in v:
            if not INSTANCE_NAME_RE.match(name):
                raise ValueError(f"instance name {name!r}: lowercase letters, digits, '-', '_'")
        projects = [i.project for i in v.values()]
        if len(set(projects)) != len(projects):
            raise ValueError("two instances name the same compose project")
        return v

    def instance(self, name: str) -> InstanceConfig:
        try:
            return self.instances[name]
        except KeyError:
            raise ConfigError(f"unknown instance {name!r}; configured: {', '.join(sorted(self.instances))}")


def parse_config(data: object) -> UpdaterConfig:
    try:
        return UpdaterConfig.model_validate(data)
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            lines.append(f"  {loc}: {err['msg']}")
        raise ConfigError("invalid instances.yml:\n" + "\n".join(lines)) from None


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> UpdaterConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"config file {path} does not exist") from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    return parse_config(raw)


def validate_tag(tag: str) -> str:
    if not TAG_RE.match(tag or ""):
        raise ConfigError(f"{tag!r} is not a valid release tag")
    return tag
