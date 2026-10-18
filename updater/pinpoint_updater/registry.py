"""Read-only OCI registry client: tag → digest, digest → labels.

Ported from centralizedhosting/orchestrator/upstream.py (resolve_digest,
image_labels, _blob, _blob_manifest, _stamp_from_labels), generalised from a
GHCR-only token flow to the standard ``WWW-Authenticate`` challenge, which is
what ghcr.io, registry.gitlab.com and a self-managed GitLab registry all speak:

* ``GET /v2/`` answers 401 with ``Bearer realm=…,service=…``;
* the realm issues a pull-scoped token, anonymously for public images or for a
  read-only credential sent as HTTP Basic (a GHCR ``read:packages`` PAT, a
  GitLab deploy token with ``read_registry``);
* manifests and blobs are then read with that bearer token.

Properties kept from the orchestrator: the digest comes from the registry's
``Docker-Content-Digest`` header (we verify and deploy the same bytes, never a
tag); manifest requests never follow redirects; tags and digests are checked
against the registry grammar before they go into a URL.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from pinpoint_updater.redact import register_secret

LABEL_PREFIX = "org.pinpoint311.app"

_INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
_MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
ACCEPT = ", ".join(_INDEX_TYPES + _MANIFEST_TYPES)

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_CHALLENGE_PARAM = re.compile(r'(\w+)="([^"]*)"')


class RegistryError(RuntimeError):
    """The registry could not be reached or answered with something unusable."""


def split_image(image: str) -> tuple[str, str]:
    """``ghcr.io/owner/name`` → ``("ghcr.io", "owner/name")`` (orchestrator/upstream.py)."""
    head, _, rest = image.partition("/")
    if not rest or ("." not in head and ":" not in head and head != "localhost"):
        raise RegistryError(f"{image!r} has no registry host")
    return head, rest.split("@")[0].split(":")[0]


def stamp_from_labels(labels: dict[str, str]) -> dict[str, Optional[str]]:
    """Release stamp keys, identical to orchestrator/upstream.py and the labels
    written by .github/workflows/build-publish.yml."""
    return {
        "version": labels.get(f"{LABEL_PREFIX}.version") or labels.get("org.opencontainers.image.version"),
        "git_sha": labels.get(f"{LABEL_PREFIX}.git_sha") or labels.get("org.opencontainers.image.revision"),
        "db_revision": labels.get(f"{LABEL_PREFIX}.db_revision"),
        "min_db_revision": labels.get(f"{LABEL_PREFIX}.min_db_revision"),
    }


class RegistryClient:
    def __init__(
        self,
        *,
        token: Optional[str] = None,
        username: str = "pinpoint-updater",
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.token = (token or "").strip() or None
        register_secret(self.token)
        self.username = username
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "pinpoint-updater"},
        )
        self._auth_cache: dict[tuple[str, str], dict[str, str]] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RegistryClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- auth ---------------------------------------------------------------

    def _basic(self) -> dict[str, str]:
        if not self.token:
            return {}
        raw = base64.b64encode(f"{self.username}:{self.token}".encode()).decode()
        register_secret(raw)
        return {"Authorization": f"Basic {raw}"}

    @staticmethod
    def _scheme(registry: str) -> str:
        host = registry.split(":")[0]
        return "http" if host in ("localhost", "127.0.0.1") else "https"

    def _auth(self, registry: str, repository: str) -> dict[str, str]:
        key = (registry, repository)
        if key in self._auth_cache:
            return self._auth_cache[key]
        try:
            ping = self._client.get(f"{self._scheme(registry)}://{registry}/v2/")
        except httpx.HTTPError as exc:
            raise RegistryError(f"cannot reach registry {registry}: {exc.__class__.__name__}") from None
        headers: dict[str, str] = {}
        if ping.status_code == 401:
            challenge = ping.headers.get("WWW-Authenticate", "")
            scheme, _, params_raw = challenge.partition(" ")
            if scheme.lower() == "basic":
                headers = self._basic()
            elif scheme.lower() == "bearer":
                params = dict(_CHALLENGE_PARAM.findall(params_raw))
                realm = params.get("realm", "")
                parsed = urlparse(realm)
                local = parsed.hostname in ("localhost", "127.0.0.1")
                if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
                    raise RegistryError(f"registry {registry} sent a non-https token realm; refusing")
                query = {"scope": f"repository:{repository}:pull"}
                if params.get("service"):
                    query["service"] = params["service"]
                try:
                    resp = self._client.get(realm, params=query, headers=self._basic())
                except httpx.HTTPError as exc:
                    raise RegistryError(f"token request to {parsed.hostname} failed: {exc.__class__.__name__}") from None
                if resp.status_code != 200:
                    raise RegistryError(
                        f"registry refused a pull token for {repository} ({resp.status_code}). "
                        "For a private registry set release_source.registry_token_file to a read-only token."
                    )
                body = resp.json()
                issued = body.get("token") or body.get("access_token")
                if not issued:
                    raise RegistryError("registry token response contained no token")
                register_secret(issued)
                headers = {"Authorization": f"Bearer {issued}"}
            else:
                raise RegistryError(f"registry {registry} uses an unsupported auth scheme {scheme!r}")
        elif ping.status_code != 200:
            raise RegistryError(f"registry {registry} answered {ping.status_code} on /v2/")
        self._auth_cache[key] = headers
        return headers

    # -- reads ----------------------------------------------------------------

    def _get_manifest(self, registry: str, repository: str, reference: str) -> httpx.Response:
        headers = {**self._auth(registry, repository), "Accept": ACCEPT}
        url = f"{self._scheme(registry)}://{registry}/v2/{repository}/manifests/{reference}"
        try:
            return self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise RegistryError(f"manifest request failed: {exc.__class__.__name__}") from None

    def resolve_digest(self, image: str, tag: str) -> tuple[str, dict[str, Any]]:
        """``image:tag`` → (digest, manifest). orchestrator/upstream.py resolve_digest."""
        if not TAG_RE.match(tag):
            raise RegistryError(f"{tag!r} is not a valid image tag")
        registry, repository = split_image(image)
        resp = self._get_manifest(registry, repository, tag)
        if resp.status_code == 404:
            raise RegistryError(f"{image}:{tag} does not exist in the registry")
        if resp.status_code != 200:
            raise RegistryError(f"registry returned {resp.status_code} for {image}:{tag}")
        digest = resp.headers.get("Docker-Content-Digest", "")
        if not DIGEST_RE.match(digest):
            raise RegistryError(
                f"registry did not return a usable content digest for {image}:{tag}; "
                "refusing to deploy an unpinnable reference"
            )
        # Belt and braces: the header must describe the body we received.
        if hashlib.sha256(resp.content).hexdigest() != digest.split(":", 1)[1]:
            raise RegistryError(f"manifest body for {image}:{tag} does not match its digest header")
        return digest, resp.json()

    def manifest(self, image: str, digest: str) -> dict[str, Any]:
        if not DIGEST_RE.match(digest):
            raise RegistryError(f"{digest!r} is not a sha256 digest")
        registry, repository = split_image(image)
        resp = self._get_manifest(registry, repository, digest)
        if resp.status_code != 200:
            raise RegistryError(f"could not fetch manifest {digest[:19]}… ({resp.status_code})")
        if hashlib.sha256(resp.content).hexdigest() != digest.split(":", 1)[1]:
            raise RegistryError(f"manifest {digest[:19]}… does not match its digest")
        return resp.json()

    def _blob(self, registry: str, repository: str, digest: str) -> dict[str, Any]:
        if not DIGEST_RE.match(digest):
            raise RegistryError(f"{digest!r} is not a sha256 digest")
        headers = self._auth(registry, repository)
        try:
            # Registries hand blobs to a CDN, so this hop follows redirects
            # (httpx drops Authorization on a cross-origin redirect).
            resp = self._client.get(
                f"{self._scheme(registry)}://{registry}/v2/{repository}/blobs/{digest}",
                headers=headers,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise RegistryError(f"blob request failed: {exc.__class__.__name__}") from None
        if resp.status_code != 200:
            raise RegistryError(f"could not fetch blob {digest[:19]}… ({resp.status_code})")
        if hashlib.sha256(resp.content).hexdigest() != digest.split(":", 1)[1]:
            raise RegistryError(f"blob {digest[:19]}… does not match its digest")
        try:
            return json.loads(resp.content)
        except ValueError:
            raise RegistryError(f"blob {digest[:19]}… is not JSON") from None

    def labels(self, image: str, digest: str, manifest: Optional[dict[str, Any]] = None) -> dict[str, str]:
        """OCI config labels of a digest-pinned image. For a multi-arch index,
        descend into the first real platform manifest (orchestrator/upstream.py
        image_labels: every architecture of one build carries the same stamp)."""
        registry, repository = split_image(image)
        if manifest is None:
            manifest = self.manifest(image, digest)
        if manifest.get("mediaType") in _INDEX_TYPES or "manifests" in manifest:
            child = next(
                (m for m in manifest.get("manifests", [])
                 # attestation/signature entries ride in the index too; skip them
                 if (m.get("platform") or {}).get("os") not in (None, "unknown")),
                None,
            )
            if not child:
                raise RegistryError("image index contained no platform manifest")
            manifest = self.manifest(image, child["digest"])
        config_digest = (manifest.get("config") or {}).get("digest")
        if not config_digest:
            raise RegistryError("image manifest has no config descriptor")
        config = self._blob(registry, repository, config_digest)
        labels = (config.get("config") or {}).get("Labels") or {}
        return {str(k): str(v) for k, v in labels.items() if v is not None}
