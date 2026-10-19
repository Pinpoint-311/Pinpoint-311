"""Azure Key Vault client (secrets + key crypto) over the REST API.

Used to offer Azure as an alternative to Google for the two host-managed
capabilities: PII key management (KMS-equivalent) and the secret store. Uses
plain httpx (sync) + AAD client-credentials — no azure SDK dependency, and
fully mockable. Works against commercial and Azure Government by configuring
the authority + vault scope.

All functions are synchronous because the PII encrypt/decrypt path
(models.py setters) is synchronous, matching the existing Google KMS usage.
"""

import base64
import logging
import os
import time
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# cache: (tenant, client_id, scope) -> (token, expiry_epoch)
_token_cache: dict = {}


def _cfg(key: str) -> Optional[str]:
    """Read Azure Key Vault config from env, then DB secrets (same resolver the
    Google KMS path uses)."""
    val = os.getenv(key)
    if val:
        return val
    try:
        from app.core.encryption import _get_config_sync
        return _get_config_sync(key)
    except Exception:
        return None


def _b64url_nopad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def is_configured() -> bool:
    """A vault URL, plus some way to prove who we are.

    The second half used to require a client secret. On an Azure VM, App Service
    or Container App there is a managed identity attached to the compute, and
    using it is both less work -- nothing to enter -- and better: the token is
    issued minutes at a time and rotated by the platform, so no long-lived
    secret exists to leak, and none expires on a date nobody wrote down.
    Requiring a client secret meant a town on Azure had to create the worst
    credential of the three clouds while the platform was already offering it
    the best one.
    """
    if not _cfg("AZURE_KEYVAULT_URL"):
        return False
    if _managed_identity_endpoint():
        return True
    return bool(_cfg("AZURE_TENANT_ID") and _cfg("AZURE_KEYVAULT_CLIENT_ID")
                and _cfg("AZURE_KEYVAULT_CLIENT_SECRET"))


def _managed_identity_endpoint() -> Optional[str]:
    """Where to ask for a token, if this host has an identity of its own.

    App Service and Container Apps inject IDENTITY_ENDPOINT with a matching
    header secret; VMs and scale sets use the link-local IMDS address. Both are
    reachable only from inside Azure, so their presence is the detection.
    """
    return os.getenv("IDENTITY_ENDPOINT") or os.getenv("MSI_ENDPOINT")


def _managed_identity_token(scope: str):
    """(token, ttl_seconds) from the attached identity, or None."""
    endpoint = _managed_identity_endpoint()
    header_secret = os.getenv("IDENTITY_HEADER") or os.getenv("MSI_SECRET")
    try:
        if endpoint:
            resp = httpx.get(
                endpoint,
                params={"api-version": "2019-08-01", "resource": scope},
                headers={"X-IDENTITY-HEADER": header_secret} if header_secret else {},
                timeout=15.0,
            )
        else:
            resp = httpx.get(
                "http://169.254.169.254/metadata/identity/oauth2/token",
                params={"api-version": "2018-02-01", "resource": scope},
                headers={"Metadata": "true"},
                timeout=15.0,
            )
        resp.raise_for_status()
        body = resp.json()
        return body["access_token"], int(body.get("expires_in", 3600))
    except Exception as e:
        logger.debug(f"Managed identity token request failed: {e}")
        return None


def _get_token() -> Optional[str]:
    tenant = _cfg("AZURE_TENANT_ID")
    client_id = _cfg("AZURE_KEYVAULT_CLIENT_ID")
    client_secret = _cfg("AZURE_KEYVAULT_CLIENT_SECRET")
    authority = _cfg("AZURE_AUTHORITY") or "login.microsoftonline.com"
    scope = _cfg("AZURE_KEYVAULT_SCOPE") or "https://vault.azure.net"

    # The attached identity wins when there is one, rather than serving as a
    # fallback. A town with both keeps working after the client secret expires,
    # which is the failure this is most useful against.
    if _managed_identity_endpoint():
        cache_key = ("managed", scope)
        cached = _token_cache.get(cache_key)
        if cached and cached[1] - 60 > time.time():
            return cached[0]
        result = _managed_identity_token(scope)
        if result:
            token, ttl = result
            _token_cache[cache_key] = (token, time.time() + ttl)
            return token

    if not all([tenant, client_id, client_secret]):
        return None

    cache_key = (tenant, client_id, scope)
    cached = _token_cache.get(cache_key)
    if cached and cached[1] - 60 > time.time():
        return cached[0]

    resp = httpx.post(
        f"https://{authority}/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": f"{scope}/.default",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )
    resp.raise_for_status()
    body = resp.json()
    token = body["access_token"]
    _token_cache[cache_key] = (token, time.time() + int(body.get("expires_in", 3600)))
    return token


def _vault_url() -> str:
    return (_cfg("AZURE_KEYVAULT_URL") or "").rstrip("/")


def _api_version() -> str:
    return _cfg("AZURE_KEYVAULT_API_VERSION") or "7.4"


# ---- Key crypto (KMS-equivalent) ----

# wrapKey/unwrapKey, not encrypt/decrypt.
#
# A Key Vault key carries a `keyOps` list, and wrapKey/unwrapKey are separate
# entries from encrypt/decrypt even though RSA-OAEP performs the identical
# operation for both. Our own ARM template creates the key with
# ["wrapKey", "unwrapKey"] -- the tighter and more accurate choice, since what
# this module does is wrap a data encryption key -- while the code called
# /encrypt and /decrypt. So a vault built by our own template refused every call
# with
#
#     403 "Operation encrypt is not permitted on this key." (KeyOperationForbidden)
#
# and resident data fell back to the application key with nothing said. The
# template was right and the client was wrong, so the client changed: widening
# the key's permissions to match a mistake would have made every future
# deployment's key more capable than it needs to be.


def _key_op(operation: str, value: str, version: Optional[str] = None) -> dict:
    token = _get_token()
    key_name = _cfg("AZURE_KEYVAULT_KEY")
    if not token or not key_name:
        raise RuntimeError("Azure Key Vault key crypto not configured")
    path = f"{key_name}/{version}" if version else key_name
    resp = httpx.post(
        f"{_vault_url()}/keys/{path}/{operation}?api-version={_api_version()}",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json={"alg": "RSA-OAEP-256", "value": value},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def _version_of(kid: str) -> str:
    """The version segment of a key id: .../keys/<name>/<version>."""
    return (kid or "").rstrip("/").rsplit("/", 1)[-1]


# Key rotation.
#
# A call to /keys/<name>/unwrapkey with no version uses the key's *current*
# version. That is right for wrapping and wrong for unwrapping: after the
# town rotates the key (a 90-day policy is ordinary), every data key wrapped
# under the previous version would be sent to the new one and refused, and
# every resident record would stop decrypting while the version that could
# open them sat enabled in the same vault. So a wrap records the version Key
# Vault used (the `kid` in its answer), and an unwrap names it.

def encrypt(plaintext: str) -> str:
    """Wrap a small value with the configured Key Vault key (RSA-OAEP-256).

    Named `encrypt` for its callers; the request it makes is `wrapkey`. Returns
    the base64url ciphertext. Prefer `wrap_versioned`, which also says which
    key version did the wrapping.
    """
    return wrap_versioned(plaintext)[1]


def wrap_versioned(plaintext: str) -> Tuple[str, str]:
    """(key version, base64url ciphertext) for a value wrapped with the key's current version."""
    body = _key_op("wrapkey", _b64url_nopad(plaintext.encode("utf-8")))
    return _version_of(body.get("kid", "")), body["value"]


def decrypt(ciphertext_b64url: str, version: Optional[str] = None) -> str:
    """Unwrap with the named key version, or the current one when none is given."""
    return _b64url_decode(_key_op("unwrapkey", ciphertext_b64url, version)["value"]).decode("utf-8")


def decrypt_any_version(ciphertext_b64url: str) -> str:
    """Unwrap a value whose wrapping version was not recorded.

    Values written before versions were recorded. Tries the current version
    first -- right for every such value until the key is first rotated -- then
    each other enabled version, newest first.
    """
    try:
        return decrypt(ciphertext_b64url)
    except httpx.HTTPStatusError as first:
        if first.response.status_code in (401, 403):
            raise  # authorisation, not the wrong version: another version will not help
        for version in key_versions()[1:]:
            try:
                return decrypt(ciphertext_b64url, version)
            except httpx.HTTPStatusError:
                continue
        raise first


def _get_json(path: str) -> dict:
    token = _get_token()
    if not token:
        raise RuntimeError("no Key Vault access token")
    resp = httpx.get(path if path.startswith("http") else
                     f"{_vault_url()}{path}?api-version={_api_version()}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    resp.raise_for_status()
    return resp.json()


def key_versions() -> List[str]:
    """The key's enabled versions, newest first."""
    key_name = _cfg("AZURE_KEYVAULT_KEY")
    if not key_name:
        return []
    items, page = [], _get_json(f"/keys/{key_name}/versions")
    while True:
        items.extend(page.get("value", []))
        nxt = page.get("nextLink")
        if not nxt:
            break
        page = _get_json(nxt)
    enabled = [i for i in items if (i.get("attributes") or {}).get("enabled", True)]
    enabled.sort(key=lambda i: (i.get("attributes") or {}).get("created", 0), reverse=True)
    return [_version_of(i.get("kid", "")) for i in enabled]


_current_version_cache: dict = {}
_CURRENT_VERSION_TTL = 600.0


def current_key_version() -> Optional[str]:
    """The version a wrap would use now. Cached ten minutes; None if it cannot be read."""
    key_name = _cfg("AZURE_KEYVAULT_KEY")
    if not key_name:
        return None
    hit = _current_version_cache.get(key_name)
    if hit and hit[1] > time.time():
        return hit[0]
    try:
        version = _version_of((_get_json(f"/keys/{key_name}").get("key") or {}).get("kid", ""))
    except Exception as exc:
        logger.debug("Key Vault: could not read the current key version: %s", exc)
        return hit[0] if hit else None
    _current_version_cache[key_name] = (version, time.time() + _CURRENT_VERSION_TTL)
    return version


def key_posture() -> dict:
    """Attributes that decide whether the key can be lost: recovery level, expiry, enabled.

    Read-only, and attributes only -- never key material (the key is not
    exportable anyway).
    """
    key_name = _cfg("AZURE_KEYVAULT_KEY")
    attrs = (_get_json(f"/keys/{key_name}").get("attributes") or {}) if key_name else {}
    return {
        "enabled": attrs.get("enabled"),
        "recovery_level": attrs.get("recoveryLevel"),
        "recoverable_days": attrs.get("recoverableDays"),
        "expires": attrs.get("exp"),
        "exportable": attrs.get("exportable"),
    }


# ---- Secret store ----

def _secret_id(name: str) -> str:
    # Key Vault secret names allow only alphanumerics and dashes
    return name.replace("_", "-").lower()


def get_secret(name: str) -> Optional[str]:
    """The secret's value, or None only when Key Vault says it does not exist.

    Anything else raises. "Could not ask" used to return None too, which reads
    as "not set": secret_manager caches that answer, so one failed token
    request made the AI key look absent for fifteen minutes and reports were
    filed with AI analysis skipped.
    """
    token = _get_token()
    if not token:
        raise RuntimeError("no Key Vault access token")
    url = f"{_vault_url()}/secrets/{_secret_id(name)}?api-version={_api_version()}"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("value")


# How long to wait for Key Vault's soft-delete state changes, which are
# asynchronous: a delete takes a moment to land in the recycle bin, and a
# recovery a moment to come back. About a second each, measured live.
_SOFT_DELETE_WAIT_SECONDS = 20.0


def _inner_code(resp) -> str:
    try:
        err = resp.json().get("error") or {}
        return (err.get("innererror") or {}).get("code") or err.get("code") or ""
    except Exception:
        return ""


def _wait_for(check) -> bool:
    deadline = time.time() + _SOFT_DELETE_WAIT_SECONDS
    while True:
        if check():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(1.0)


def _recover_deleted(secret_id: str, headers: dict) -> None:
    """Bring a soft-deleted secret back so its name can be written again.

    Soft-delete is on by default and cannot be turned off on a new vault. A
    deleted secret keeps its name for the retention period (90 days by
    default) and a PUT to that name answers 409 ObjectIsDeletedButRecoverable.
    The secret-store self-test deletes its probe key every run, so live, every
    test after the first failed as "would not accept a test write" -- and a
    credential removed on disconnect could not be saved again on reconnect.

    Recover rather than purge: recover is in the same Secrets Officer role as
    write and works with purge protection on; purge is neither.
    """
    base, version = _vault_url(), _api_version()
    deleted_url = f"{base}/deletedsecrets/{secret_id}?api-version={version}"
    # Right after a delete the secret is "being deleted" and cannot be
    # recovered until it has landed in the recycle bin.
    _wait_for(lambda: httpx.get(deleted_url, headers=headers, timeout=15.0).status_code == 200)
    resp = httpx.post(f"{base}/deletedsecrets/{secret_id}/recover?api-version={version}",
                      headers=headers, timeout=15.0)
    resp.raise_for_status()
    live_url = f"{base}/secrets/{secret_id}?api-version={version}"
    _wait_for(lambda: httpx.get(live_url, headers=headers, timeout=15.0).status_code == 200)


def set_secret(name: str, value: str) -> bool:
    token = _get_token()
    if not token:
        return False
    secret_id = _secret_id(name)
    url = f"{_vault_url()}/secrets/{secret_id}?api-version={_api_version()}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def put():
        return httpx.put(url, headers=headers, json={"value": value}, timeout=15.0)

    resp = put()
    if resp.status_code == 409 and _inner_code(resp) in (
            "ObjectIsDeletedButRecoverable", "ObjectIsBeingDeleted"):
        _recover_deleted(secret_id, headers)
        resp = put()
    resp.raise_for_status()
    return True


def delete_secret(name: str) -> bool:
    """Remove a secret from the vault. Returns whether it is gone.

    Two callers depend on this: the secret-store round-trip check, whose probe
    must take back what it wrote or leave litter in a town's vault forever, and
    govtech-integration disconnect, which takes the vendor credentials out of
    the vault with the connection rather than leaving a live client secret with
    nothing in the UI referring to it. A 404 counts as success -- the caller
    asked for it to be absent, and it is.
    """
    token = _get_token()
    if not token:
        return False
    url = f"{_vault_url()}/secrets/{_secret_id(name)}?api-version={_api_version()}"
    resp = httpx.delete(url, headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    if resp.status_code == 404:
        return True
    resp.raise_for_status()
    return True
