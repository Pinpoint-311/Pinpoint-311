"""Where releases come from: GitHub or GitLab (cloud or self-managed).

The provider is configuration, never code paths elsewhere: everything past
this module sees ``ReleaseInfo`` (what a human picks from) and
``ResolvedRelease`` (what gets verified and deployed: two digests and the
stamp read from the backend image's own labels).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import quote

import httpx

from pinpoint_updater import __version__
from pinpoint_updater.config import ReleaseSourceConfig, validate_tag
from pinpoint_updater.redact import register_secret
from pinpoint_updater.registry import DIGEST_RE, RegistryClient, RegistryError, stamp_from_labels


class SourceError(RuntimeError):
    pass


@dataclass
class ReleaseInfo:
    tag: str
    name: str
    published_at: Optional[str]
    notes: str
    url: Optional[str]
    prerelease: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedRelease:
    tag: str
    version: str
    backend_image: str
    frontend_image: str
    backend_digest: str
    frontend_digest: str
    git_sha: Optional[str] = None
    db_revision: Optional[str] = None
    min_db_revision: Optional[str] = None
    frontend_version: Optional[str] = None
    stamp_complete: bool = False

    @property
    def backend_ref(self) -> str:
        return f"{self.backend_image}@{self.backend_digest}" if self.backend_digest else self.backend_image

    @property
    def frontend_ref(self) -> str:
        return f"{self.frontend_image}@{self.frontend_digest}" if self.frontend_digest else self.frontend_image

    @property
    def version_mismatch(self) -> Optional[str]:
        if self.frontend_version and self.version and self.frontend_version != self.version:
            return f"frontend reports {self.frontend_version}, backend reports {self.version}"
        return None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["backend_ref"] = self.backend_ref
        d["frontend_ref"] = self.frontend_ref
        return d


class ReleaseSource(ABC):
    provider: str = "?"

    def __init__(
        self,
        config: ReleaseSourceConfig,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        registry: Optional[RegistryClient] = None,
    ):
        self.config = config
        token = config.api_token()
        register_secret(token)
        self._api_token = token
        self._http = httpx.Client(
            timeout=config.timeout,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": f"pinpoint-updater/{__version__}"},
        )
        self.registry = registry or RegistryClient(
            token=config.registry_token(),
            username=config.registry_username,
            timeout=config.timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()
        self.registry.close()

    # -- release listing (provider specific) ---------------------------------

    @abstractmethod
    def _releases_request(self, limit: int) -> tuple[str, dict[str, str], dict[str, Any]]:
        """(url, headers, params) for the provider's releases API."""

    @abstractmethod
    def parse_releases(self, payload: Any) -> list[ReleaseInfo]:
        """Normalise the provider's JSON to ReleaseInfo, newest first."""

    def list_releases(self, limit: int = 20) -> list[ReleaseInfo]:
        url, headers, params = self._releases_request(max(1, min(limit, 100)))
        try:
            resp = self._http.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"{self.provider} releases API unreachable: {exc.__class__.__name__}") from None
        if resp.status_code != 200:
            raise SourceError(f"{self.provider} releases API answered {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError:
            raise SourceError(f"{self.provider} releases API returned non-JSON") from None
        releases = self.parse_releases(payload)
        if not self.config.include_prereleases:
            releases = [r for r in releases if not r.prerelease]
        return releases[:limit]

    # -- tag → digests + stamp (shared) --------------------------------------

    def resolve(self, tag: str) -> ResolvedRelease:
        validate_tag(tag)
        image_tag = self.config.image_tag_for(tag)
        backend = self.config.image_repo("backend")
        frontend = self.config.image_repo("frontend")
        try:
            b_digest, b_manifest = self.registry.resolve_digest(backend, image_tag)
            f_digest, f_manifest = self.registry.resolve_digest(frontend, image_tag)
            b_stamp = stamp_from_labels(self.registry.labels(backend, b_digest, b_manifest))
            f_stamp = stamp_from_labels(self.registry.labels(frontend, f_digest, f_manifest))
        except RegistryError as exc:
            raise SourceError(str(exc)) from None
        return ResolvedRelease(
            tag=tag,
            version=b_stamp["version"] or tag,
            backend_image=backend,
            frontend_image=frontend,
            backend_digest=b_digest,
            frontend_digest=f_digest,
            git_sha=b_stamp["git_sha"],
            db_revision=b_stamp["db_revision"],
            min_db_revision=b_stamp["min_db_revision"],
            frontend_version=f_stamp["version"],
            stamp_complete=bool(b_stamp["version"] and b_stamp["db_revision"]),
        )

    def stamp_for_ref(self, ref: str) -> dict[str, Optional[str]]:
        """Stamp of an already-pinned ``image@sha256:…`` (used by rollback)."""
        image, _, digest = ref.partition("@")
        if not DIGEST_RE.match(digest):
            raise SourceError(f"{ref} is not digest-pinned")
        try:
            return stamp_from_labels(self.registry.labels(image, digest))
        except RegistryError as exc:
            raise SourceError(str(exc)) from None


class GitHubSource(ReleaseSource):
    provider = "github"

    def _releases_request(self, limit: int):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        return f"{self.config.api}/repos/{self.config.project}/releases", headers, {"per_page": str(limit)}

    def parse_releases(self, payload: Any) -> list[ReleaseInfo]:
        if not isinstance(payload, list):
            raise SourceError("GitHub releases API returned an unexpected shape")
        out = []
        for item in payload:
            if not isinstance(item, dict) or item.get("draft"):
                continue
            tag = item.get("tag_name") or ""
            try:
                validate_tag(tag)
            except ValueError:
                continue
            out.append(ReleaseInfo(
                tag=tag,
                name=item.get("name") or tag,
                published_at=item.get("published_at") or item.get("created_at"),
                notes=item.get("body") or "",
                url=item.get("html_url"),
                prerelease=bool(item.get("prerelease")),
            ))
        out.sort(key=lambda r: r.published_at or "", reverse=True)
        return out


class GitLabSource(ReleaseSource):
    provider = "gitlab"

    def _releases_request(self, limit: int):
        headers = {"Accept": "application/json"}
        if self._api_token:
            headers["PRIVATE-TOKEN"] = self._api_token
        project = quote(self.config.project, safe="")
        return (
            f"{self.config.api}/projects/{project}/releases",
            headers,
            {"per_page": str(limit), "order_by": "released_at", "sort": "desc"},
        )

    def parse_releases(self, payload: Any) -> list[ReleaseInfo]:
        if not isinstance(payload, list):
            raise SourceError("GitLab releases API returned an unexpected shape")
        out = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            tag = item.get("tag_name") or ""
            try:
                validate_tag(tag)
            except ValueError:
                continue
            links = item.get("_links") or {}
            out.append(ReleaseInfo(
                tag=tag,
                name=item.get("name") or tag,
                published_at=item.get("released_at") or item.get("created_at"),
                notes=item.get("description") or "",
                url=links.get("self"),
                # GitLab has no prerelease flag; an upcoming (future-dated)
                # release is the closest equivalent.
                prerelease=bool(item.get("upcoming_release")),
            ))
        out.sort(key=lambda r: r.published_at or "", reverse=True)
        return out


def make_source(config: ReleaseSourceConfig, **kwargs) -> ReleaseSource:
    if config.provider == "github":
        return GitHubSource(config, **kwargs)
    if config.provider == "gitlab":
        return GitLabSource(config, **kwargs)
    raise SourceError(f"unknown provider {config.provider!r}")
