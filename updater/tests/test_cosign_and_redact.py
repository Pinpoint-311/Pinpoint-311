import io
import json

from conftest import FakeRunner, OLD, is_cosign, write_secret
from pinpoint_updater.config import TrustConfig
from pinpoint_updater.cosign import CosignVerifier
from pinpoint_updater.models import RunContext, RunOutcome, StepResult
from pinpoint_updater.redact import redact, register_secret
from pinpoint_updater.reporting import ConsoleReporter, JsonlReporter
from pinpoint_updater.runner import CommandResult, Runner

KEYLESS = TrustConfig(issuer="https://token.actions.githubusercontent.com",
                      identity=r"^https://github\.com/Pinpoint-311/Pinpoint-311/")


def test_keyless_verify_argv():
    r = FakeRunner()
    v = CosignVerifier(KEYLESS, r).verify(OLD.backend)
    assert v.ok
    assert r.calls[0] == ["cosign", "verify", "--certificate-identity-regexp", KEYLESS.identity,
                          "--certificate-oidc-issuer", KEYLESS.issuer, OLD.backend]


def test_key_verify_and_attestations_argv():
    r = FakeRunner()
    trust = TrustConfig(key="/etc/pinpoint-updater/cosign.pub", attestation_types=["spdxjson", "slsaprovenance"])
    verdicts = CosignVerifier(trust, r).verify_all([OLD.backend], require_attestations=True)
    assert all(v.ok for v in verdicts) and len(verdicts) == 3
    assert r.calls[0] == ["cosign", "verify", "--key", "/etc/pinpoint-updater/cosign.pub", OLD.backend]
    assert r.calls[1][:4] == ["cosign", "verify-attestation", "--type", "spdxjson"]


def test_mutable_tag_is_refused_without_running_cosign():
    r = FakeRunner()
    v = CosignVerifier(KEYLESS, r).verify("ghcr.io/x/y:latest")
    assert not v.ok and "not digest-pinned" in v.detail and r.calls == []


def test_missing_cosign_binary():
    r = FakeRunner().on(is_cosign, 127, "", "cosign: not found")
    v = CosignVerifier(KEYLESS, r).verify(OLD.backend)
    assert not v.ok and "not found" in v.detail


def test_runner_refuses_a_shell_string():
    import pytest
    with pytest.raises(TypeError):
        Runner().run("echo hi; rm -rf /", timeout=1)


def test_runner_never_uses_a_shell(monkeypatch):
    import subprocess
    seen = {}

    def fake_run(args, **kw):
        seen.update(kw, args=args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("BACKEND_IMAGE", "attacker/image:latest")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "someone-else")
    Runner().run(["docker", "compose", "ps"], timeout=5, env={"FRONTEND_IMAGE": "f"})
    assert seen["shell"] is False and isinstance(seen["args"], list)
    assert "BACKEND_IMAGE" not in seen["env"] and "COMPOSE_PROJECT_NAME" not in seen["env"]
    assert seen["env"]["FRONTEND_IMAGE"] == "f"


# -- redaction -------------------------------------------------------------------------

def test_known_shapes_are_redacted():
    samples = {
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig": "eyJhbGciOiJIUzI1NiJ9",
        "token ghp_" + "A" * 36: "ghp_" + "A" * 36,
        "github_pat_" + "B" * 40: "B" * 40,
        "glpat-" + "C" * 20: "C" * 20,
        "https://user:hunter2secret@registry.example.gov/v2/": "hunter2secret",
        "GET /token?scope=x&access_token=s3cr3tvalue": "s3cr3tvalue",
        "PRIVATE-TOKEN: abcdefabcdef": "abcdefabcdef",
    }
    for text, secret in samples.items():
        assert secret not in redact(text), text


def test_registered_secrets_are_redacted_everywhere(tmp_path):
    token = "plain-looking-registry-token-1234"
    register_secret(token)
    assert token not in redact({"a": [f"x {token} y"]})["a"][0]
    assert token not in CommandResult(["x"], 1, f"out {token}", f"err {token}").tail()

    run = RunContext(instance="town", action="upgrade", tag="v1")
    step = StepResult("pull", "failed", f"denied for {token}", {"argv": ["--password", token]})
    JsonlReporter(tmp_path).step(run, step)
    JsonlReporter(tmp_path).finished(run, RunOutcome("refused", f"because {token}", [step]))
    text = (tmp_path / "town.jsonl").read_text()
    assert token not in text and json.loads(text.splitlines()[0])["status"] == "failed"

    buf = io.StringIO()
    ConsoleReporter(buf).step(run, step)
    assert token not in buf.getvalue()


def test_secret_files_loaded_by_config_are_registered(tmp_path):
    from pinpoint_updater.config import ReleaseSourceConfig
    write_secret(tmp_path / "rt", "deploy-token-value-xyz\n")
    cfg = ReleaseSourceConfig(provider="gitlab", api="https://gitlab.com/api/v4", project="a/b",
                              registry="registry.gitlab.com/a/b", registry_token_file=tmp_path / "rt")
    assert cfg.registry_token() == "deploy-token-value-xyz"
    assert "deploy-token-value-xyz" not in redact("error: deploy-token-value-xyz rejected")


def test_the_runner_drops_every_inherited_compose_variable(monkeypatch):
    from pinpoint_updater.runner import Runner
    monkeypatch.setenv("COMPOSE_FILE", "/tmp/evil.yml")
    monkeypatch.setenv("COMPOSE_REMOVE_ORPHANS", "1")
    monkeypatch.setenv("BACKEND_IMAGE", "evil@sha256:" + "0" * 64)
    monkeypatch.setenv("KEEP_ME", "yes")
    out = Runner().run(["env"], timeout=10).stdout
    assert "COMPOSE_" not in out and "BACKEND_IMAGE" not in out and "KEEP_ME=yes" in out
