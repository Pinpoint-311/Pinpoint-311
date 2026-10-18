import copy

import pytest

from conftest import base_config
from pinpoint_updater.config import ConfigError, load_config, parse_config


def ok(tmp_path, mutate=None):
    data = base_config(tmp_path)
    if mutate:
        mutate(data)
    return parse_config(data)


def bad(tmp_path, mutate, match):
    data = base_config(tmp_path)
    mutate(data)
    with pytest.raises(ConfigError, match=match):
        parse_config(data)


def test_valid_config_resolves_paths(tmp_path):
    cfg = ok(tmp_path)
    inst = cfg.instance("town")
    assert inst.lock_path == inst.dir / "release.lock"
    assert inst.compose_paths[0] == inst.dir / "docker-compose.yml"
    assert cfg.trust.mode == "keyless"
    assert inst.backup.mode == "verify"
    assert inst.services == ["backend", "worker", "frontend"]


def test_keyless_needs_both_issuer_and_identity(tmp_path):
    bad(tmp_path, lambda d: d["trust"].pop("identity"), "issuer and identity")
    bad(tmp_path, lambda d: d["trust"].pop("issuer"), "issuer and identity")
    bad(tmp_path, lambda d: d.__setitem__("trust", {}), "issuer and identity")


def test_identity_must_be_anchored(tmp_path):
    bad(tmp_path, lambda d: d["trust"].__setitem__("identity", "github.com/Pinpoint-311"), "anchored")


def test_key_based_trust(tmp_path):
    cfg = ok(tmp_path, lambda d: d.__setitem__("trust", {"key": "/etc/pinpoint-updater/cosign.pub"}))
    assert cfg.trust.mode == "key"
    bad(tmp_path, lambda d: d["trust"].__setitem__("key", "/k.pub"), "not both")


def test_app_url_must_be_loopback(tmp_path):
    bad(tmp_path, lambda d: d["instances"]["town"].__setitem__("app_url", "https://town.example.gov"), "loopback")
    ok(tmp_path, lambda d: d["instances"]["town"].__setitem__("app_url", "http://[::1]:8080"))


def test_instance_fields_are_validated(tmp_path):
    bad(tmp_path, lambda d: d["instances"]["town"].__setitem__("project", "Bad Name"), "compose project")
    bad(tmp_path, lambda d: d["instances"]["town"].__setitem__("dir", "relative/dir"), "absolute")
    bad(tmp_path, lambda d: d["instances"]["town"].__setitem__("compose", []), "compose")
    bad(tmp_path, lambda d: d["instances"]["town"].__setitem__("typo_key", 1), "typo_key")
    bad(tmp_path, lambda d: d["instances"].__setitem__("Town!", d["instances"]["town"]), "instance name")


def test_two_instances_cannot_share_a_project(tmp_path):
    def dup(d):
        d["instances"]["other"] = copy.deepcopy(d["instances"]["town"])
    bad(tmp_path, dup, "same compose project")


def test_release_source_validation(tmp_path):
    bad(tmp_path, lambda d: d["release_source"].__setitem__("api", "http://api.github.com"), "https")
    bad(tmp_path, lambda d: d["release_source"].__setitem__("registry", "pinpoint-311"), "registry host")
    bad(tmp_path, lambda d: d["release_source"].__setitem__("provider", "bitbucket"), "provider")
    cfg = ok(tmp_path, lambda d: d.__setitem__("release_source", {
        "provider": "gitlab", "api": "https://gitlab.example.gov/api/v4", "project": "city/pinpoint-311",
        "registry": "registry.example.gov/city/pinpoint-311"}))
    assert cfg.release_source.image_repo("backend") == "registry.example.gov/city/pinpoint-311/pinpoint-311-backend"
    assert cfg.release_source.image_tag_for("v1.8.0") == "1.8.0"
    assert cfg.release_source.image_tag_for("release-7") == "release-7"


def test_load_config_errors_are_config_errors(tmp_path):
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path / "missing.yml")
    (tmp_path / "bad.yml").write_text("release_source: [\n")
    with pytest.raises(ConfigError, match="YAML"):
        load_config(tmp_path / "bad.yml")


def test_example_config_is_valid():
    from pathlib import Path
    example = Path(__file__).resolve().parents[1] / "deploy" / "instances.example.yml"
    cfg = load_config(example)
    assert cfg.instances
