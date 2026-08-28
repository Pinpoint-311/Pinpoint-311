"""Admin API for external govtech platform integrations, plus the inbound
webhook endpoint that lets connected platforms (e.g. Polimorphic's AI intake)
create and update requests in Pinpoint."""

import logging
import secrets as pysecrets
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from app.core.client_ip import client_ip, rate_limit_key
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin, get_current_staff
from app.db.session import get_db
from app.services.enqueue import QUEUE_UNAVAILABLE, enqueue
from app.integrations import (
    PLATFORM_CATALOG, build_connector_for, store_credentials,
)
from app.models import (
    IntegrationConfig,
    IntegrationDeadLetter,
    IntegrationLink,
    IntegrationSyncLog,
    RequestAuditLog,
    RequestComment,
    ServiceDefinition,
    ServiceRequest,
    User,
)

# Per-caller, not per-proxy -- see app/core/client_ip.py.
limiter = Limiter(key_func=rate_limit_key)
logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- Schemas ----------

class IntegrationCreate(BaseModel):
    platform: str
    display_name: Optional[str] = None
    enabled: bool = False
    sync_direction: str = Field(default="push", pattern="^(push|pull|bidirectional)$")
    config: Dict[str, Any] = {}
    credentials: Dict[str, str] = {}


class IntegrationUpdate(BaseModel):
    display_name: Optional[str] = None
    enabled: Optional[bool] = None
    sync_direction: Optional[str] = Field(default=None, pattern="^(push|pull|bidirectional)$")
    config: Optional[Dict[str, Any]] = None
    # Only keys present are updated; empty-string values are ignored (keep existing)
    credentials: Optional[Dict[str, str]] = None


class WebhookCommentIn(BaseModel):
    """A comment carried in an inbound webhook payload."""
    content: str = Field(..., min_length=1, max_length=5000)
    author: Optional[str] = Field(default=None, max_length=100)
    external_id: Optional[str] = Field(default=None, max_length=100)


class WebhookRequestIn(BaseModel):
    """Normalized inbound payload external platforms POST to the webhook."""
    external_id: str = Field(..., max_length=200)
    # Optional when updating an existing record (status/comment-only posts)
    description: Optional[str] = Field(default=None, max_length=10000)
    comments: Optional[List[WebhookCommentIn]] = None
    service_code: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(open|in_progress|closed)$")
    address: Optional[str] = Field(default=None, max_length=500)
    lat: Optional[float] = None
    long: Optional[float] = None
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=30)
    media_urls: Optional[List[str]] = None


def _allowed_keys(platform: str, field_list: str) -> set:
    catalog = PLATFORM_CATALOG.get(platform, {})
    return {f["key"] for f in catalog.get(field_list, []) if isinstance(f, dict) and f.get("key")}


def _reject_unknown_keys(platform: str, credentials: Optional[Dict[str, Any]],
                         config: Optional[Dict[str, Any]]) -> None:
    """Refuse credential and config keys the platform does not declare.

    `credentials` is unvalidated input that becomes a Secret Manager key name:
    `store_credentials` writes each field to `INTEGRATION_<PLATFORM>_<FIELD>`.
    Without an allowlist an admin could name any field they liked and write
    arbitrary `INTEGRATION_*` entries into the town's vault of record -- next to
    the ones the platform itself relies on, in the namespace it reads from.

    The same check on `config` is about honesty rather than the vault: config is
    merged into a JSON blob that the connectors read by key, so an unrecognised
    key is a setting the admin believes they set and nothing will ever read.
    """
    for values, field_list, label in (
        (credentials, "credential_fields", "credential"),
        (config, "config_fields", "setting"),
    ):
        if not values:
            continue
        allowed = _allowed_keys(platform, field_list)
        unknown = sorted(set(values) - allowed - _EXTRA_CONFIG_KEYS.get(field_list, set()))
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(f"Unknown {label} field(s) for {platform}: {', '.join(unknown)}. "
                        f"Accepted: {', '.join(sorted(allowed)) or 'none'}"),
            )


# Config keys the connectors read that the wizard does not show as fields --
# per-vendor mappings and tuning an integrator sets deliberately. Kept as an
# explicit list so "the catalog does not mention it" stays the default answer.
_EXTRA_CONFIG_KEYS = {
    "config_fields": {
        "share_pii", "import_new_records", "service_code_map",
        "default_local_service_code", "status_map_in", "status_map_out",
        "field_map", "static_fields", "max_retries", "max_pull_pages",
        "list_items_field", "next_field", "comments_path", "comments_items_field",
        "comment_id_field", "comment_text_field", "comment_author_field",
        "comment_created_field", "documents_path", "document_file_field",
        "assets_path", "assets_items_field", "asset_id_field", "asset_name_field",
        "asset_type_field", "asset_lat_field", "asset_long_field",
        "asset_layer_id", "asset_service_codes", "assets_on_resident_portal",
        "work_order_id_field", "priority_field", "assigned_to_field",
        "assigned_department_field", "scheduled_date_field", "due_date_field",
        "resolution_field", "auth_query_param", "api_base", "auth_base",
    },
}


def _vaulted_state(credentials: Dict[str, Any]) -> str:
    """Whether every stored credential is a vault reference, some, or none."""
    from app.integrations.credentials import is_reference

    values = list(credentials.values())
    if not values:
        return "none"
    referenced = [v for v in values if is_reference(v)]
    if len(referenced) == len(values):
        return "all"
    return "partial" if referenced else "none"


def _serialize(integration: IntegrationConfig) -> Dict[str, Any]:
    from app.integrations.registry import RETIRED_PLATFORMS, connector_available

    catalog = PLATFORM_CATALOG.get(integration.platform, {})
    # Read once. `credentials` is a hybrid property that Fernet-decrypts on every
    # access, and this function touched it four times per row -- on a list of
    # connections that is four decryptions each, for one response.
    credentials = integration.credentials or {}
    vaulted = _vaulted_state(credentials)
    return {
        "id": integration.id,
        "platform": integration.platform,
        "platform_name": (
            catalog.get("name")
            or RETIRED_PLATFORMS.get(integration.platform)
            or integration.platform
        ),
        # A row for a platform Pinpoint no longer connects. The row is kept --
        # a town's stored decision is not ours to delete -- and every sync task
        # and the nightly health sweep skip it, so it costs nothing and raises
        # no alerts. It has no catalog entry and therefore no card, so this flag
        # is the one place the admin list can say what it is instead of the row
        # simply vanishing from the page while still sitting in the database.
        "retired": not connector_available(integration.platform),
        "retired_reason": (
            f"The {RETIRED_PLATFORMS[integration.platform]} connector has been removed "
            "from Pinpoint. These settings are kept so nothing is lost, but nothing "
            "syncs. To reach the same system, connect it through the generic Open311 "
            "connector — it publishes a GeoReport v2 endpoint."
        ) if integration.platform in RETIRED_PLATFORMS else None,
        "display_name": integration.display_name,
        "enabled": integration.enabled,
        "sync_direction": integration.sync_direction,
        "config": integration.config or {},
        # Never return secret values — only which keys are set
        "configured_credentials": sorted(credentials.keys()),
        # A stored refresh token means the admin completed the vendor's own
        # sign-in, so the UI can say "signed in" instead of asking for one again.
        "oauth_connected": bool(credentials.get("refresh_token")),
        # Whether the stored credentials are Secret Manager references (the raw
        # secret lives only in the vault, not this database) — the UI's "stored in
        # your Secret Manager" trust line.
        #
        # `all`, not `any`. A vault write that failed for one field falls back to
        # keeping that value encrypted in this database, and `any` reported the
        # whole set as vaulted on the strength of the fields that succeeded. A
        # trust signal about where secrets live must not round up.
        "credentials_vaulted": vaulted == "all",
        # "all" | "partial" | "none", so the UI can say which rather than only
        # yes-or-no. Partial is the state worth naming: it means at least one
        # secret is in the application database after all.
        "credentials_vaulted_state": vaulted,
        # The vendor's own code lists, so the mapping fields are a menu rather
        # than a text box. Empty for a vendor that publishes no such list --
        # which is a real answer, not a missing one.
        "lookups": integration.lookups_cache or {},
        "lookups_fetched_at": (integration.lookups_fetched_at.isoformat()
                               if integration.lookups_fetched_at else None),
        # "somebody looked at the mapping and said yes" is not the same fact as
        # "a mapping exists", and an empty approved mapping is a decision.
        "mapping_approved_at": (integration.mapping_approved_at.isoformat()
                                if integration.mapping_approved_at else None),
        "mapping_approved_by": integration.mapping_approved_by,
        "webhook_path": f"/api/integrations/webhook/{integration.platform}/{integration.webhook_token}",
        "last_sync_at": integration.last_sync_at.isoformat() if integration.last_sync_at else None,
        "last_sync_status": integration.last_sync_status,
        "last_sync_error": integration.last_sync_error,
        "created_at": integration.created_at.isoformat() if integration.created_at else None,
    }


async def _get_integration(db: AsyncSession, integration_id: int) -> IntegrationConfig:
    integration = (await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.id == integration_id)
    )).scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


# ---------- Catalog & CRUD (admin) ----------

@router.get("/catalog")
async def get_platform_catalog(_: User = Depends(get_current_staff)):
    """List all supported govtech platforms and the fields each requires."""
    return [{"platform": key, **meta} for key, meta in PLATFORM_CATALOG.items()]


@router.get("")
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    integrations = (await db.execute(
        select(IntegrationConfig).order_by(IntegrationConfig.created_at.asc())
    )).scalars().all()
    # How much work is still owed to each vendor, in one aggregate rather than a
    # query per card. A card that says "Working" while nine reports sit in the
    # backlog is telling the truth about the connection and nothing about the
    # town, which is the gap this closes.
    backlog = await _backlog_counts(db)
    return [{**_serialize(i), **backlog.get(i.id, _EMPTY_BACKLOG)} for i in integrations]


# What a connection owes when it owes nothing.
_EMPTY_BACKLOG = {"backlog_open": 0, "backlog_stalled": 0}


async def _backlog_counts(db: AsyncSession) -> Dict[int, Dict[str, int]]:
    """Open backlog per integration, split by whether it is still being retried.

    `stalled` is the number past the automatic schedule -- those have
    `next_attempt_at` NULL and will not move again on their own. They are the
    ones worth a badge: everything else is a connection that is already
    recovering by itself.

    Never raises. A deployment that has not run the migration has no table, and
    a missing backlog count must not take the whole connections list down with
    it.
    """
    from sqlalchemy import func

    try:
        rows = (await db.execute(
            select(
                IntegrationDeadLetter.integration_id,
                func.count().label("open"),
                func.count(IntegrationDeadLetter.id).filter(
                    IntegrationDeadLetter.next_attempt_at.is_(None)
                ).label("stalled"),
            )
            .where(IntegrationDeadLetter.resolved_at.is_(None))
            .group_by(IntegrationDeadLetter.integration_id)
        )).all()
    except Exception as exc:
        from app.core.sanitize import sanitize_for_log
        logger.warning("[Integrations] could not read the push backlog: %s",
                       sanitize_for_log(str(exc)[:300]))
        return {}
    return {r[0]: {"backlog_open": r[1] or 0, "backlog_stalled": r[2] or 0} for r in rows}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_integration(
    data: IntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    if data.platform not in PLATFORM_CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {data.platform}")
    _reject_unknown_keys(data.platform, data.credentials, data.config)

    existing = (await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.platform == data.platform)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"An integration for {data.platform} already exists")

    integration = IntegrationConfig(
        platform=data.platform,
        display_name=data.display_name or PLATFORM_CATALOG[data.platform]["name"],
        enabled=data.enabled,
        sync_direction=data.sync_direction,
        config=data.config,
        webhook_token=pysecrets.token_urlsafe(32),
    )
    # Secret Manager of record: write raw values to the configured vault and
    # store only @secret: references on the row. Falls back to encrypted-in-DB
    # when no external vault is configured (see integrations/credentials.py).
    creds = {k: v for k, v in (data.credentials or {}).items() if v}
    try:
        integration.credentials = await store_credentials(data.platform, creds)
    except ValueError as exc:
        # A caller-supplied @secret: reference. Refused there because a stored
        # pointer at somebody else's vault entry is read by resolve_credentials
        # and deleted by disconnect -- see store_credentials.
        raise HTTPException(status_code=422, detail=str(exc))
    db.add(integration)
    try:
        await db.commit()
    except IntegrityError:
        # The SELECT above is not a lock. Two admins connecting the same vendor
        # at once both saw "no existing row" and both inserted, giving one
        # platform two enabled integrations -- after which every resident report
        # was pushed to the county twice, as two records. The unique index added
        # in 7d73fe63d6e3 makes the second insert fail; the answer an admin
        # should see is the same 409 the SELECT would have produced.
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"An integration for {data.platform} already exists")
    await db.refresh(integration)
    from app.core.sanitize import sanitize_for_log
    logger.info(f"[Integrations] {sanitize_for_log(current_user.username)} created integration {sanitize_for_log(data.platform)}")
    return _serialize(integration)


@router.put("/{integration_id}")
async def update_integration(
    integration_id: int,
    data: IntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    integration = await _get_integration(db, integration_id)
    _reject_unknown_keys(integration.platform, data.credentials, data.config)

    if data.display_name is not None:
        integration.display_name = data.display_name
    if data.enabled is not None:
        integration.enabled = data.enabled
    if data.sync_direction is not None:
        integration.sync_direction = data.sync_direction
    if data.config is not None:
        # An explicit null deletes the key. Config was merged and the frontend
        # skipped empty strings, so between them there was no way to blank a
        # setting at all: a jurisdiction_id typed by mistake stayed in the
        # payload of every push forever, and the only remedy was disconnecting
        # the integration and re-entering every credential.
        merged = {**(integration.config or {}), **data.config}
        integration.config = {k: v for k, v in merged.items() if v is not None}
    if data.credentials:
        # Only the fields the admin actually filled in are (re)written to the
        # vault; blanks mean "keep existing" and untouched fields keep their
        # stored @secret: reference. store_credentials returns references for
        # what it wrote to the vault, raw values only as an encrypted-DB fallback.
        changed = {k: v for k, v in data.credentials.items() if v}
        if changed:
            try:
                stored = await store_credentials(integration.platform, changed)
            except ValueError as exc:
                # A caller-supplied @secret: reference — same refusal as create.
                raise HTTPException(status_code=422, detail=str(exc))
            merged = dict(integration.credentials or {})
            merged.update(stored)
            integration.credentials = merged

    integration.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(integration)
    from app.core.sanitize import sanitize_for_log
    logger.info(f"[Integrations] {sanitize_for_log(current_user.username)} updated integration {sanitize_for_log(integration.platform)}")
    return _serialize(integration)


@router.delete("/{integration_id}")
async def delete_integration(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    integration = await _get_integration(db, integration_id)
    platform = integration.platform
    # Read before the delete: after it, the row is gone and so is the only record
    # of which vault entries belonged to it.
    stored = dict(integration.credentials or {})
    await db.delete(integration)
    await db.commit()
    # Disconnecting left the vendor's client secret and agency password sitting
    # in the town's Secret Manager under INTEGRATION_<PLATFORM>_<FIELD>, with
    # nothing left in the UI referring to them -- so a credential an admin
    # believes they revoked by pressing Disconnect stayed live and unlisted.
    # Best-effort: the integration is already gone, and failing the request now
    # would tell the admin the disconnect did not happen when it did.
    await _forget_vault_secrets(platform, stored)
    logger.info(f"[Integrations] {current_user.username} deleted integration {platform}")
    return {"message": "Integration deleted", "platform": platform}


async def _forget_vault_secrets(platform: str, stored: Dict[str, Any]) -> None:
    """Delete the Secret Manager entries a disconnected integration wrote.

    Only the entries it *wrote*: names are recomputed from the platform and
    field, never taken from wherever a stored reference happens to point. A
    reference is a pointer, and a row that carried
    ``@secret:GCP_SERVICE_ACCOUNT_JSON`` would otherwise turn Disconnect into
    deleting the platform key -- outside the reject_platform_key_writes gate,
    because this path talks to the vault directly.
    """
    from app.core.sanitize import sanitize_for_log
    from app.integrations.credentials import owned_secret_names

    names = owned_secret_names(platform, stored)
    if not names:
        return
    try:
        from app.services.secret_manager import clear_cache, delete_secret
    except Exception:
        logger.warning("[Integrations] no secret manager available to clean up "
                       "%s credentials", sanitize_for_log(platform))
        return
    for name in sorted(names):
        try:
            await delete_secret(name)
            clear_cache(key_name=name)
            logger.info("[Integrations] removed vault entry %s on disconnect",
                        sanitize_for_log(name))
        except Exception as exc:
            # Named, so somebody can remove it by hand. Never the value.
            logger.warning("[Integrations] could not remove vault entry %s: %s",
                           sanitize_for_log(name), sanitize_for_log(str(exc)))


# ---------- Actions ----------

def _friendly_test_error(error: str) -> str:
    """Translate a technical connection error into plain language a
    non-technical admin can act on."""
    text = error.lower()
    # Before the credential-specific advice below: the fields are not blank, and
    # telling somebody to re-enter them here overwrites working vault references
    # with whatever they retype.
    if "secret manager" in text and "could not read" in text:
        return ("The credentials are saved, but we couldn't read them from your "
                "Secret Manager just now. Nothing here needs re-entering — check "
                "that the vault is reachable and that this system still has "
                "permission to read it, then try again.")
    # Checked ahead of the generic 401/403 branch: a dead refresh token comes
    # back as a 400 from the token endpoint, and "check your password" is the
    # wrong advice for a connection that has no password.
    if "is not signed in" in text or "oauth2 refresh" in text:
        return ("This connection isn't signed in to Accela any more — the authorization "
                "may have been revoked or expired there. Open Settings and sign in again.")
    if "http 401" in text or "http 403" in text or "unauthorized" in text or "forbidden" in text:
        return ("The platform refused the sign-in details. Double-check the key or "
                "username/password — copy and paste them again with no extra spaces.")
    if "http 404" in text:
        return ("We reached their server, but the web address looks incomplete or "
                "slightly wrong. Compare it letter-for-letter with what the vendor sent you.")
    if "http 429" in text:
        return "The platform says we're connecting too often. Wait a few minutes and try again."
    if "http 5" in text:
        return ("Their system had a problem on its end. This usually isn't your setup — "
                "wait a few minutes and try again, or check with the vendor.")
    if "timed out" in text or "timeout" in text:
        return ("Their system didn't answer in time. Check the web address for typos; "
                "if it looks right, try again in a few minutes.")
    if ("name or service not known" in text or "getaddrinfo" in text
            or "nodename" in text or "resolve" in text or "connecterror" in text
            or "connection refused" in text or "all connection attempts failed" in text):
        return ("We couldn't find a system at that web address. Check it for typos — "
                "it should start with https:// and match what the vendor sent exactly.")
    if "certificate" in text or "ssl" in text:
        return ("There's a security-certificate problem with that address. Make sure it "
                "starts with https:// — if it does, ask the vendor about their certificate.")
    if "requires config.base_url" in text or "no api base url" in text:
        return "The web address (base URL) is missing. Paste the one the vendor sent you."
    if "no feature layer url" in text:
        return ("The feature layer address is missing. Paste the layer URL from ArcGIS — "
                "it ends in a number, like /FeatureServer/0.")
    if "arcgis rejected the credentials" in text:
        return ("ArcGIS refused the key or account. Check that it has editing rights on "
                "that layer, and that the layer is shared with it.")
    if "credentials missing" in text or "requires agency_name" in text or "requires record_type" in text:
        return "Some required fields are still blank — go back one step and fill them in."
    return ("Something didn't work. The technical details below may help the vendor's "
            "support team figure it out.")


@router.post("/{integration_id}/test")
@limiter.limit("10/minute")  # live vendor API call
async def test_integration(
    request: Request,
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    integration = await _get_integration(db, integration_id)
    from app.services.connector_verification import check_integration_now

    # The check itself lives in a service so it records health and clears the
    # breaker the same way wherever it is called from. This endpoint used to
    # write an IntegrationSyncLog row and nothing else, so an admin could watch
    # a test pass while the card still said "not checked yet" -- the only writer
    # of govtech health was the resident-report push path.
    result = await check_integration_now(db, integration)
    # The provider test endpoint does the same before it writes, and for the same
    # reason: a check that failed part-way can leave this session in a failed
    # transaction, and every statement after that raises PendingRollbackError --
    # so the sync-log write below would be lost and the 500 would replace a
    # perfectly good "here is what went wrong". Health is written on its own
    # session and is already safe from this.
    try:
        await db.rollback()
    except Exception:
        pass
    if result.get("ok"):
        # `verifiable` alongside `verified`, so the admin UI can derive a card's
        # state with one function for both surfaces rather than two that drift.
        if result.get("verified") is not None:
            result = {**result, "verifiable": result["verified"]}
        log_status, detail = "success", str(result.get("detail") or "OK")
        # A warning means the credentials are fine but something still blocks a
        # report. Keeping it out of the activity trail is how it gets forgotten
        # between the wizard closing and the first rejected report.
        if result.get("warnings"):
            log_status = "warning"
            detail = detail + " — " + " ".join(result["warnings"])
    else:
        detail = str(result.get("detail") or "")
        result = {**result, "friendly": _friendly_test_error(detail)}
        log_status = "error"

    db.add(IntegrationSyncLog(
        # The path parameter, not `integration.id`. The rollback above expires
        # every instance in this session, so reading an attribute off the ORM
        # object here re-loads it -- synchronous IO inside async attribute
        # access, which raises MissingGreenlet and turns the whole endpoint into
        # a 500. The admin then sees "Something went wrong running the check"
        # instead of the vendor's actual complaint, which is the one piece of
        # information that would let them fix their connection. _get_integration
        # already 404'd if this id did not exist, so it is the same number.
        integration_id=integration_id, operation="test", status=log_status, detail=detail[:2000]
    ))
    await db.commit()
    return result


@router.post("/{integration_id}/sync")
@limiter.limit("10/minute")
async def trigger_sync(
    request: Request,
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    integration = await _get_integration(db, integration_id)
    if not integration.enabled:
        raise HTTPException(status_code=400, detail="Enable the integration before syncing")
    # "Sync started" has to be true. This endpoint exists to start the job, so
    # a broker that cannot take it is a failed request, not a quiet log line --
    # otherwise an admin watches nothing happen and has no way to tell whether
    # the sync ran and found nothing or never ran at all.
    #
    # Scoped to the clicked integration. It used to enqueue the global beat
    # tasks, so pressing the button on one card polled every vendor the town
    # uses.
    from app.tasks.integrations import pull_integration_comments, pull_integration_updates
    # Both are enqueued before either result is judged. Written as
    # `enqueue(a) or enqueue(b)`, a first failure short-circuited and never
    # queued the second, and a second failure returned 503 after the first job
    # had already started -- so "this job did not start. Nothing has been
    # changed." was untrue in exactly the case it was meant to cover.
    started = {
        "updates": enqueue(pull_integration_updates, integration.id),
        "comments": enqueue(pull_integration_comments, integration.id),
    }
    if not any(started.values()):
        raise HTTPException(status_code=503, detail=QUEUE_UNAVAILABLE)
    if all(started.values()):
        return {"message": "Sync started", "platform": integration.platform,
                "started": started}
    # Partly started, which is neither of the two answers this endpoint had.
    # Naming what did run beats a 503 whose text says nothing has been changed,
    # in the one case where something has.
    ran = ", ".join(sorted(k for k, ok in started.items() if ok))
    return {
        "message": f"Sync partly started ({ran}). The rest could not be queued — "
                   f"check that the worker and Redis are running, then try again.",
        "platform": integration.platform,
        "started": started,
    }


@router.post("/{integration_id}/sync-assets")
@limiter.limit("6/minute")
async def trigger_asset_sync(
    request: Request,
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Run the asset inventory sync immediately (also runs daily via Beat)."""
    integration = await _get_integration(db, integration_id)
    if not integration.enabled:
        raise HTTPException(status_code=400, detail="Enable the integration before syncing")
    catalog = PLATFORM_CATALOG.get(integration.platform, {})
    if "assets" not in catalog.get("capabilities", []):
        raise HTTPException(status_code=400, detail=f"{integration.platform} does not support asset sync")
    # The catalog says what the platform *can* do; the built connector says what
    # this configuration actually does. For generic_rest they differ: asset sync
    # needs an assets_path, and without one the task would skip the run after
    # this endpoint had already answered "Asset sync started".
    try:
        connector = await build_connector_for(integration)
    except Exception as e:
        raise HTTPException(status_code=400, detail=_friendly_test_error(str(e)))
    if "assets" not in connector.capabilities:
        raise HTTPException(
            status_code=400,
            detail=("This connection has no asset endpoint configured, so there is "
                    "nothing to sync. Add the asset inventory path from your "
                    "vendor's API docs and try again."),
        )
    # Deliberately does not touch config. Pressing this button used to set
    # config["sync_assets"] = True, which enrolled the integration in the nightly
    # beat job permanently -- from one click, with nothing on screen saying so and
    # no way to undo it. `sync_assets` is a config field in the wizard now, so
    # opting into the nightly sync is a choice somebody makes and can see.
    from app.tasks.integrations import sync_integration_assets
    if not enqueue(sync_integration_assets, integration.id):
        raise HTTPException(status_code=503, detail=QUEUE_UNAVAILABLE)
    return {"message": "Asset sync started", "platform": integration.platform}


@router.post("/{integration_id}/regenerate-webhook-token")
@limiter.limit("6/minute")
async def regenerate_webhook_token(
    request: Request,
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Issue a new inbound webhook token, invalidating the old one.

    The token is in the URL path, which is where a URL's secrets are least well
    kept: it lands in reverse-proxy access logs, in the vendor's own outbound
    request logs, and in any screenshot of the setup page. There was no way to
    rotate it -- so a token disclosed that way was disclosed permanently, and the
    only remedy was deleting the integration and re-entering every credential.

    The old token stops working the moment this returns, so the vendor has to be
    given the new URL. That is stated plainly in the response rather than left
    for somebody to discover from a silent gap in inbound records.
    """
    integration = await _get_integration(db, integration_id)
    integration.webhook_token = pysecrets.token_urlsafe(32)
    integration.updated_at = datetime.now(timezone.utc)
    db.add(IntegrationSyncLog(
        integration_id=integration.id, operation="webhook_token_rotated",
        status="success",
        detail=f"Rotated by {current_user.username}. The previous URL no longer works.",
    ))
    await db.commit()
    await db.refresh(integration)
    from app.core.sanitize import sanitize_for_log
    logger.info("[Integrations] %s rotated the webhook token for %s",
                sanitize_for_log(current_user.username),
                sanitize_for_log(integration.platform))
    return {
        **_serialize(integration),
        "message": ("New webhook address issued. The previous one stopped working "
                    "immediately — send the new address to your vendor, or they will "
                    "keep posting to an address that now refuses them."),
    }


@router.post("/requests/{request_id}/refresh")
@limiter.limit("20/minute")
async def refresh_request_work_order(
    request: Request,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff),
):
    """Pull the latest work-order state (assignment, schedule, status,
    resolution) for a single request from every platform it's linked to.
    Staff-triggered on-demand refresh — complements the scheduled pull.

    Department-scoped like every other by-id staff endpoint: this writes the
    external system's assignment, schedule and resolution onto the request."""
    from app.api.scoping import scoped_request

    sr = await scoped_request(db, current_user, service_request_id=request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="Request not found")
    links = (await db.execute(
        select(IntegrationLink).where(IntegrationLink.service_request_id == sr.id)
    )).scalars().all()
    if not links:
        return {"ok": False, "detail": "This request isn't linked to any external platform."}
    from app.tasks.integrations import refresh_request_from_integrations
    if not enqueue(refresh_request_from_integrations, sr.id):
        # Answered as ok:false rather than raised, matching the "not linked to
        # any platform" case a few lines above -- this endpoint's contract is
        # an {ok, detail} pair the staff dashboard renders inline.
        return {"ok": False, "detail": QUEUE_UNAVAILABLE}
    return {"ok": True, "detail": "Refreshing the latest work-order status — updates appear on the request in a moment."}


# ---------- Accela authorization-code sign-in ----------
#
# Accela's callback lands as a plain browser redirect with no Authorization
# header, so the callback route cannot be admin-gated the way every other route
# here is. The signed ``state`` minted by /accela/oauth/start — which *is*
# admin-gated — is what authorizes it: without a valid, unexpired signature
# bound to a specific integration, the callback refuses to store anything. That
# closes the login-CSRF hole where an attacker feeds an admin their own
# authorization code and quietly binds the town's Accela sync to their account.

class AccelaOAuthStart(BaseModel):
    integration_id: int


@router.get("/accela/oauth/status")
async def accela_oauth_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Whether this deployment can offer Accela sign-in, and the exact callback
    URL to register on the developer-portal app."""
    from app.integrations import accela_oauth
    return {
        "configured": await accela_oauth.is_configured(),
        "redirect_uri": await accela_oauth.redirect_uri_for(db, str(request.base_url)),
        "scope": accela_oauth.DEFAULT_SCOPE,
    }


@router.post("/accela/oauth/start")
@limiter.limit("10/minute")
async def accela_oauth_start(
    request: Request,
    data: AccelaOAuthStart,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Begin the Accela authorization-code flow: returns the URL to send the
    admin's browser to, carrying a signed single-purpose state token."""
    from app.integrations import accela_oauth

    integration = await _get_integration(db, data.integration_id)
    if integration.platform != "accela":
        raise HTTPException(status_code=400, detail="This connection is not an Accela connection")

    client_id, _secret = await accela_oauth.app_credentials()
    if not await accela_oauth.is_configured():
        raise HTTPException(
            status_code=503,
            detail=("Accela sign-in isn't available on this deployment yet — no Accela "
                    "app is configured. Ask your administrator to set ACCELA_CLIENT_ID "
                    "and ACCELA_CLIENT_SECRET, or use the username and password option."),
        )

    agency_name = (integration.config or {}).get("agency_name")
    if not agency_name:
        raise HTTPException(status_code=400, detail="Enter your Accela agency name first")

    redirect_uri = await accela_oauth.redirect_uri_for(db, str(request.base_url))
    state = accela_oauth.sign_state(integration.id, current_user.id, redirect_uri)
    url = accela_oauth.authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        agency_name=str(agency_name),
        environment=str((integration.config or {}).get("environment") or "PROD"),
        config=integration.config or {},
    )
    from app.core.sanitize import sanitize_for_log
    logger.info("[Integrations] %s started Accela OAuth sign-in for agency %s",
                sanitize_for_log(current_user.username), sanitize_for_log(str(agency_name)))
    return {"authorize_url": url, "redirect_uri": redirect_uri}


def _oauth_result_page(ok: bool, message: str) -> HTMLResponse:
    """The tiny page Accela redirects back into. It tells the opener how things
    went and closes itself; the wizard behind it picks up from there."""
    import html as _html
    safe = _html.escape(message)
    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Accela sign-in</title></head>
<body style="font-family:system-ui,sans-serif;background:#0b1020;color:#e8ecf8;
             display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
  <div style="max-width:26rem;text-align:center;padding:2rem">
    <p style="font-size:1.05rem;font-weight:600;margin:0 0 .5rem">
      {'Accela is connected' if ok else 'Accela sign-in did not finish'}</p>
    <p style="opacity:.75;font-size:.9rem;margin:0">{safe}</p>
    <p style="opacity:.5;font-size:.8rem;margin-top:1.5rem">You can close this window.</p>
  </div>
  <script>
    try {{
      if (window.opener) {{
        window.opener.postMessage(
          {{source: "pinpoint-accela-oauth", ok: {str(bool(ok)).lower()}}},
          window.location.origin
        );
        setTimeout(function () {{ window.close(); }}, {1200 if ok else 4000});
      }}
    }} catch (e) {{ /* opener gone or cross-origin — the message above stands on its own */ }}
  </script>
</body></html>"""
    return HTMLResponse(content=body, status_code=200 if ok else 400)


@router.get("/accela/oauth/callback", include_in_schema=False)
@limiter.limit("20/minute")
async def accela_oauth_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Where Accela sends the admin back after they sign in and consent.

    Deliberately unauthenticated — see the note above; the signed state is the
    authorization. Always answers with a page rather than JSON, because a human
    browser is what lands here.
    """
    from app.integrations import accela_oauth

    if error:
        return _oauth_result_page(False, "Accela reported that the sign-in was cancelled or refused.")
    if not code or not state:
        return _oauth_result_page(False, "Accela's response was missing the sign-in code.")

    payload = accela_oauth.verify_state(state)
    if not payload:
        logger.warning("[Integrations] Rejected Accela OAuth callback with an invalid or expired state")
        return _oauth_result_page(
            False,
            "This sign-in link is no longer valid. Start the connection again from "
            "Settings and finish signing in within ten minutes.",
        )

    integration = (await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.id == payload["iid"])
    )).scalar_one_or_none()
    if not integration or integration.platform != "accela":
        return _oauth_result_page(False, "That Accela connection no longer exists.")

    # The redirect URI is signed into the state, so the exchange reuses exactly
    # the value the authorize request was issued with — Accela rejects any drift.
    try:
        tokens = await accela_oauth.exchange_code(
            code=code,
            redirect_uri=payload.get("ru") or await accela_oauth.redirect_uri_for(db, str(request.base_url)),
            config=integration.config or {},
        )
    except Exception as e:
        from app.core.sanitize import sanitize_for_log
        logger.error("[Integrations] Accela code exchange failed: %s", sanitize_for_log(str(e)))
        db.add(IntegrationSyncLog(
            integration_id=integration.id, operation="oauth", status="error", detail=str(e)[:2000]
        ))
        await db.commit()
        return _oauth_result_page(False, str(e)[:300])

    stored = await store_credentials("accela", {"refresh_token": tokens["refresh_token"]})
    merged = dict(integration.credentials or {})
    merged.update(stored)
    # The refresh token supersedes the password fallback — leaving a government
    # password in the vault after it is no longer needed is exactly what this
    # flow exists to avoid.
    for field in ("username", "password"):
        merged.pop(field, None)
    integration.credentials = merged
    integration.config = {
        **(integration.config or {}),
        "auth_mode": "authorization_code",
    }
    integration.updated_at = datetime.now(timezone.utc)
    db.add(IntegrationSyncLog(
        integration_id=integration.id, operation="oauth", status="success",
        detail=f"Authorized via Accela sign-in (scope: {accela_oauth.scope_for(integration.config)})",
    ))
    await db.commit()

    # Any access token cached against the old authorization is now the wrong one.
    from app.integrations.connectors.accela import _clear_token_cache
    _clear_token_cache()

    logger.info("[Integrations] Accela authorization stored for integration %s", integration.id)
    return _oauth_result_page(True, "Pinpoint can now sync with Accela on your behalf.")


class MappingApproval(BaseModel):
    """A mapping an admin has looked at and accepted."""
    status_map_out: Optional[Dict[str, str]] = None
    status_map_in: Optional[Dict[str, str]] = None
    service_code_map: Optional[Dict[str, str]] = None


def _unknown_codes(mapping: Optional[Dict[str, str]], known: List[Dict[str, Any]]) -> List[str]:
    """Values in a mapping that the vendor's own list does not contain.

    Only meaningful when there IS a list. A vendor that publishes none gets an
    empty `known` and nothing is rejected -- refusing a code because we could
    not check it would make the honest "we don't know" state unusable.
    """
    if not mapping or not known:
        return []
    codes = {str(item.get("code")) for item in known if isinstance(item, dict)}
    return sorted({str(v) for v in mapping.values() if str(v) not in codes})


@router.post("/{integration_id}/lookups/refresh")
@limiter.limit("10/minute")  # live vendor API call
async def refresh_integration_lookups(
    request: Request,
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Pull this vendor's own code lists down and keep them.

    A mapping is a promise about codes that live in the vendor's data -- this
    town's service codes, this layer's status domain -- and nothing published
    anywhere says what they are. Typed from memory, a wrong one is not an
    error: it is a status that silently never maps, or a 422 on the first real
    report. Hydrated, the admin picks from their own live values.

    Only where the vendor genuinely publishes such a list to a call the
    connector already makes. Where they do not, this says so plainly rather
    than offering a menu that is not the truth.
    """
    integration = await _get_integration(db, integration_id)
    try:
        connector = await build_connector_for(integration)
    except Exception as e:
        raise HTTPException(status_code=400, detail=_friendly_test_error(str(e)))
    if "lookups" not in connector.capabilities:
        return {
            "ok": False,
            "supported": False,
            "detail": (f"{PLATFORM_CATALOG.get(integration.platform, {}).get('name', integration.platform)} "
                       "does not publish a list of its own codes, so the mapping has to be "
                       "entered from what the vendor told you."),
        }
    from app.services import connector_health
    from app.services.connector_verification import health_key

    try:
        lookups = await connector.pull_lookups()
    except Exception as e:
        # Recorded like any other real call to this vendor -- a hydration that
        # fails on an expired credential is the same evidence as a failed push.
        await connector_health.record_failure(
            db, health_key(integration.platform), e, provider=integration.platform)
        detail = connector_health.clean_error(e)
        raise HTTPException(status_code=502, detail=_friendly_test_error(detail) + f" ({detail})")

    integration.lookups_cache = lookups
    integration.lookups_fetched_at = datetime.now(timezone.utc)
    db.add(IntegrationSyncLog(
        integration_id=integration.id, operation="lookups", status="success",
        detail=", ".join(f"{name}: {len(items)}" for name, items in lookups.items()
                         if isinstance(items, list))[:2000],
    ))
    await db.commit()
    await db.refresh(integration)
    return {"ok": True, "supported": True, "lookups": lookups,
            "fetched_at": integration.lookups_fetched_at.isoformat()}


@router.post("/{integration_id}/mapping")
async def approve_integration_mapping(
    integration_id: int,
    data: MappingApproval,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Store a mapping somebody has actually looked at.

    Checked against the hydrated lists where there are any: a code the vendor
    does not have is refused here, by name, rather than becoming a 422 on the
    first real report or a status that quietly never maps.

    The approval is recorded separately from the mapping itself. An empty
    mapping an admin deliberately approved -- the vendor's words happen to match
    ours -- and one nobody has ever opened are the same JSON, and only one of
    them is a decision.
    """
    integration = await _get_integration(db, integration_id)
    lookups = integration.lookups_cache or {}

    problems = []
    for label, mapping, known in (
        ("status", data.status_map_out, lookups.get("statuses") or []),
        ("service code", data.service_code_map, lookups.get("services") or []),
    ):
        unknown = _unknown_codes(mapping, known)
        if unknown:
            problems.append(
                f"{label}(s) this vendor does not have: {', '.join(unknown)}")
    if problems:
        raise HTTPException(
            status_code=400,
            detail=("Checked against the list pulled from your vendor — "
                    + "; ".join(problems)
                    + ". Refresh the list if these were added at the vendor recently."),
        )

    config = dict(integration.config or {})
    for key, value in (("status_map_out", data.status_map_out),
                       ("status_map_in", data.status_map_in),
                       ("service_code_map", data.service_code_map)):
        if value is not None:
            config[key] = value
    integration.config = config
    integration.mapping_approved_at = datetime.now(timezone.utc)
    integration.mapping_approved_by = current_user.username[:100]
    integration.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(integration)
    return _serialize(integration)


class BacklogDiscard(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


@router.get("/{integration_id}/backlog")
async def get_push_backlog(
    integration_id: int,
    include_resolved: bool = False,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Reports and updates that have not reached this vendor yet.

    The sync log says what happened; this says what is still owed. They are
    different questions and the log could only ever answer the first, which is
    why a failed push used to be indistinguishable from a push that never
    happened.
    """
    await _get_integration(db, integration_id)
    query = (
        select(IntegrationDeadLetter, ServiceRequest.service_request_id)
        .outerjoin(ServiceRequest,
                   IntegrationDeadLetter.service_request_id == ServiceRequest.id)
        .where(IntegrationDeadLetter.integration_id == integration_id)
        .order_by(IntegrationDeadLetter.first_failed_at.desc())
        .limit(min(max(1, limit), 500))
    )
    if not include_resolved:
        query = query.where(IntegrationDeadLetter.resolved_at.is_(None))
    try:
        rows = (await db.execute(query)).all()
    except Exception:
        # Migration pending. An empty backlog is the honest answer here: there
        # is no table, so nothing has been recorded in one.
        await db.rollback()
        return []
    return [
        {
            "id": item.id,
            "operation": item.operation,
            "request_id": public_id,
            "comment_id": item.comment_id,
            "attempts": item.attempts,
            # Already scrubbed on the way in by tasks.integrations._safe_error.
            "last_error": item.last_error,
            "first_failed_at": item.first_failed_at.isoformat() if item.first_failed_at else None,
            "last_attempt_at": item.last_attempt_at.isoformat() if item.last_attempt_at else None,
            "next_attempt_at": item.next_attempt_at.isoformat() if item.next_attempt_at else None,
            # No further automatic attempt is scheduled. Not "given up" -- the
            # row is still here -- but it needs somebody to decide.
            "stalled": item.resolved_at is None and item.next_attempt_at is None,
            "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None,
            "resolution": item.resolution,
            "resolution_note": item.resolution_note,
        }
        for item, public_id in rows
    ]


async def _open_backlog_item(db: AsyncSession, integration_id: int, item_id: int):
    item = (await db.execute(
        select(IntegrationDeadLetter).where(
            IntegrationDeadLetter.id == item_id,
            IntegrationDeadLetter.integration_id == integration_id,
        )
    )).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="No such item in this connection's backlog")
    if item.resolved_at is not None:
        raise HTTPException(
            status_code=409,
            detail=("That item is already closed — it either went through or was "
                    "discarded. Reload the list to see its current state."),
        )
    return item


@router.post("/{integration_id}/backlog/{item_id}/retry")
@limiter.limit("20/minute")
async def retry_backlog_item(
    request: Request,
    integration_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Try this one again now, rather than waiting out its backoff.

    The point of the button is the case the schedule cannot know about: somebody
    has just fixed the credential, or the vendor has just come back, and the
    next automatic attempt is six hours away. It also un-stalls an item that has
    run out of automatic attempts, which is the only way one moves again.
    """
    integration = await _get_integration(db, integration_id)
    if not integration.enabled:
        raise HTTPException(
            status_code=400,
            detail="Turn this connection on before retrying — a disabled connection is not pushed to.")
    item = await _open_backlog_item(db, integration_id, item_id)
    # Reset the clock rather than the attempt count. The count is the history of
    # how hard this has been, and an admin pressing Retry does not un-happen the
    # eight failures behind it.
    item.next_attempt_at = datetime.now(timezone.utc)
    await db.commit()

    from app.tasks.integrations import retry_integration_dead_letters
    if not enqueue(retry_integration_dead_letters, 50):
        # Rescheduled but not started: the row is due now and the beat will take
        # it within ten minutes. Saying so beats a 503 that implies nothing
        # happened, because something did.
        return {"ok": True, "started": False, "detail": QUEUE_UNAVAILABLE}
    from app.core.sanitize import sanitize_for_log
    logger.info("[Integrations] %s retried backlog item %s on %s",
                sanitize_for_log(current_user.username), item_id,
                sanitize_for_log(integration.platform))
    return {"ok": True, "started": True,
            "detail": "Trying again now — the result appears in the activity trail."}


@router.post("/{integration_id}/backlog/{item_id}/discard")
@limiter.limit("20/minute")
async def discard_backlog_item(
    request: Request,
    integration_id: int,
    item_id: int,
    data: BacklogDiscard,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Decide this one should not be sent after all.

    A reason is required, and the row is kept rather than deleted. "This report
    never reached the county and we chose not to send it" is a decision about a
    public record, and it needs a name and a sentence against it -- which is
    also the difference between this and the silent drop it replaces.
    """
    await _get_integration(db, integration_id)
    item = await _open_backlog_item(db, integration_id, item_id)
    item.resolved_at = datetime.now(timezone.utc)
    item.resolution = "discarded"
    item.resolved_by = current_user.username[:100]
    item.resolution_note = data.reason
    item.next_attempt_at = None
    db.add(IntegrationSyncLog(
        integration_id=integration_id, operation=item.operation, status="warning",
        detail=(f"Backlog item {item_id} discarded by {current_user.username} "
                f"after {item.attempts} attempt(s): {data.reason}")[:2000],
    ))
    await db.commit()
    return {"ok": True, "detail": "Removed from the backlog and recorded in the activity trail."}


@router.get("/{integration_id}/logs")
async def get_sync_logs(
    integration_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    await _get_integration(db, integration_id)
    logs = (await db.execute(
        select(IntegrationSyncLog)
        .where(IntegrationSyncLog.integration_id == integration_id)
        .order_by(IntegrationSyncLog.created_at.desc())
        .limit(min(limit, 200))
    )).scalars().all()
    return [
        {
            "id": entry.id,
            "operation": entry.operation,
            "status": entry.status,
            "detail": entry.detail,
            "request_count": entry.request_count,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
        for entry in logs
    ]


@router.get("/requests/{service_request_id}/links")
async def get_request_links(
    service_request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff),
):
    """External platform records linked to a service request (staff, own departments)."""
    from app.api.scoping import scoped_request

    sr = await scoped_request(db, current_user, service_request_id=service_request_id)
    if not sr:
        raise HTTPException(status_code=404, detail="Request not found")

    rows = (await db.execute(
        select(IntegrationLink, IntegrationConfig)
        .join(IntegrationConfig, IntegrationLink.integration_id == IntegrationConfig.id)
        .where(IntegrationLink.service_request_id == sr.id)
    )).all()
    return [
        {
            "platform": integration.platform,
            "platform_name": integration.display_name,
            "external_id": link.external_id,
            "external_status": link.external_status,
            "direction": link.direction,
            "last_pushed_at": link.last_pushed_at.isoformat() if link.last_pushed_at else None,
            "last_pulled_at": link.last_pulled_at.isoformat() if link.last_pulled_at else None,
            "sync_error": link.sync_error,
        }
        for link, integration in rows
    ]


# ---------- Inbound webhook (no session auth — token in path) ----------

def _webhook_rate_key(request: Request) -> str:
    """Rate-limit inbound webhooks per connection *and* source address.

    One vendor's egress IP serves every event for every town on their platform,
    so a bucket keyed on the IP alone meant a busy neighbour's traffic could
    exhaust the budget for ours -- and one misconfigured integration could not
    be throttled without throttling every connection sharing that IP. The path
    identifies the connection, so the token digest stays in the key.

    The address stays in it too. Keyed on the token alone, every *guessed*
    token minted a fresh bucket with a fresh budget -- an attacker
    brute-forcing this unauthenticated endpoint was never rate-limited at all,
    and each miss grew the limiter's in-memory store by one bucket, forever.
    """
    parts = [p for p in request.url.path.split("/") if p]
    # .../webhook/{platform}/{token} -- a digest of the token, so the bucket
    # name is per-connection without a credential ending up in the limiter's
    # store or its log lines.
    if len(parts) >= 2 and parts[-2]:
        import hashlib
        digest = hashlib.sha256(parts[-1].encode("utf-8", "replace")).hexdigest()[:16]
        return f"webhook:{parts[-2]}:{digest}:{client_ip(request)}"
    return f"webhook:{client_ip(request)}"


@router.post("/webhook/{platform}/{token}", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute", key_func=_webhook_rate_key)
async def integration_webhook(
    request: Request,
    platform: str,
    token: str,
    payload: WebhookRequestIn,
    db: AsyncSession = Depends(get_db),
):
    """Inbound intake from a connected platform.

    Creates a new service request (or updates the status of the already-linked
    one when the same external_id is posted again). Authenticated by the
    per-integration webhook token."""
    # Fetched by platform, then compared in Python with compare_digest. Matching
    # the token inside the SQL predicate makes the comparison the database's
    # byte-by-byte one, whose duration depends on how many leading characters are
    # right -- and this endpoint is unauthenticated and remotely timeable, which
    # is the whole precondition for extracting a token that way.
    # Catalog membership too, not only an enabled row. A platform removed from
    # the catalog (the practice sandbox, deleted 2026-07-20) can leave enabled
    # rows behind with live webhook tokens, and this endpoint is
    # unauthenticated -- an orphaned row must not stay a valid way in.
    if platform not in PLATFORM_CATALOG:
        raise HTTPException(status_code=404, detail="Unknown platform")
    integration = (await db.execute(
        select(IntegrationConfig).where(
            IntegrationConfig.platform == platform,
            IntegrationConfig.enabled == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not integration or not pysecrets.compare_digest(
            str(integration.webhook_token or ""), str(token)):
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    # A push-only connection is one the town configured to send and not receive.
    # Accepting inbound creates on it anyway meant a vendor could open service
    # requests in a town that had deliberately not asked them to -- and the
    # sync_direction setting the admin chose did nothing on this path.
    if integration.sync_direction == "push":
        raise HTTPException(
            status_code=403,
            detail=("This connection is set to send only. Change its sync direction "
                    "to 'pull' or 'bidirectional' to accept incoming records."),
        )

    async def _import_webhook_comments(service_request_pk: int) -> int:
        """Attach comments carried in the payload, deduped by external comment id."""
        imported = 0
        for wc in (payload.comments or []):
            ref = f"{integration.id}:{wc.external_id}" if wc.external_id else None
            if ref:
                exists = (await db.execute(
                    select(RequestComment.id).where(RequestComment.external_ref == ref)
                )).scalar_one_or_none()
                if exists:
                    continue
            db.add(RequestComment(
                service_request_id=service_request_pk,
                username=(wc.author or integration.display_name)[:100],
                content=wc.content,
                visibility="external",
                external_ref=ref or f"{integration.id}:webhook-{uuid_module.uuid4().hex[:12]}",
            ))
            imported += 1
        return imported

    # Existing link -> status update and/or comments
    link = (await db.execute(
        select(IntegrationLink).where(
            IntegrationLink.integration_id == integration.id,
            IntegrationLink.external_id == payload.external_id,
        )
    )).scalar_one_or_none()
    if link:
        sr = (await db.execute(
            select(ServiceRequest).where(ServiceRequest.id == link.service_request_id)
        )).scalar_one_or_none()
        comments_added = 0
        if sr:
            if payload.status and payload.status != sr.status:
                old_status = sr.status
                sr.status = payload.status
                sr.updated_datetime = datetime.now(timezone.utc)
                if payload.status == "closed":
                    sr.closed_datetime = datetime.now(timezone.utc)
                db.add(RequestAuditLog(
                    service_request_id=sr.id,
                    action="status_change",
                    old_value=old_status,
                    new_value=payload.status,
                    actor_type="integration",
                    actor_name=integration.display_name,
                ))
            comments_added = await _import_webhook_comments(sr.id)
            await db.commit()
        return {
            "message": "updated",
            "service_request_id": sr.service_request_id if sr else None,
            "comments_added": comments_added,
        }

    if not payload.description:
        raise HTTPException(
            status_code=400,
            detail="description is required when creating a new request (unknown external_id)",
        )

    # New record -> create a request
    service_code = payload.service_code or (integration.config or {}).get("default_local_service_code")
    service = None
    if service_code:
        service = (await db.execute(
            select(ServiceDefinition).where(
                ServiceDefinition.service_code == service_code,
                ServiceDefinition.is_active == True,  # noqa: E712
            )
        )).scalar_one_or_none()
    if not service:
        # Fall back to the first active service so intake never bounces
        service = (await db.execute(
            select(ServiceDefinition).where(ServiceDefinition.is_active == True).limit(1)  # noqa: E712
        )).scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=400, detail="No active service categories configured")

    from app.api.open311 import generate_request_id
    sr = ServiceRequest(
        service_request_id=generate_request_id(),
        service_code=service.service_code,
        service_name=service.service_name,
        description=payload.description,
        address=payload.address,
        lat=payload.lat,
        long=payload.long,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email or f"integration-{integration.platform}@intake.local",
        phone=payload.phone,
        media_urls=[u for u in (payload.media_urls or []) if isinstance(u, str) and u.startswith("http")][:3],
        source=f"integration_{integration.platform}",
        status=payload.status or "open",
        assigned_department_id=service.assigned_department_id,
    )
    db.add(sr)
    await db.commit()
    await db.refresh(sr)

    db.add(IntegrationLink(
        integration_id=integration.id,
        service_request_id=sr.id,
        external_id=payload.external_id,
        external_status=payload.status,
        direction="pulled",
        last_pulled_at=datetime.now(timezone.utc),
    ))
    db.add(RequestAuditLog(
        service_request_id=sr.id,
        action="submitted",
        new_value=sr.status,
        actor_type="integration",
        actor_name=integration.display_name,
    ))
    db.add(IntegrationSyncLog(
        integration_id=integration.id,
        operation="webhook",
        status="success",
        detail=f"{payload.external_id} -> {sr.service_request_id}",
        request_count=1,
    ))
    await _import_webhook_comments(sr.id)
    await db.commit()

    # Same post-processing as portal submissions (AI triage). Incidental: the
    # request is committed above, and a webhook sender that gets an error back
    # will redeliver, creating a duplicate report.
    from app.tasks.service_requests import analyze_request
    enqueue(analyze_request, sr.id)

    return {"message": "created", "service_request_id": sr.service_request_id}
