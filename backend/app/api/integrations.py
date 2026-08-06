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
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin, get_current_staff
from app.db.session import get_db
from app.services.enqueue import QUEUE_UNAVAILABLE, enqueue
from app.integrations import (
    PLATFORM_CATALOG, build_connector_for, store_credentials,
)
from app.models import (
    IntegrationConfig,
    IntegrationLink,
    IntegrationSyncLog,
    RequestAuditLog,
    RequestComment,
    ServiceDefinition,
    ServiceRequest,
    User,
)

limiter = Limiter(key_func=get_remote_address)
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


def _serialize(integration: IntegrationConfig) -> Dict[str, Any]:
    catalog = PLATFORM_CATALOG.get(integration.platform, {})
    return {
        "id": integration.id,
        "platform": integration.platform,
        "platform_name": catalog.get("name", integration.platform),
        "display_name": integration.display_name,
        "enabled": integration.enabled,
        "sync_direction": integration.sync_direction,
        "config": integration.config or {},
        # Never return secret values — only which keys are set
        "configured_credentials": sorted((integration.credentials or {}).keys()),
        # A stored refresh token means the admin completed the vendor's own
        # sign-in, so the UI can say "signed in" instead of asking for one again.
        "oauth_connected": bool((integration.credentials or {}).get("refresh_token")),
        # True when the stored credentials are Secret Manager references (the raw
        # secret lives only in the vault, not this database) — lets the UI show a
        # "stored in your Secret Manager" trust signal for government deployments.
        "credentials_vaulted": any(
            isinstance(v, str) and v.startswith("@secret:")
            for v in (integration.credentials or {}).values()
        ),
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
    return [_serialize(i) for i in integrations]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_integration(
    data: IntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    if data.platform not in PLATFORM_CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {data.platform}")

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
    integration.credentials = await store_credentials(data.platform, creds)
    db.add(integration)
    await db.commit()
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

    if data.display_name is not None:
        integration.display_name = data.display_name
    if data.enabled is not None:
        integration.enabled = data.enabled
    if data.sync_direction is not None:
        integration.sync_direction = data.sync_direction
    if data.config is not None:
        integration.config = {**(integration.config or {}), **data.config}
    if data.credentials:
        # Only the fields the admin actually filled in are (re)written to the
        # vault; blanks mean "keep existing" and untouched fields keep their
        # stored @secret: reference. store_credentials returns references for
        # what it wrote to the vault, raw values only as an encrypted-DB fallback.
        changed = {k: v for k, v in data.credentials.items() if v}
        if changed:
            stored = await store_credentials(integration.platform, changed)
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
    await db.delete(integration)
    await db.commit()
    logger.info(f"[Integrations] {current_user.username} deleted integration {platform}")
    return {"message": "Integration deleted", "platform": platform}


# ---------- Actions ----------

def _friendly_test_error(error: str) -> str:
    """Translate a technical connection error into plain language a
    non-technical admin can act on."""
    text = error.lower()
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
    try:
        connector = await build_connector_for(integration)
        result = await connector.test_connection()
        log_status, detail = "success", result.get("detail", "OK")
    except Exception as e:
        result = {"ok": False, "detail": str(e), "friendly": _friendly_test_error(str(e))}
        log_status, detail = "error", str(e)

    db.add(IntegrationSyncLog(
        integration_id=integration.id, operation="test", status=log_status, detail=detail[:2000]
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
    from app.tasks.integrations import pull_integration_comments, pull_integration_updates
    if not enqueue(pull_integration_updates) or not enqueue(pull_integration_comments):
        raise HTTPException(status_code=503, detail=QUEUE_UNAVAILABLE)
    return {"message": "Sync started", "platform": integration.platform}


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
    from app.tasks.integrations import _flag
    if not _flag(integration.config, "sync_assets"):
        integration.config = {**(integration.config or {}), "sync_assets": True}
        await db.commit()
    from app.tasks.integrations import sync_integration_assets
    if not enqueue(sync_integration_assets):
        raise HTTPException(status_code=503, detail=QUEUE_UNAVAILABLE)
    return {"message": "Asset sync started", "platform": integration.platform}


@router.post("/requests/{request_id}/refresh")
@limiter.limit("20/minute")
async def refresh_request_work_order(
    request: Request,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """Pull the latest work-order state (assignment, schedule, status,
    resolution) for a single request from every platform it's linked to.
    Staff-triggered on-demand refresh — complements the scheduled pull."""
    sr = (await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == request_id)
    )).scalar_one_or_none()
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
async def accela_oauth_status(request: Request, _: User = Depends(get_current_admin)):
    """Whether this deployment can offer Accela sign-in, and the exact callback
    URL to register on the developer-portal app."""
    from app.integrations import accela_oauth
    return {
        "configured": await accela_oauth.is_configured(),
        "redirect_uri": await accela_oauth.redirect_uri_for(str(request.base_url)),
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

    redirect_uri = await accela_oauth.redirect_uri_for(str(request.base_url))
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
            redirect_uri=payload.get("ru") or await accela_oauth.redirect_uri_for(str(request.base_url)),
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
    _: User = Depends(get_current_staff),
):
    """External platform records linked to a service request (staff view)."""
    sr = (await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == service_request_id)
    )).scalar_one_or_none()
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

@router.post("/webhook/{platform}/{token}", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
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
    integration = (await db.execute(
        select(IntegrationConfig).where(
            IntegrationConfig.platform == platform,
            IntegrationConfig.webhook_token == token,
            IntegrationConfig.enabled == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

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
