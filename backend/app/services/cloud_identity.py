"""Whether this server already has an identity on the cloud it is using.

The largest part of setup, by a wide margin, is credentials. A town on Google
pastes a service-account JSON file; on AWS an access key and secret; on Azure a
tenant id, a client id and a client secret. Those are the values a clerk is most
likely to mis-copy, they are the ones that have to be vaulted afterwards, and
the Azure one expires on a date nobody records.

None of them is necessary when the application runs on the cloud it is talking
to. Every provider attaches an identity to the compute itself -- a service
account on GCE/Cloud Run/GKE, an instance role on EC2/ECS, a managed identity on
an Azure VM or App Service -- and the SDKs pick it up from a metadata endpoint
with nothing configured. The credential is issued minutes at a time and rotated
by the platform.

So this is not a shortcut with a security cost. It is the arrangement a
government security review asks for -- no long-lived credential exists to be
leaked, mailed, committed, or left behind by a departing employee -- and it
happens to be the one where a clerk types nothing at all.

Two of the three already worked here by accident: boto3 falls through to the
instance role when no access key is set, and google-auth falls through to
Application Default Credentials. Nothing said so, so nobody knew to leave the
boxes empty. This module detects the situation and lets the page say it.

Detection is a metadata probe with a short timeout, cached: the endpoints are
link-local addresses that either answer immediately or are not there at all.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# The probes hit link-local addresses that are either present or absent, so a
# slow answer means "not here" rather than "wait longer".
_PROBE_TIMEOUT = 1.5

# Detection is stable for the lifetime of a deployment -- compute does not
# acquire an attached identity halfway through an afternoon -- but not cached
# forever, so an operator who attaches one does not have to restart.
_CACHE_TTL = 300
_cache: Dict[str, Any] = {"at": 0.0, "value": None}


def _google() -> Optional[Dict[str, str]]:
    """GCE, Cloud Run, GKE and App Engine all expose the same metadata server."""
    import httpx

    try:
        resp = httpx.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200 and "@" in resp.text:
            return {"provider": "google", "identity": resp.text.strip()}
    except Exception:
        pass
    return None


def _aws() -> Optional[Dict[str, str]]:
    """EC2 and ECS differ: ECS injects a URI into the environment, EC2 uses the
    link-local address and, under IMDSv2, requires a token first."""
    import httpx

    relative = os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    if relative:
        return {"provider": "aws", "identity": "task role"}

    try:
        token = httpx.put(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            timeout=_PROBE_TIMEOUT,
        )
        headers = {"X-aws-ec2-metadata-token": token.text} if token.status_code == 200 else {}
        resp = httpx.get(
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            headers=headers,
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200 and resp.text.strip():
            return {"provider": "aws", "identity": resp.text.strip().splitlines()[0]}
    except Exception:
        pass
    return None


def _azure() -> Optional[Dict[str, str]]:
    """App Service and Container Apps set IDENTITY_ENDPOINT; VMs and VM scale
    sets use the same link-local address as AWS on a different path."""
    import httpx

    endpoint = os.getenv("IDENTITY_ENDPOINT") or os.getenv("MSI_ENDPOINT")
    if endpoint:
        return {"provider": "azure", "identity": "managed identity"}

    try:
        resp = httpx.get(
            "http://169.254.169.254/metadata/instance",
            params={"api-version": "2021-02-01"},
            headers={"Metadata": "true"},
            timeout=_PROBE_TIMEOUT,
        )
        if resp.status_code == 200:
            return {"provider": "azure", "identity": "managed identity"}
    except Exception:
        pass
    return None


def detect(force: bool = False) -> Optional[Dict[str, str]]:
    """The attached identity, or None if this server has none.

    Never raises: it drives an advisory panel and a set of "you can leave this
    empty" hints, and a failed probe should read as "no identity" rather than
    breaking the page.
    """
    now = time.time()
    if not force and _cache["value"] is not None and now - _cache["at"] < _CACHE_TTL:
        return _cache["value"] or None

    found = None
    try:
        # Ordered by how cheaply each fails. Google's hostname does not resolve
        # off GCP; the other two share a link-local address, so probing Azure's
        # path on EC2 returns 404 rather than hanging.
        found = _google() or _azure() or _aws()
    except Exception as exc:
        logger.debug("cloud identity probe failed: %s", exc)

    _cache.update({"at": now, "value": found or {}})
    return found


def summary() -> Dict[str, Any]:
    """What the setup page needs to decide whether to ask for credentials."""
    identity = detect()
    if not identity:
        return {"attached": False, "provider": None, "identity": None, "skippable_keys": []}
    return {
        "attached": True,
        "provider": identity["provider"],
        "identity": identity["identity"],
        # The page greys these out and says why, rather than leaving a clerk to
        # guess whether an empty box is an oversight.
        "skippable_keys": SKIPPABLE.get(identity["provider"], []),
    }


# Credentials the attached identity replaces. Everything else on a card -- key
# names, regions, endpoints -- still has to be entered, because those identify
# *which* resource to use rather than proving who is asking.
SKIPPABLE = {
    "google": ["GCP_SERVICE_ACCOUNT_JSON", "VERTEX_AI_SERVICE_ACCOUNT_KEY"],
    "aws": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"],
    "azure": ["AZURE_KEYVAULT_CLIENT_SECRET", "AZURE_KEYVAULT_CLIENT_ID", "AZURE_TENANT_ID"],
}
