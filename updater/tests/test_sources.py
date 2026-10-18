"""GitHub / GitLab release parsing and OCI registry resolution, over httpx.MockTransport."""

import base64
import hashlib
import json

import httpx
import pytest

from pinpoint_updater.config import ReleaseSourceConfig
from pinpoint_updater.registry import RegistryClient, RegistryError
from pinpoint_updater.sources import GitHubSource, GitLabSource, SourceError

GITHUB_RELEASES = [
    {"tag_name": "v1.8.0", "name": "1.8.0", "published_at": "2026-10-10T12:00:00Z", "body": "## Fixes\n- a",
     "html_url": "https://github.com/Pinpoint-311/Pinpoint-311/releases/tag/v1.8.0", "draft": False, "prerelease": False},
    {"tag_name": "v1.9.0-rc1", "name": "rc", "published_at": "2026-10-15T12:00:00Z", "body": "", "draft": False,
     "prerelease": True},
    {"tag_name": "v2.0.0", "name": "draft", "published_at": None, "draft": True, "prerelease": False},
    {"tag_name": "v1.7.0", "name": "1.7.0", "published_at": "2026-09-01T12:00:00Z", "body": "old", "draft": False,
     "prerelease": False},
    {"tag_name": "../../etc", "name": "evil", "published_at": "2026-10-16T00:00:00Z", "draft": False},
]

GITLAB_RELEASES = [
    {"tag_name": "v1.8.0", "name": "Pinpoint 1.8.0", "released_at": "2026-10-10T12:00:00.000Z",
     "description": "Notes", "_links": {"self": "https://gitlab.example.gov/city/pinpoint-311/-/releases/v1.8.0"},
     "upcoming_release": False},
    {"tag_name": "v1.9.0", "name": "future", "released_at": "2027-01-01T00:00:00.000Z", "description": "",
     "upcoming_release": True},
]


def gh_config(**kw):
    return ReleaseSourceConfig(provider="github", api="https://api.github.com", project="Pinpoint-311/Pinpoint-311",
                               registry="ghcr.io/pinpoint-311", **kw)


def gl_config(**kw):
    return ReleaseSourceConfig(provider="gitlab", api="https://gitlab.example.gov/api/v4", project="city/pinpoint-311",
                               registry="registry.example.gov/city/pinpoint-311", **kw)


def test_github_release_parsing_skips_drafts_prereleases_and_bad_tags():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=GITHUB_RELEASES)

    src = GitHubSource(gh_config(), transport=httpx.MockTransport(handler))
    rels = src.list_releases(10)
    assert [r.tag for r in rels] == ["v1.8.0", "v1.7.0"]
    assert rels[0].notes.startswith("## Fixes") and rels[0].url.endswith("v1.8.0")
    assert seen["url"].startswith("https://api.github.com/repos/Pinpoint-311/Pinpoint-311/releases")
    assert seen["auth"] is None


def test_github_includes_prereleases_when_asked_and_sends_token(tmp_path):
    (tmp_path / "t").write_text("ghp_" + "a" * 36 + "\n")
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=GITHUB_RELEASES)

    src = GitHubSource(gh_config(include_prereleases=True, api_token_file=tmp_path / "t"),
                       transport=httpx.MockTransport(handler))
    assert [r.tag for r in src.list_releases()] == ["v1.9.0-rc1", "v1.8.0", "v1.7.0"]
    assert seen["auth"] == "Bearer ghp_" + "a" * 36


def test_gitlab_release_parsing_and_url_encoded_project(tmp_path):
    (tmp_path / "t").write_text("glpat-" + "b" * 20)
    seen = {}

    def handler(request):
        seen["path"] = request.url.raw_path.decode()
        seen["token"] = request.headers.get("PRIVATE-TOKEN")
        return httpx.Response(200, json=GITLAB_RELEASES)

    src = GitLabSource(gl_config(api_token_file=tmp_path / "t"), transport=httpx.MockTransport(handler))
    rels = src.list_releases()
    assert [r.tag for r in rels] == ["v1.8.0"]
    assert rels[0].name == "Pinpoint 1.8.0" and rels[0].published_at.startswith("2026-10-10")
    assert seen["path"].startswith("/api/v4/projects/city%2Fpinpoint-311/releases")
    assert seen["token"] == "glpat-" + "b" * 20


def test_api_errors_are_source_errors():
    src = GitHubSource(gh_config(), transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})))
    with pytest.raises(SourceError, match="403"):
        src.list_releases()


# -- registry ------------------------------------------------------------------------

def _blob(obj):
    raw = json.dumps(obj).encode()
    return raw, "sha256:" + hashlib.sha256(raw).hexdigest()


def fake_registry(host, realm, service, labels_by_repo, *, require_basic=None, tamper=False):
    """A minimal OCI distribution API with a bearer challenge."""
    store = {}  # (repo, ref) -> (bytes, media type)
    for repo, labels in labels_by_repo.items():
        config_raw, config_d = _blob({"config": {"Labels": labels}})
        store[(repo, config_d)] = (config_raw, "application/vnd.oci.image.config.v1+json")
        manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {"digest": config_d, "mediaType": "application/vnd.oci.image.config.v1+json"}}
        m_raw, m_d = _blob(manifest)
        store[(repo, m_d)] = (m_raw, manifest["mediaType"])
        index = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
                 "manifests": [{"digest": "sha256:" + "f" * 64, "platform": {"os": "unknown"}},
                               {"digest": m_d, "platform": {"os": "linux", "architecture": "amd64"}}]}
        i_raw, i_d = _blob(index)
        store[(repo, i_d)] = (i_raw, index["mediaType"])
        store[(repo, "1.8.0")] = (i_raw, index["mediaType"])
    issued = "registry-bearer-" + "z" * 20
    log = []

    def handler(request):
        url = request.url
        log.append(str(url))
        if url.host == host and url.path == "/v2/":
            return httpx.Response(401, headers={"WWW-Authenticate": f'Bearer realm="{realm}",service="{service}"'})
        if str(url).startswith(realm):
            if require_basic and request.headers.get("Authorization") != require_basic:
                return httpx.Response(401)
            assert url.params["scope"].endswith(":pull") and url.params["service"] == service
            return httpx.Response(200, json={"token": issued})
        if request.headers.get("Authorization") != f"Bearer {issued}":
            return httpx.Response(401)
        parts = url.path.split("/")
        kind = parts[-2]
        repo = "/".join(parts[2:-2])
        ref = parts[-1]
        if (repo, ref) not in store:
            return httpx.Response(404)
        raw, mt = store[(repo, ref)]
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if tamper and kind == "manifests":
            digest = "sha256:" + "0" * 64
        return httpx.Response(200, content=raw, headers={"Content-Type": mt, "Docker-Content-Digest": digest})

    return handler, log


LABELS = {
    "org.pinpoint311.app.version": "1.8.0",
    "org.pinpoint311.app.git_sha": "abc123",
    "org.pinpoint311.app.db_revision": "d2e4f6a8b0c1",
    "org.pinpoint311.app.min_db_revision": "c7d9e1f3a5b6",
}


def test_resolve_ghcr_anonymous_reads_digests_and_labels():
    handler, log = fake_registry(
        "ghcr.io", "https://ghcr.io/token", "ghcr.io",
        {"pinpoint-311/pinpoint-311-backend": LABELS,
         "pinpoint-311/pinpoint-311-frontend": {"org.pinpoint311.app.version": "1.8.0"}})
    src = GitHubSource(gh_config(), transport=httpx.MockTransport(handler))
    rel = src.resolve("v1.8.0")
    assert rel.version == "1.8.0" and rel.git_sha == "abc123"
    assert rel.db_revision == "d2e4f6a8b0c1" and rel.min_db_revision == "c7d9e1f3a5b6"
    assert rel.backend_ref.startswith("ghcr.io/pinpoint-311/pinpoint-311-backend@sha256:")
    assert rel.stamp_complete and rel.version_mismatch is None
    assert any("/manifests/1.8.0" in u for u in log)  # v stripped for the image tag


def test_resolve_gitlab_registry_with_deploy_token(tmp_path):
    (tmp_path / "rt").write_text("gldt-" + "c" * 20)
    basic = "Basic " + base64.b64encode(("deploy-user:gldt-" + "c" * 20).encode()).decode()
    handler, _ = fake_registry(
        "registry.example.gov", "https://gitlab.example.gov/jwt/auth", "container_registry",
        {"city/pinpoint-311/pinpoint-311-backend": LABELS,
         "city/pinpoint-311/pinpoint-311-frontend": {"org.pinpoint311.app.version": "1.8.0"}},
        require_basic=basic)
    src = GitLabSource(gl_config(registry_token_file=tmp_path / "rt", registry_username="deploy-user"),
                       transport=httpx.MockTransport(handler))
    rel = src.resolve("v1.8.0")
    assert rel.db_revision == "d2e4f6a8b0c1"
    assert rel.frontend_ref.startswith("registry.example.gov/city/pinpoint-311/pinpoint-311-frontend@sha256:")


def test_private_registry_without_token_is_a_clear_error():
    handler, _ = fake_registry("ghcr.io", "https://ghcr.io/token", "ghcr.io",
                               {"pinpoint-311/pinpoint-311-backend": LABELS}, require_basic="Basic nope")
    src = GitHubSource(gh_config(), transport=httpx.MockTransport(handler))
    with pytest.raises(SourceError, match="registry_token_file"):
        src.resolve("v1.8.0")


def test_digest_header_that_does_not_match_the_body_is_refused():
    handler, _ = fake_registry("ghcr.io", "https://ghcr.io/token", "ghcr.io",
                               {"pinpoint-311/pinpoint-311-backend": LABELS}, tamper=True)
    client = RegistryClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RegistryError, match="does not match"):
        client.resolve_digest("ghcr.io/pinpoint-311/pinpoint-311-backend", "1.8.0")


def test_missing_tag_and_bad_tag():
    handler, _ = fake_registry("ghcr.io", "https://ghcr.io/token", "ghcr.io",
                               {"pinpoint-311/pinpoint-311-backend": LABELS})
    client = RegistryClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RegistryError, match="does not exist"):
        client.resolve_digest("ghcr.io/pinpoint-311/pinpoint-311-backend", "9.9.9")
    with pytest.raises(RegistryError, match="valid image tag"):
        client.resolve_digest("ghcr.io/pinpoint-311/pinpoint-311-backend", "../x")


def test_non_https_token_realm_is_refused():
    def handler(request):
        return httpx.Response(401, headers={"WWW-Authenticate": 'Bearer realm="http://evil.example/token",service="x"'})
    client = RegistryClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RegistryError, match="non-https"):
        client.resolve_digest("ghcr.io/a/b", "1.0")
