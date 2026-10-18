"""The release list the updater publishes to an instance's console.

The app never calls GitHub or GitLab itself (design section 4): it shows what
the updater resolved and verified here. For the newest few releases this
resolves the tag to digests, runs ``cosign verify`` (and
``verify-attestation`` for the configured types) and checks the schema window
against the instance's live ``db_revision``. Older entries are listed with
those fields unset (``None``), which the console reads as "not checked" and
refuses to request.

``gate_passed``: CI signs a digest only after the release gate (tests, SAST,
Trivy) passes, so a valid signature from the pinned identity is the evidence
the gate passed. It is ``True`` when the signature verifies and ``None``
(unknown) otherwise, never a separate unverified claim.

A digest is immutable, so a positive verdict is cached per digest and trust
policy in ``<log_dir>/<instance>.verified.json``; negative verdicts are
re-checked on the next rebuild (they can be a transient Rekor or registry
failure).

``build_cached`` is what ``poll`` calls every minute: it rebuilds at most every
``release_refresh_seconds`` (default an hour), or when forced after a run, and
otherwise republishes the list cached in ``<log_dir>/<instance>.releases.json``
with only the schema-compatibility check redone against the live
``db_revision`` (one loopback call; no release API, registry or cosign).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from types import SimpleNamespace
from pathlib import Path
from typing import Optional

from pinpoint_updater import steps
from pinpoint_updater.config import UpdaterConfig
from pinpoint_updater.cosign import CosignVerifier
from pinpoint_updater.health import AppProbe, ProbeError
from pinpoint_updater.lockfile import LockFileError, read_lock
from pinpoint_updater.redact import redact
from pinpoint_updater.sources import ReleaseSource, SourceError


class VerdictCache:
    def __init__(self, path: Path, policy: str):
        self.path = path
        self.policy = policy
        try:
            self.data = json.loads(path.read_text())
            if not isinstance(self.data, dict):
                self.data = {}
        except (OSError, ValueError):
            self.data = {}

    def _key(self, kind: str, ref: str) -> str:
        return hashlib.sha256(f"{self.policy}|{kind}|{ref}".encode()).hexdigest()

    def get(self, kind: str, ref: str) -> bool:
        return self.data.get(self._key(kind, ref)) is True

    def put(self, kind: str, ref: str) -> None:
        self.data[self._key(kind, ref)] = True

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data))
            os.replace(tmp, self.path)
        except OSError:
            pass


def _policy_fingerprint(cfg: UpdaterConfig) -> str:
    t = cfg.trust
    return hashlib.sha256(json.dumps([t.key, t.issuer, t.identity], sort_keys=True).encode()).hexdigest()[:16]


def current_images(cfg: UpdaterConfig, name: str) -> Optional[dict]:
    try:
        cur = read_lock(cfg.instance(name).lock_path).current
    except (LockFileError, OSError):
        return None
    return {"version": cur.version, "backend": cur.backend, "frontend": cur.frontend}


def build(cfg: UpdaterConfig, name: str, source: ReleaseSource, verifier: CosignVerifier, probe: AppProbe, *,
          limit: int = 10, resolve: int = 3, insecure: bool = False) -> list[dict]:
    cfg.instance(name)  # ConfigError for an unknown name
    releases = source.list_releases(limit)
    try:
        health = probe.quick()
    except ProbeError:
        health = steps._UNREACHABLE
    cache = VerdictCache(Path(cfg.log_dir) / f"{name}.verified.json", _policy_fingerprint(cfg))
    rows: list[dict] = []
    for i, rel in enumerate(releases):
        row = {
            "tag": rel.tag, "version": steps.norm_version(rel.tag), "name": rel.name,
            "published_at": rel.published_at, "notes": rel.notes, "url": rel.url, "prerelease": rel.prerelease,
            "signature_verified": None, "gate_passed": None, "attested": None,
            "db_revision": None, "min_db_revision": None, "compatible": None, "compatibility": None,
            "backend_digest": None, "frontend_digest": None,
        }
        rows.append(row)
        if i >= resolve:
            continue
        try:
            resolved = source.resolve(rel.tag)
        except (SourceError, ValueError) as exc:
            row["compatibility"] = redact(f"could not resolve: {exc}")[:300]
            continue
        ok, detail = steps.compatibility(resolved, health)
        row.update({"version": resolved.version or row["version"], "db_revision": resolved.db_revision,
                    "min_db_revision": resolved.min_db_revision, "compatible": ok, "compatibility": detail,
                    "backend_digest": resolved.backend_digest, "frontend_digest": resolved.frontend_digest})
        if insecure:
            # Never claim a signature that was not checked.
            continue
        refs = [resolved.backend_ref, resolved.frontend_ref]
        signed = True
        for ref in refs:
            if cache.get("signature", ref):
                continue
            verdict = verifier.verify(ref)
            if verdict.ok:
                cache.put("signature", ref)
            else:
                signed = False
        row["signature_verified"] = signed
        row["gate_passed"] = True if signed else None
        types = list(cfg.trust.attestation_types or [])
        if signed and types:
            attested = True
            for ref in refs:
                for t in types:
                    kind = f"attestation:{t}"
                    if cache.get(kind, ref):
                        continue
                    if verifier.verify_attestation(ref, t).ok:
                        cache.put(kind, ref)
                    else:
                        attested = False
            row["attested"] = attested
    cache.save()
    return rows


def build_cached(cfg: UpdaterConfig, name: str, source: ReleaseSource, verifier: CosignVerifier, probe: AppProbe, *,
                 insecure: bool = False, force: bool = False, now: Optional[float] = None) -> list[dict]:
    """The release list, rebuilt at most every ``release_refresh_seconds``."""
    now = time.time() if now is None else now
    path = Path(cfg.log_dir) / f"{name}.releases.json"
    policy = _policy_fingerprint(cfg)
    cached = None
    try:
        cached = json.loads(path.read_text())
    except (OSError, ValueError):
        cached = None
    fresh = (isinstance(cached, dict) and isinstance(cached.get("rows"), list)
             and cached.get("policy") == policy and cached.get("insecure") == bool(insecure)
             and now - float(cached.get("built_at") or 0) < cfg.release_refresh_seconds)
    if fresh and not force:
        return recheck_compatibility(cached["rows"], probe)
    rows = build(cfg, name, source, verifier, probe, insecure=insecure)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"built_at": now, "policy": policy, "insecure": bool(insecure), "rows": rows}))
        os.replace(tmp, path)
    except OSError:
        pass
    return rows


def recheck_compatibility(rows: list[dict], probe: AppProbe) -> list[dict]:
    """Redo the schema-window check of cached rows against the live revision."""
    try:
        health = probe.quick()
    except ProbeError:
        health = steps._UNREACHABLE
    out = []
    for row in rows:
        row = dict(row)
        if row.get("compatible") is not None:
            rel = SimpleNamespace(db_revision=row.get("db_revision"), min_db_revision=row.get("min_db_revision"))
            row["compatible"], row["compatibility"] = steps.compatibility(rel, health)
        out.append(row)
    return out
