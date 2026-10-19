"""Signature admission via the ``cosign`` binary.

Ported from centralizedhosting/orchestrator/supply_chain.py (``_run_cosign``,
``verify_image``, ``verify_refs``): keyless verification needs both the
certificate identity regexp and the OIDC issuer, key-based verification uses
``--key``, a ref that is not digest-pinned is refused before cosign runs, and
the invocation is isolated behind a ``Runner`` so tests substitute it.

Added here: ``cosign verify-attestation --type …`` for instances that require
SBOM/provenance attestations (design §1, "the updater can then require them").
"""

from __future__ import annotations

from dataclasses import dataclass

from pinpoint_updater.config import TrustConfig
from pinpoint_updater.redact import redact
from pinpoint_updater.runner import Runner


@dataclass
class Verdict:
    ref: str
    ok: bool
    detail: str
    kind: str = "signature"

    def as_dict(self) -> dict:
        return {"ref": self.ref, "ok": self.ok, "detail": self.detail, "kind": self.kind}


class CosignVerifier:
    def __init__(self, trust: TrustConfig, runner: Runner, timeout: float = 180):
        self.trust = trust
        self.runner = runner
        self.timeout = timeout

    def _policy_args(self) -> list[str] | None:
        if self.trust.key:
            return ["--key", self.trust.key]
        if not (self.trust.identity and self.trust.issuer):
            # Config validation already refuses this; checked again so a policy
            # built some other way can never fall through to an unconstrained
            # verify that accepts any signer.
            return None
        return [
            "--certificate-identity-regexp", self.trust.identity,
            "--certificate-oidc-issuer", self.trust.issuer,
        ]

    def _run(self, subcommand: list[str], ref: str, kind: str) -> Verdict:
        if "@sha256:" not in ref:
            return Verdict(ref, False, f"{ref} is not digest-pinned; cannot verify a mutable tag", kind)
        policy = self._policy_args()
        if policy is None:
            return Verdict(ref, False, "keyless verify needs trust.identity and trust.issuer (or trust.key)", kind)
        result = self.runner.run([self.trust.cosign_binary, *subcommand, *policy, ref], timeout=self.timeout)
        name = ref.split("@")[0]
        if result.returncode == 127:
            return Verdict(ref, False, f"cosign binary {self.trust.cosign_binary!r} not found on PATH", kind)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "verification failed").strip()[-500:]
            return Verdict(ref, False, redact(f"{name}: {detail}"), kind)
        return Verdict(ref, True, f"{name}: {kind} verified ({self.trust.mode})", kind)

    def verify(self, ref: str) -> Verdict:
        return self._run(["verify"], ref, "signature")

    def verify_attestation(self, ref: str, predicate_type: str) -> Verdict:
        return self._run(["verify-attestation", "--type", predicate_type], ref, f"attestation:{predicate_type}")

    def verify_all(self, refs: list[str], require_attestations: bool) -> list[Verdict]:
        verdicts = [self.verify(ref) for ref in refs]
        if require_attestations:
            for ref in refs:
                for t in self.trust.attestation_types:
                    verdicts.append(self.verify_attestation(ref, t))
        return verdicts
