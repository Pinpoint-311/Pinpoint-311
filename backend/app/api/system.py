from fastapi import (APIRouter, BackgroundTasks, Body, Depends, HTTPException, status, UploadFile,
                     File, Request, Query)
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Any, List, Optional, Dict
from pydantic import BaseModel
import subprocess
import os
import uuid
import logging
import aiofiles

logger = logging.getLogger(__name__)

from app.db.session import get_db
from app.models import SystemSettings, SystemSecret, ServiceRequest, User, DisclaimerAcknowledgment, AuditLog
from app.schemas import (
    SystemSettingsBase, SystemSettingsResponse,
    SecretCreate, SecretResponse,
    StatisticsResponse
)
from app.core.auth import get_current_admin, get_current_staff
from app.services.system_settings import get_settings as read_settings_row
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()

# Tighter per-route limits for endpoints that call paid Google APIs, on top of
# the app-wide default limit. Decorator-based enforcement (own in-memory store).
_cost_limiter = Limiter(key_func=get_remote_address)


# ============ Settings ============

@router.get("/settings", response_model=SystemSettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Get system settings (public - for branding)"""
    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    if not settings:
        # Create default settings if none exist
        settings = SystemSettings()
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def public_origin(db) -> Optional[str]:
    """The address residents actually use, or None if nothing has set one.

    Setup instructions hand out callback and redirect URLs to paste into a
    vendor console, and until now those were built from `window.location.origin`
    -- whatever the admin happened to type into their own browser. An admin on
    `http://10.0.0.7:3000`, or on a hostname that only resolves inside the
    town's network, registered a URL the identity provider can never redirect
    to. The password is accepted and the login then fails on the redirect, which
    reads as a wrong secret rather than a wrong URL.

    The deployment already knows its real address in two places, so this is a
    lookup rather than a new setting: the township's `custom_domain`, and the
    DOMAIN environment variable the compose file sets. Prefer the database,
    because that is the one an admin can change without a redeploy.
    """
    domain = os.environ.get("DOMAIN", "").strip()
    try:
        from sqlalchemy import select

        from app.models import SystemSettings

        row = (await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))).scalar_one_or_none()
        if row and (row.custom_domain or "").strip():
            domain = row.custom_domain.strip()
    except Exception:
        # Advisory only. A failure here falls back to the browser's origin,
        # which is what happened before this existed.
        pass

    if not domain or domain == "localhost":
        return None
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")
    return f"https://{domain}"


@router.get("/config")
async def get_deployment_config(db: AsyncSession = Depends(get_db)):
    """Deployment-mode flags (public). The setup UI uses managed_mode to show
    'Managed by your state' placeholders instead of the Google Cloud / Backups
    / domain cards (A1), and public_origin to build the callback URLs it tells
    an admin to paste into a vendor console."""
    from app.core.config import get_settings as get_app_settings
    app_settings = get_app_settings()
    return {
        "managed_mode": app_settings.managed_mode,
        "app_version": app_settings.app_version,
        "public_origin": await public_origin(db),
    }


def _field_required(field: Dict[str, Any]) -> bool:
    """Whether a credential field must be present for a provider to count as set up.

    Two conventions exist in the catalogs. The maps catalog carries an explicit
    `required` boolean; the older AI, identity and translation catalogs encode it
    by ending the label with "(optional)". Trust the flag when it is there and
    fall back to the label when it is not, rather than making every catalog
    change shape at once.
    """
    if "required" in field:
        return bool(field["required"])
    return not str(field.get("label", "")).rstrip().endswith("(optional)")


async def providers_for(capability: str) -> List[Dict[str, Any]]:
    """The catalog for one capability, without going through its endpoint.

    The eight catalog endpoints each import their own module and call its
    `catalog_for_api`. That is fine for a request, but the daily connector sweep
    needs the same lists with no request to hang them off, and copying the eight
    imports into a task module would be a second place to update when a ninth
    capability appears.
    """
    if capability in ("email", "sms", "kms", "redaction"):
        from app.services.delivery_providers import catalog_for_api as delivery
        return delivery(capability)
    loaders = {
        "ai": ("app.services.ai.registry", "catalog_for_api"),
        "translation": ("app.services.translation_providers", "catalog_for_api"),
        "identity": ("app.services.identity", "catalog_for_api"),
        "maps": ("app.services.map_provider", "catalog_for_api"),
    }
    entry = loaders.get(capability)
    if not entry:
        return []
    module, name = entry
    return getattr(__import__(module, fromlist=[name]), name)()


async def capability_is_configured(capability: str) -> bool:
    """Whether the provider currently selected for this capability has its
    credentials stored.

    Used to decide what the daily sweep bothers testing. A town that has not set
    up text messages has not made a mistake, and testing it would write a
    failure that shows an amber badge on something deliberately switched off --
    which is the noise that teaches people to ignore badges.
    """
    from app.services.secret_manager import get_secret

    select_key = _PROVIDER_SELECT_KEY.get(capability)
    if not select_key:
        return False
    current = ((await get_secret(select_key)) or "").strip().lower()
    if not current or current in ("none", "off", "disabled"):
        return False
    providers = await providers_for(capability)
    return (await _configured_map(providers)).get(current, False)


async def _configured_map(providers: List[Dict[str, Any]]) -> Dict[str, bool]:
    """{provider id: are all of its required credentials stored}.

    This exists because three of the four capability catalogs were not returning
    it at all. The admin UI reads `configured[current_provider]`, so identity,
    translation and maps cards resolved it to undefined and reported "not
    configured" however well set up they actually were -- a false negative on a
    working connector, which is worse than no badge, because it sends someone off
    to re-paste credentials that were already fine.

    A provider with no required fields counts as configured: there is nothing to
    supply, so there is nothing missing.
    """
    from app.services.secret_manager import get_secret

    out: Dict[str, bool] = {}
    for provider in providers:
        required = [f["key"] for f in provider.get("credential_fields", []) if _field_required(f)]
        present = True
        for key in required:
            try:
                # `.strip()`, so that a value of " " is absent here as well as
                # everywhere else.
                #
                # Two definitions of empty had drifted apart. This one counted
                # any truthy string, and the live test stripped before checking
                # -- so a whitespace credential made a provider "configured"
                # and simultaneously untestable, and the card said "Set up.
                # There is no way to test this one from here" about a service
                # nobody had entered anything for.
                if not (await get_secret(key) or "").strip():
                    present = False
                    break
            except Exception:
                # An unreachable secret store is not the same as an unconfigured
                # provider. Say nothing rather than say something false.
                present = False
                break
        out[provider["provider"]] = present
    return out


@router.get("/client-errors")
async def list_client_errors(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Browser crashes residents and staff have hit.

    The error screen promises a report. Without this the promise resolved to a
    line in a container log, which for a self-hosted town is the same as
    nowhere. Identical crashes are collapsed with a count, so a render loop
    shows as one row seen 400 times rather than burying every other fault.
    """
    from app.services import client_errors

    rows = await client_errors.recent(db, limit=min(max(limit, 1), 200))
    return {
        "errors": [
            {
                "id": r.id,
                "kind": r.kind,
                "message": r.message,
                "stack": r.stack,
                "component_stack": r.component_stack,
                "url": r.url,
                "occurrences": r.occurrences,
                "first_seen_at": r.first_seen_at.isoformat() if r.first_seen_at else None,
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            }
            for r in rows
        ],
    }


@router.get("/connectors/health")
async def connector_health_report(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """What each integration is actually doing, as opposed to whether its
    credentials are stored.

    Deliberately separate from the catalog endpoints. "Configured" is a fact
    about our database and is always answerable; "working" is a fact about
    someone else's service and is sometimes genuinely unknown. Merging them
    into one field would force the unknown case to pick a side, and it always
    picks green.
    """
    from app.services import connector_health as ch

    healths = ch.worst_first(list((await ch.snapshot(db)).values()))
    return {
        "connectors": [
            {
                "connector": h.connector,
                "provider": h.provider,
                "status": h.status,
                "summary": h.summary(),
                "last_success_at": h.last_success_at.isoformat() if h.last_success_at else None,
                "last_error_at": h.last_error_at.isoformat() if h.last_error_at else None,
                "last_error": h.last_error,
                "consecutive_failures": h.consecutive_failures,
                "total_successes": h.total_successes,
                "total_failures": h.total_failures,
                # Surfaced so the card can say alerts are muted and until when.
                # A mute that silenced the email and left no trace on screen
                # would be indistinguishable from the alerting being broken.
                "alerts_muted_until": (
                    h.alert_muted_until.isoformat() if h.alert_muted_until else None
                ),
            }
            for h in healths
        ],
        "needs_attention": [h.connector for h in healths if h.status in (ch.DOWN, ch.FAILING)],
    }


@router.post("/connectors/{connector}/mute")
async def mute_connector_alerts(
    connector: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """"I know about this one." Stops the emails; leaves the badge alone.

    Pass `{"days": 0}` to lift a mute early.

    Nothing here touches how the connector is reported on screen. A dismiss
    that also cleared the red card would turn a known problem into an invisible
    one, which is the exact failure the health system exists to prevent -- so
    the card keeps saying it is broken, and adds that nobody is being emailed
    about it and until when.
    """
    from sqlalchemy import select

    from app.models import ConnectorHealth
    from app.services import connector_alerts as alerts

    row = (await db.execute(
        select(ConnectorHealth).where(ConnectorHealth.connector == connector)
    )).scalar_one_or_none()
    if row is None:
        # Nothing has ever reported health for this name. Creating a row here
        # would let any admin request insert arbitrary connectors into a table
        # the setup page renders.
        raise HTTPException(status_code=404, detail="No health has been recorded for that service yet.")

    raw_days = payload.get("days", alerts.MUTE_FOR.days)
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="days must be a whole number.")
    # Bounded. An unbounded mute is a permanently disabled alarm that nobody
    # remembers turning off, and a negative one is a mute that has already
    # expired dressed up as a mute.
    if not 0 <= days <= 90:
        raise HTTPException(status_code=400, detail="days must be between 0 and 90.")

    now = datetime.now(timezone.utc)
    if days == 0:
        row.alert_muted_until = None
        row.alert_muted_level = None
    else:
        row.alert_muted_until = alerts.mute_until(now, days=days)
        row.alert_muted_level = alerts.alert_level(ch_classify(row, now=now))
    await db.commit()

    # Muting an alarm is exactly the kind of act that wants a name against it
    # six months later, when somebody asks why nobody was told.
    try:
        from app.services.audit_service import AuditService

        await AuditService.log_event(
            db,
            event_type="connector_alerts_muted" if days else "connector_alerts_unmuted",
            username=getattr(admin, "username", None) or str(getattr(admin, "id", "")),
            user_id=getattr(admin, "id", None),
            success=True,
            details={"connector": connector, "days": days},
        )
    except Exception:
        # The mute has already been committed. Losing its audit line is worth
        # noting, not worth failing the request over.
        from app.core.sanitize import sanitize_for_log
        logger.warning("[Health] could not audit the mute of %s", sanitize_for_log(connector))
    return {
        "connector": connector,
        "muted_until": row.alert_muted_until.isoformat() if row.alert_muted_until else None,
        "muted_level": row.alert_muted_level,
    }


def ch_classify(row, *, now=None):
    from app.services.connector_health import classify

    return classify(row, now=now)


@router.get("/identity/catalog")
async def get_identity_catalog(_: User = Depends(get_current_admin)):
    """Identity provider catalog for the admin UI (Auth0 / Entra / Okta / OIDC),
    plus which provider is active."""
    from app.services.identity import catalog_for_api, IDENTITY_PROVIDER_KEY
    from app.services.secret_manager import get_secret
    current = (await get_secret(IDENTITY_PROVIDER_KEY)) or "auth0"
    providers = catalog_for_api()
    return {"current_provider": current.strip().lower(), "default_provider": "auth0",
            "providers": providers, "configured": await _configured_map(providers)}


@router.get("/translation/catalog")
async def get_translation_catalog(_: User = Depends(get_current_admin)):
    """Translation provider catalog (Google / Azure) + current selection."""
    from app.services.translation_providers import catalog_for_api, TRANSLATION_PROVIDER_KEY
    from app.services.secret_manager import get_secret
    current = (await get_secret(TRANSLATION_PROVIDER_KEY)) or "google"
    providers = catalog_for_api()
    return {"current_provider": current.strip().lower(), "default_provider": "google",
            "providers": providers, "configured": await _configured_map(providers)}


@router.get("/maps/catalog")
async def get_maps_catalog(_: User = Depends(get_current_admin)):
    """Map provider catalog. Maps is a capability like AI or translation, so it
    uses the same catalog/save/test endpoints and the same card in the UI --
    a town switches its map the way it switches anything else."""
    from app.services.map_provider import MAP_PROVIDER_KEY, catalog_for_api, normalize_provider
    from app.services.secret_manager import get_secret
    current = normalize_provider(await get_secret(MAP_PROVIDER_KEY))
    providers = catalog_for_api()
    return {"current_provider": current, "default_provider": "google",
            "providers": providers, "configured": await _configured_map(providers)}


@router.get("/ai/catalog")
async def get_ai_catalog(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """AI provider catalog for the admin UI: available boundaries (Vertex /
    Azure Government / Bedrock), their models, and the fields each needs, plus
    which provider is currently selected and which are configured.

    Model lists are served from the live-discovery cache when available (a
    provider's actual current models, refreshed on demand and daily) and fall
    back to the curated catalog. No live network call happens here — the load
    stays fast; refreshing is explicit (POST /ai/models/refresh) or scheduled."""
    from app.services.ai.registry import AI_CATALOG, catalog_for_api, AI_PROVIDER_KEY, AI_MODEL_KEY
    from app.services.ai import model_discovery as md
    from app.services.secret_manager import get_secret

    current_provider = (await get_secret(AI_PROVIDER_KEY)) or "vertex"
    current_model = await get_secret(AI_MODEL_KEY)

    # Overlay the discovered model lists (per-provider) onto the curated catalog.
    cache = await md.load_db_cache(db)
    providers = catalog_for_api()

    # Shared with the other three capabilities rather than a second copy of the
    # same rule. The AI-only version this replaces inferred "required" purely
    # from the label ending in "(optional)", which silently mis-reads any
    # catalog that states it as a flag.
    configured = await _configured_map(providers)
    for p in providers:
        entry = cache.get(p["provider"])
        if entry and entry.get("models"):
            p["models"] = entry["models"]
            p["models_source"] = entry.get("source", "live")
            p["models_fetched_at"] = entry.get("fetched_at")
        else:
            p["models_source"] = "curated"
            p["models_fetched_at"] = None

    resolved_model = current_model or AI_CATALOG.get(current_provider, {}).get("default_model")
    current_models = next((p["models"] for p in providers if p["provider"] == current_provider), [])
    return {
        "current_provider": current_provider,
        "default_provider": "vertex",
        "current_model": resolved_model,
        "current_model_available": md.model_is_available(current_models, current_model),
        "configured": configured,
        "providers": providers,
    }


class AIModelRefreshRequest(BaseModel):
    provider: str


@router.post("/ai/models/refresh")
@_cost_limiter.limit("6/minute")  # live provider API call
async def refresh_ai_models(
    request: Request,
    body: AIModelRefreshRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Live-discover a provider's current models and update the shared cache.
    Returns the merged list plus whether the configured model is still offered."""
    from app.services.ai.registry import AI_CATALOG
    provider = (body.provider or "").strip().lower()
    if provider not in AI_CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown AI provider: {provider}")
    from app.services.ai import model_discovery as md
    result = await md.refresh_provider(db, provider)
    return {"provider": provider, **result}


@router.get("/{capability}/catalog", include_in_schema=False)
async def get_capability_catalog(capability: str, _: User = Depends(get_current_admin)):
    """Catalog for the capabilities added after the first four, which each had
    their own near-identical route. Declared before /ai/catalog would shadow it
    Registered after every hand-written catalog route, because FastAPI takes the
    first match: declared earlier, this would shadow /ai/catalog and 404 it."""
    from app.services.delivery_providers import _CATALOGS, catalog_for_api, normalize_provider
    if capability not in _CATALOGS:
        raise HTTPException(status_code=404, detail="Unknown capability")
    from app.services.secret_manager import get_secret
    from app.services.delivery_providers import _DEFAULTS
    current = normalize_provider(capability, await get_secret(_PROVIDER_SELECT_KEY[capability]))
    providers = catalog_for_api(capability)
    return {"current_provider": current, "default_provider": _DEFAULTS[capability],
            "providers": providers, "configured": await _configured_map(providers)}


# ---- Unified provider save + test (AI / translation / identity) ----

_PROVIDER_SELECT_KEY = {
    "ai": "AI_PROVIDER",
    "translation": "TRANSLATION_PROVIDER",
    "identity": "IDENTITY_PROVIDER",
    "maps": "MAP_PROVIDER",
    # Four capabilities whose provider switch already existed in the dispatch
    # code and had no catalog, so nothing surfaced them: notifications went out
    # through a hand-written SMTP/Twilio card, and KMS and photo redaction could
    # only be changed by setting a secret by hand.
    "email": "EMAIL_PROVIDER",
    "sms": "SMS_PROVIDER",
    "kms": "KMS_PROVIDER",
    "redaction": "REDACTION_PROVIDER",
}


async def _persist_secret(db: AsyncSession, key_name: str, value: str) -> bool:
    """Write a secret to the configured store and keep an encrypted DB copy.

    Returns whether the external store took it. That return value matters: when
    the store is not reachable yet, set_secret returns False and logs at DEBUG,
    which nothing raises the level for -- so the secret quietly lived only in
    the database and the town had no way to know. It is a real ordering trap,
    because the credentials that make Secret Manager reachable are themselves
    entered on this page: anything saved before them lands in the database and
    stays there until somebody happens to run the migration.

    The caller surfaces this rather than swallowing it.
    """
    from app.core.encryption import encrypt
    from app.core.managed import reject_platform_key_writes
    from app.services.secret_manager import set_secret, clear_cache
    reject_platform_key_writes(key_name)
    # These two are deliberately database-only: they are what makes the secret
    # store reachable in the first place, so storing them in it is circular.
    bootstrap_keys = {"GCP_SERVICE_ACCOUNT_JSON", "GOOGLE_CLOUD_PROJECT"}
    stored_externally = key_name in bootstrap_keys
    if value and key_name not in bootstrap_keys:
        try:
            if await set_secret(key_name, value):
                stored_externally = True
                clear_cache()
        except Exception as e:
            from app.core.sanitize import sanitize_for_log
            logger.warning(f"Provider secret store write failed for {sanitize_for_log(key_name)}: {sanitize_for_log(str(e))}")
    result = await db.execute(select(SystemSecret).where(SystemSecret.key_name == key_name))
    secret = result.scalar_one_or_none()
    enc = encrypt(value) if value else None
    if secret:
        secret.key_value = enc
        secret.is_configured = bool(value)
    else:
        db.add(SystemSecret(key_name=key_name, key_value=enc, is_configured=bool(value)))
    await db.commit()
    return stored_externally


class ProviderSaveRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    settings: Dict[str, str] = {}


def _capability_catalog(capability: str) -> Dict:
    if capability == "ai":
        from app.services.ai.registry import AI_CATALOG
        return AI_CATALOG
    if capability == "translation":
        from app.services.translation_providers import TRANSLATION_CATALOG
        return TRANSLATION_CATALOG
    if capability == "identity":
        from app.services.identity import IDENTITY_CATALOG
        return IDENTITY_CATALOG
    if capability == "maps":
        from app.services.map_provider import MAP_CATALOG
        return MAP_CATALOG
    if capability in ("email", "sms", "kms", "redaction"):
        from app.services.delivery_providers import _CATALOGS
        return _CATALOGS[capability]
    return {}


@router.post("/providers/{capability}/save")
async def save_provider(
    capability: str,
    body: ProviderSaveRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Select a provider for a capability and save its settings/secrets.
    Blank values are ignored (existing secret kept)."""
    if capability not in _PROVIDER_SELECT_KEY:
        raise HTTPException(status_code=400, detail=f"Unknown capability: {capability}")
    catalog = _capability_catalog(capability)
    provider_id = (body.provider or "").strip().lower()
    if provider_id not in catalog:
        raise HTTPException(status_code=400, detail=f"Unknown {capability} provider: {body.provider}")
    # Only the credential keys this provider's catalog declares may be written
    # through this endpoint — it must not become an arbitrary secret writer.
    allowed_keys = {f["key"] for f in catalog[provider_id].get("credential_fields", [])}
    unknown = [k for k in (body.settings or {}) if k not in allowed_keys]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unexpected settings for {provider_id}: {', '.join(sorted(unknown))}")
    if capability == "ai" and body.model:
        # Validate against curated ∪ live-discovered models. A model the provider
        # actually offers (from the discovery cache) is accepted even if it isn't
        # in the curated list — that's the whole point of live discovery. Only
        # reject when we can positively prove the id is offered nowhere.
        allowed_models = {m["id"] for m in catalog[provider_id].get("models", [])}
        try:
            from app.services.ai import model_discovery as md
            cache = await md.load_db_cache(db)
            entry = cache.get(provider_id) or {}
            allowed_models |= {m["id"] for m in entry.get("models", []) if m.get("id")}
        except Exception:
            # Discovery is an *additional* source of valid model ids. If the
            # cache can't be read, fall back to validating against the curated
            # list alone rather than rejecting the save.
            pass
        if allowed_models and body.model not in allowed_models:
            raise HTTPException(status_code=400, detail=f"Unknown model for {provider_id}: {body.model}")
    await _persist_secret(db, _PROVIDER_SELECT_KEY[capability], provider_id)
    if capability == "ai" and body.model:
        await _persist_secret(db, "AI_MODEL", body.model)
    # Track where each credential actually landed. A False here is not an
    # error -- the encrypted database is a supported store -- but it is
    # something the town has to be told, because the usual cause is saving
    # this card before the credentials that make the secret store reachable,
    # and the fix (enter those, then re-save) is only obvious if you know.
    db_only: List[str] = []
    for key, value in (body.settings or {}).items():
        if value:  # blank = keep existing
            if not await _persist_secret(db, key, value):
                db_only.append(key)
    from app.services.secret_manager import clear_cache
    clear_cache()
    # Shape findings are advisory and never block: a rule is a heuristic about
    # someone else's format, and refusing a credential that would have worked is
    # a worse failure than accepting one that will not -- the second is
    # discoverable, the first is a dead end.
    from app.services.credential_checks import inspect_settings
    findings = inspect_settings(body.settings)
    warnings = [{"key": f.key, "severity": f.severity, "message": f.message} for f in findings]
    if db_only:
        from app.services.secret_manager import _secrets_provider
        warnings.append({
            "key": db_only[0],
            "severity": "info",
            "message": (
                f"Saved and encrypted in the database. "
                f"{ {'azure': 'Azure Key Vault', 'aws': 'AWS Secrets Manager'}.get(_secrets_provider(), 'Google Secret Manager') }"
                " is not reachable yet — once you finish the cloud credentials above,"
                " this moves across on its own. Nothing further to do here."
            ),
        })
    else:
        # The store took everything, which means it is reachable -- and this may
        # be the moment it became reachable, if what was just saved were the
        # cloud credentials themselves. Sweep anything entered earlier across
        # now rather than leaving it for the hourly pass. Scheduled after the
        # response so a slow store cannot make Save feel broken.
        from app.services.storage_maintenance import vault_secrets as _vault
        background.add_task(_vault)
    return {
        "ok": True,
        "provider": provider_id,
        "warnings": warnings,
    }


# ---- live tests for the capabilities that had none ---------------------------
#
# `test_provider` validated eight capabilities and could test three. Pressing
# Save & Test on maps, email, text messages, encryption or photo redaction
# returned "A live test is not available for this capability" -- a button whose
# whole job is to tell you whether something works, telling five of eight cards
# that it cannot.
#
# Two of the five turned out to be the most valuable tests on the page, because
# they check the two things that fail without saying so: which key is actually
# encrypting resident data, and whether the photo detector can answer at all.
#
# The rest need a real network call. Where one exists that does not send
# anything to a resident, it is made. Where it does not -- a generic HTTP SMS
# gateway cannot be exercised without sending a text -- the response says so and
# is deliberately NOT recorded as a connector failure, because "we cannot check
# this from here" is not the same as "this is broken", and a red badge that
# never goes green teaches people to ignore badges.


async def _test_ai(db) -> dict:
    from app.services.ai import get_ai_provider
    provider = await get_ai_provider(db)
    if not provider:
        return {"ok": False, "detail": "No AI provider is configured. Enter the required fields and save first."}
    result = await provider.complete_json('Reply with {"priority_score": 5}. This is a connection test.')
    # Reachability and auth, not whether a trivial prompt produced parseable
    # JSON. Providers set `_reachable` when the API answered at all.
    reachable = isinstance(result, dict) and ("_error" not in result or bool(result.get("_reachable")))
    if reachable:
        return {"ok": True, "detail": f"{provider.provider}/{provider.model} reachable and authenticated"}
    return {"ok": False, "detail": f"Call failed: {result.get('_error', 'unknown')[:200]}"}


async def _test_translation(db) -> dict:
    from app.services.translation_providers import get_translation_provider
    provider = await get_translation_provider()
    if not provider:
        return {"ok": False, "detail": "No translation provider is configured."}
    out = await provider.translate(["hello"], "en", "es")
    return {"ok": bool(out), "detail": f"Translated sample → {out[0]}" if out else "No translation returned"}


async def _test_identity(db) -> dict:
    from app.services.identity import resolve_identity_config, get_oidc_metadata
    cfg = await resolve_identity_config(db)
    if not cfg:
        return {"ok": False, "detail": "No identity provider is configured."}
    meta = await get_oidc_metadata(cfg)
    return {"ok": bool(meta.get("authorization_endpoint")),
            "detail": f"Discovered {cfg['provider']} endpoints at {cfg['issuer_base']}"}


async def _test_kms(db=None) -> dict:
    """Wrap a throwaway key and see which service actually did it.

    The most valuable check on the page. A KMS that stops answering does not
    raise -- pii_crypto falls back to the application key and carries on -- so
    "is the key I selected the one encrypting resident data" is a question
    nothing else asks out loud. `probe_backend` rather than `active_backend`,
    because the latter reads the data key this process cached at startup and
    would answer for the world as it was then.
    """
    from app.core import pii_crypto
    from app.core.encryption import _kms_provider

    selected = _kms_provider()
    actual = pii_crypto.probe_backend()
    if actual == selected:
        label = {"google": "Google Cloud KMS", "azure": "Azure Key Vault",
                 "aws": "AWS KMS", "local": "the application key"}.get(actual, actual)
        return {"ok": True, "detail": f"Wrapped a test key with {label}."}
    return {"ok": False, "detail": (
        f"Selected {selected}, but a test key was wrapped with {actual}. Resident "
        f"data is not being encrypted with the key you chose — check the "
        f"credentials and that the key still exists.")}


async def _test_redaction(db=None) -> dict:
    """Can the chosen detector answer, and is it the chosen one?

    A detector with no credentials returns the same empty result as a photo
    with nobody in it, so this is the only place the difference is visible.
    """
    from app.services.image_redaction import effective_provider, resolve_provider

    selected = await resolve_provider()
    if not selected:
        return {"ok": True, "detail": "Photo redaction is switched off, as configured."}
    actual, degraded_from = await effective_provider(selected)
    if degraded_from == actual:
        return {"ok": False, "detail": (
            "No detector is available, so photos would be stored without blurring. "
            "On-server detection needs no account — this usually means OpenCV is missing.")}
    if degraded_from:
        return {"ok": False, "detail": (
            f"{degraded_from} has no usable credentials, so blurring is falling back to "
            f"on-server detection. Photos are still redacted, less accurately.")}
    return {"ok": True, "detail": f"{actual} is available and will blur faces and plates."}


async def _test_email(db=None) -> dict:
    return await _test_delivery("email")


async def _test_sms(db=None) -> dict:
    return await _test_delivery("sms")


def _unverifiable(detail: str) -> dict:
    """A result that is shown but not written to connector health."""
    return {"ok": False, "detail": detail, "recorded": False}


async def _test_maps() -> dict:
    """Geocode a known address. Reads only, costs a fraction of a cent."""
    import httpx

    from app.services.secret_manager import get_secret

    provider = (await get_secret("MAPS_PROVIDER")) or "google"
    sample = "1600 Pennsylvania Ave NW, Washington DC"

    async with httpx.AsyncClient(timeout=12.0) as client:
        if provider == "google":
            key = await get_secret("GOOGLE_MAPS_API_KEY")
            if not key:
                return {"ok": False, "detail": "No Google Maps API key is saved."}
            r = await client.get("https://maps.googleapis.com/maps/api/geocode/json",
                                 params={"address": sample, "key": key})
            body = r.json()
            status = body.get("status")
            if status == "OK":
                return {"ok": True, "detail": "Key accepted; a test address geocoded successfully."}
            # Google's own words matter here: REQUEST_DENIED with "billing" is
            # the single most common failure on this page and its remedy is
            # nothing to do with the key.
            return {"ok": False, "detail": f"Google returned {status}. {body.get('error_message', '')}".strip()}

        if provider == "azure":
            key = await get_secret("AZURE_MAPS_KEY")
            if not key:
                return {"ok": False, "detail": "No Azure Maps key is saved."}
            r = await client.get("https://atlas.microsoft.com/search/address/json",
                                 params={"api-version": "1.0", "subscription-key": key, "query": sample})
            if r.status_code == 200:
                return {"ok": True, "detail": "Key accepted; a test address geocoded successfully."}
            return {"ok": False, "detail": f"Azure Maps returned HTTP {r.status_code}."}

        if provider == "esri":
            key = await get_secret("ARCGIS_API_KEY")
            if not key:
                return {"ok": False, "detail": "No ArcGIS API key is saved."}
            locator = (await get_secret("ARCGIS_LOCATOR_URL")) or (
                "https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer")
            r = await client.get(f"{locator.rstrip('/')}/findAddressCandidates",
                                 params={"SingleLine": sample, "f": "json", "token": key})
            body = r.json() if r.status_code == 200 else {}
            if "error" in body:
                return {"ok": False, "detail": f"ArcGIS: {body['error'].get('message', 'rejected the key')}"}
            if r.status_code == 200:
                return {"ok": True, "detail": "Key accepted; the locator answered."}
            return {"ok": False, "detail": f"ArcGIS returned HTTP {r.status_code}."}

        if provider == "apple":
            return _unverifiable(
                "Apple Maps credentials can only be checked by signing a token in the "
                "browser, so there is nothing to test from here. Open the resident "
                "portal and confirm the map draws.")

    return _unverifiable(f"No live test is available for {provider}.")


async def _test_delivery(capability: str) -> dict:
    """Email and text messages, without sending anything to a resident."""
    import httpx

    from app.services.delivery_providers import (
        EMAIL_CATALOG, SMS_CATALOG, describe_missing, required_keys,
    )
    from app.services.secret_manager import get_secret

    async def _nothing_saved(catalog: dict, provider: str) -> Optional[dict]:
        """"You have not filled this in" beats any statement about the vendor.

        The fallthroughs at the ends of both halves of this function reported on
        the *provider* -- "there is no way to check http without sending a real
        text message", "ACS has no check that avoids sending a real message" --
        without first asking whether the town had entered anything. A clerk who
        had never touched text messages was told their gateway was untestable,
        which is true of the gateway and irrelevant to them: what they needed to
        know is that the boxes are empty.
        """
        entry = catalog.get(provider)
        missing = [k for k in required_keys(entry) if not (await get_secret(k) or "").strip()]
        if not missing:
            return None
        # `configured: False` rather than only `recorded: False`.
        #
        # These are different facts and the frontend was collapsing them: it
        # read "not recorded" as "this provider cannot be tested", which is
        # true of an HTTP gateway in general and wrong about a town that has
        # entered nothing. Saying which it is lets the card correct itself even
        # when the catalog disagrees.
        return {
            "ok": False,
            "detail": describe_missing(entry, missing),
            "recorded": False,
            "configured": False,
        }

    if capability == "email":
        provider = (await get_secret("EMAIL_PROVIDER")) or "smtp"
        blank = await _nothing_saved(EMAIL_CATALOG, provider)
        if blank:
            return blank
        if provider == "smtp":
            import asyncio
            import smtplib
            host = await get_secret("SMTP_HOST")
            user = await get_secret("SMTP_USER")
            password = await get_secret("SMTP_PASSWORD")
            if not host:
                return {"ok": False, "detail": "No SMTP host is saved."}
            port = int((await get_secret("SMTP_PORT")) or 587)

            def _connect():
                # Connect and authenticate only. Nothing is sent, so this is
                # safe to press repeatedly.
                if port == 465:
                    server = smtplib.SMTP_SSL(host, port, timeout=12)
                else:
                    server = smtplib.SMTP(host, port, timeout=12)
                    server.starttls()
                with server:
                    if user and password:
                        server.login(user, password)
                return True

            await asyncio.get_event_loop().run_in_executor(None, _connect)
            return {"ok": True, "detail": f"Connected to {host}:{port} and signed in. Nothing was sent."}

        if provider == "ses":
            import asyncio
            from app.services.cloud_moderation import _aws_kwargs
            kwargs = await _aws_kwargs()
            if not kwargs:
                return {"ok": False, "detail": "No AWS region or credentials are saved."}

            def _quota():
                import boto3
                return boto3.client("ses", **kwargs).get_send_quota()

            quota = await asyncio.get_event_loop().run_in_executor(None, _quota)
            sent, cap = quota.get("SentLast24Hours", 0), quota.get("Max24HourSend", 0)
            if cap and cap <= 200:
                # The sandbox cap. Everything looks fine and residents receive
                # nothing, so it is worth saying rather than passing green.
                return {"ok": False, "detail": (
                    f"Credentials work, but the 24-hour cap is {int(cap)} — this account is still "
                    f"in the SES sandbox and will not deliver to unverified addresses. "
                    f"Request production access.")}
            return {"ok": True, "detail": f"SES reachable. {int(sent)} of {int(cap)} sent in the last 24 hours."}

        return _unverifiable(
            "Azure Communication Services has no check that avoids sending a real "
            "message. Save, then send yourself a test from a request.")

    provider = (await get_secret("SMS_PROVIDER")) or "none"
    if provider == "none":
        return {"ok": True, "detail": "Text messages are switched off, as configured."}

    blank = await _nothing_saved(SMS_CATALOG, provider)
    if blank:
        return blank

    if provider == "twilio":
        sid = await get_secret("TWILIO_ACCOUNT_SID")
        token = await get_secret("TWILIO_AUTH_TOKEN")
        if not (sid and token):
            return {"ok": False, "detail": "Account SID or auth token is missing."}
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
                                 auth=(sid, token))
        if r.status_code == 200:
            status = r.json().get("status", "active")
            if status != "active":
                return {"ok": False, "detail": f"Credentials work, but the Twilio account is {status}."}
            return {"ok": True, "detail": "Twilio credentials accepted. Nothing was sent."}
        if r.status_code == 401:
            return {"ok": False, "detail": "Twilio rejected the Account SID or auth token."}
        return {"ok": False, "detail": f"Twilio returned HTTP {r.status_code}."}

    if provider == "sns":
        import asyncio
        from app.services.cloud_moderation import _aws_kwargs
        kwargs = await _aws_kwargs()
        if not kwargs:
            return {"ok": False, "detail": "No AWS region or credentials are saved."}

        def _attrs():
            import boto3
            return boto3.client("sns", **kwargs).get_sms_attributes()

        await asyncio.get_event_loop().run_in_executor(None, _attrs)
        return {"ok": True, "detail": "SNS reachable and authenticated. Nothing was sent."}

    return _unverifiable(
        f"There is no way to check {provider} without sending a real text message. "
        f"Save, then send yourself one from a request to confirm delivery.")


# One table, so the set of capabilities the endpoint accepts and the set it can
# actually test cannot drift apart. They did: the accept-list was widened when
# maps, email, SMS, encryption and redaction got catalogs, and five of eight
# cards then answered "a live test is not available for this capability" -- a
# button whose whole job is to say whether something works, saying it could not.
_CAPABILITY_TESTS = {
    "ai": _test_ai,
    "translation": _test_translation,
    "identity": _test_identity,
    "maps": lambda db=None: _test_maps(),
    "email": _test_email,
    "sms": _test_sms,
    "kms": _test_kms,
    "redaction": _test_redaction,
}


@router.post("/providers/{capability}/test")
@_cost_limiter.limit("10/minute")  # live paid-API call — bound the cost
async def test_provider(
    request: Request,
    capability: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Live connectivity check for the currently-configured provider of a
    capability. Returns {ok, detail}.

    The outcome is recorded, so a test is not just a moment on screen. That
    matters in the failing direction especially: an admin who tests, sees red
    and walks away leaves a record the setup page can keep showing, instead of
    a green badge that only means credentials exist.
    """
    from app.services import connector_health

    # Validate before anything else, the way save_provider does. Without this,
    # `capability` is an unvalidated path segment that reaches
    # connector_health._row(), which creates a row for whatever name it is
    # given -- so any admin request could insert arbitrary junk rows into a
    # table the setup page renders. It also kept the raw segment out of the
    # 400 body below.
    if capability not in _PROVIDER_SELECT_KEY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown capability. Expected one of: {', '.join(sorted(_PROVIDER_SELECT_KEY))}.",
        )

    async def _remember(outcome: dict) -> dict:
        try:
            if outcome.get("ok"):
                await connector_health.record_success(db, capability)
            else:
                await connector_health.record_failure(db, capability, outcome.get("detail", ""))
        except Exception:
            # Bookkeeping must never turn a passing test into a failing one.
            pass
        return outcome

    check = _CAPABILITY_TESTS.get(capability)
    if check is None:
        # Cannot happen while the accept-list is derived from this table, and
        # a test asserts that it is. Kept as a real branch rather than an
        # assertion because a 400 is a better failure than a 500.
        raise HTTPException(status_code=400, detail="A live test is not available for this capability.")

    try:
        outcome = await check(db)
        # An outcome we could not verify is shown but not written to connector
        # health: "we cannot check this from here" is not "this is broken", and
        # a red badge that can never go green teaches people to ignore badges.
        return outcome if outcome.get("recorded") is False else await _remember(outcome)
    except HTTPException:
        raise
    except Exception as e:
        # The provider's own words, plus a next step when we recognise the
        # shape of the complaint. Never a replacement -- a clerk searching the
        # web for their error needs the actual string.
        from app.services.credential_checks import describe_failure
        return await _remember({"ok": False, "detail": describe_failure(str(e)[:300])})


# ---- Cloud environment profile (hybrid one-choice front door) ----
#
# The real decision a jurisdiction makes is its compliance boundary — it is
# authorized under ONE cloud (Google, or Azure Government / GCC High), so a
# single choice should set AI + translation + secret-store together. Identity is
# deliberately NOT bundled: an Azure-cloud town may still use Auth0/Okta for SSO,
# so we only *recommend* the matching IdP and switch it on explicit opt-in.
# Google Maps is fixed regardless of profile.
CLOUD_PROFILES: Dict[str, Dict[str, str]] = {
    "google": {
        "label": "Google Cloud",
        "boundary": "Google Cloud — FedRAMP High / StateRAMP",
        "ai": "vertex",
        "translation": "google",
        "secrets": "google",
        "kms": "google",
        # Google has no first-party SMS; email works via SMTP (Workspace/relay).
        "email": "smtp",
        "sms": "",
        "identity_recommended": "auth0",
    },
    "azure": {
        "label": "Microsoft Azure (Government)",
        "boundary": "Azure Government / GCC High — FedRAMP High, DoD IL4/5",
        "ai": "azure",
        "translation": "azure",
        "secrets": "azure",
        "kms": "azure",
        "email": "acs",
        "sms": "acs",
        "identity_recommended": "entra",
    },
    "aws": {
        "label": "Amazon Web Services (GovCloud)",
        "boundary": "AWS GovCloud — FedRAMP High, DoD IL4/5",
        "ai": "bedrock",
        "translation": "aws",
        "secrets": "aws",
        "kms": "aws",
        "email": "ses",
        "sms": "sns",
        "identity_recommended": "oidc",
    },
}


def _derive_cloud_profile(ai: str, translation: str, secrets: str, kms: str = None) -> str:
    """Report which named profile the current core selections match, or 'mixed'.
    Matches on the boundary-defining set (AI, translation, secret store, and KMS
    when provided); email/SMS can legitimately differ and aren't part of the match."""
    for pid, p in CLOUD_PROFILES.items():
        if ai == p["ai"] and translation == p["translation"] and secrets == p["secrets"]:
            if kms is not None and kms != p["kms"]:
                continue
            return pid
    return "mixed"


class CloudProfileRequest(BaseModel):
    profile: str
    # Opt-in: also switch the staff sign-in provider to the profile's
    # recommended IdP. Off by default because identity is a separate contract.
    apply_identity: bool = False


@router.get("/providers/status")
async def get_provider_status(_: User = Depends(get_current_admin)):
    """Which provider each capability is on, and which providers are set up.

    One request instead of eight. The setup guide's task list needs to know
    whether each item is finished before anything is opened, and the only
    honest answer is per *provider* rather than per capability.

    That distinction is the bug this exists to fix. The page was deciding from
    the stored secrets, where "maps is configured" meant any map provider's key
    was present -- so a town that had set up Google Maps and then switched to
    Esri saw a green tick against a provider with no credentials at all, and the
    guide skipped straight past the thing it most needed to ask for.
    """
    from app.core.sanitize import sanitize_for_log
    from app.services.secret_manager import get_secret

    out: Dict[str, Any] = {}
    for capability, select_key in _PROVIDER_SELECT_KEY.items():
        try:

            providers = await providers_for(capability)
            current = ((await get_secret(select_key)) or "").strip().lower()
            out[capability] = {
                "current_provider": current or None,
                "configured": await _configured_map(providers),
            }
        except Exception as exc:
            # One capability failing to report must not blank the other seven.
            # An absent entry reads as "unknown", which the page shows as
            # unfinished -- the safe direction, since the cost is asking about
            # something already done rather than skipping something that isn't.
            logger.warning("provider status failed for %s: %s",
                           sanitize_for_log(capability), sanitize_for_log(str(exc)))
    return out


@router.get("/providers/cloud-identity")
async def cloud_identity(_: User = Depends(get_current_admin)):
    """Whether this server already has an identity on its cloud.

    When it does, the credential boxes for that cloud are not merely optional --
    leaving them empty is the better answer. The token is issued minutes at a
    time and rotated by the platform, so there is no long-lived secret to leak,
    to vault, or to expire on a date nobody recorded.

    Two of the three already behaved this way by accident: boto3 falls through
    to the instance role and google-auth to Application Default Credentials when
    nothing is configured. Nothing said so, so every town pasted a key anyway.
    """
    from app.services.cloud_identity import summary
    return summary()


@router.get("/providers/cloud-profile")
async def get_cloud_profile(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Report the current cloud environment: the matched profile (or 'mixed'),
    the per-capability selections behind it, and the fixed Maps provider."""
    from app.services.secret_manager import get_secret, _secrets_provider
    from app.core.config import get_settings as _app_settings
    from app.core.encryption import _kms_provider
    from app.services.map_provider import MAP_CATALOG, MAP_PROVIDER_KEY, normalize_provider
    maps_provider = normalize_provider(await get_secret(MAP_PROVIDER_KEY))
    ai = (await get_secret("AI_PROVIDER")) or "vertex"
    translation = (await get_secret("TRANSLATION_PROVIDER")) or "google"
    identity = (await get_secret("IDENTITY_PROVIDER")) or "auth0"
    email = (await get_secret("EMAIL_PROVIDER")) or "smtp"
    sms = (await get_secret("SMS_PROVIDER")) or ""
    secrets = _secrets_provider()
    kms = _kms_provider()
    return {
        "profile": _derive_cloud_profile(ai, translation, secrets, kms),
        "managed": _app_settings().managed_mode,
        "components": {
            "ai": ai, "translation": translation, "secrets": secrets, "kms": kms,
            "identity": identity, "email": email, "sms": sms,
        },
        # Maps was pinned to Google when this endpoint was written. It has since
        # become a switchable capability like the others -- /maps/catalog offers
        # Google, Esri, Azure and Apple, and _PROVIDER_SELECT_KEY routes saves to
        # MAP_PROVIDER -- so reporting it as locked contradicted the card sitting
        # directly beneath the banner that showed it.
        "maps": {
            "provider": maps_provider,
            "locked": False,
            "label": MAP_CATALOG.get(maps_provider, {}).get("name")
                     or maps_provider.replace("_", " ").title(),
        },
        "profiles": [{"id": k, **v} for k, v in CLOUD_PROFILES.items()],
    }


@router.post("/providers/cloud-profile")
async def set_cloud_profile(
    body: CloudProfileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Apply a whole cloud environment in one choice: sets the AI, translation and
    secret-store providers to the profile's defaults. In managed (state-hosted)
    mode this is locked — the compliance boundary is set by the hosting platform.
    """
    # The compliance boundary is a state-level decision when hosted centrally.
    from app.core.config import get_settings as _app_settings
    if _app_settings().managed_mode:
        raise HTTPException(
            status_code=403,
            detail="The cloud environment is set by your state's hosting platform and can't be changed here.",
        )
    pid = (body.profile or "").strip().lower()
    if pid not in CLOUD_PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown cloud profile: {body.profile}")
    p = CLOUD_PROFILES[pid]

    await _persist_secret(db, _PROVIDER_SELECT_KEY["ai"], p["ai"])
    await _persist_secret(db, _PROVIDER_SELECT_KEY["translation"], p["translation"])
    await _persist_secret(db, "SECRETS_PROVIDER", p["secrets"])
    await _persist_secret(db, "KMS_PROVIDER", p["kms"])
    # Email/SMS only when the cloud has a native option — Google has no first-party
    # SMS, so leave the existing SMS provider (e.g. Twilio) untouched there.
    if p.get("email"):
        await _persist_secret(db, "EMAIL_PROVIDER", p["email"])
    if p.get("sms"):
        await _persist_secret(db, "SMS_PROVIDER", p["sms"])

    warnings: List[str] = []
    # Gov-readiness: flipping the secret store to a vault that isn't wired up yet
    # is allowed (writes fall back to the encrypted DB), but say so plainly.
    if p["secrets"] == "azure":
        try:
            from app.core import azure_keyvault
            if not azure_keyvault.is_configured():
                warnings.append(
                    "Azure Key Vault isn't configured yet — secrets stay in the encrypted "
                    "database until Key Vault credentials are added."
                )
        except Exception:
            warnings.append("Could not verify Azure Key Vault configuration.")
    elif p["secrets"] == "google":
        try:
            from app.services.secret_manager import _is_gcp_available
            if not _is_gcp_available():
                warnings.append(
                    "Google Secret Manager isn't reachable yet — secrets stay in the "
                    "encrypted database until GOOGLE_CLOUD_PROJECT and credentials are set."
                )
        except Exception:
            # This block only decides whether to add an advisory warning. Failing
            # to determine reachability is not a reason to fail the profile switch.
            pass
    elif p["secrets"] == "aws":
        try:
            from app.core import aws_secretsmanager
            if not aws_secretsmanager.is_configured():
                warnings.append(
                    "AWS Secrets Manager isn't configured yet (set AWS_REGION + credentials) — "
                    "secrets stay in the encrypted database until then."
                )
        except Exception:
            # As above: advisory only, so an unavailable check stays silent
            # rather than blocking the switch.
            pass

    # KMS migration safety: existing PII is unwrapped by the KMS tag stored in
    # each value, so it stays readable ONLY while the previous KMS credentials
    # remain in place. New PII uses the new KMS immediately.
    warnings.append(
        f"PII encryption now uses {p['kms'].upper()} KMS for new data. Existing encrypted "
        "records still need the previous KMS's credentials to decrypt — keep them in place, "
        "or run “Re-encrypt All PII” to migrate everything to the new key."
    )

    identity_applied = False
    if body.apply_identity:
        await _persist_secret(db, _PROVIDER_SELECT_KEY["identity"], p["identity_recommended"])
        identity_applied = True

    from app.services.secret_manager import clear_cache
    clear_cache()
    # Drop the cached wrapped-DEK so the next PII write re-wraps under the new KMS.
    try:
        from app.core import pii_crypto
        pii_crypto.clear_caches()
    except Exception:
        # Best-effort. A stale cached DEK means the next PII write re-wraps
        # under the old KMS, which the migration warning above already covers;
        # it is not worth failing an otherwise-applied profile over.
        pass

    from app.core.sanitize import sanitize_for_log
    logger.info(
        f"[Providers] {sanitize_for_log(current_user.username)} set cloud profile → "
        f"{sanitize_for_log(pid)} (identity_applied={identity_applied})"
    )
    return {
        "ok": True,
        "profile": pid,
        "components": {
            "ai": p["ai"], "translation": p["translation"], "secrets": p["secrets"],
            "kms": p["kms"], "email": p.get("email", ""), "sms": p.get("sms", ""),
        },
        "identity_recommended": p["identity_recommended"],
        "identity_applied": identity_applied,
        "warnings": warnings,
    }


@router.post("/settings", response_model=SystemSettingsResponse)
async def update_settings(
    settings_data: SystemSettingsBase,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Update system settings (admin only)"""
    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = SystemSettings(**settings_data.model_dump())
        db.add(settings)
    else:
        # IMPORTANT: Only update fields that were explicitly provided in the request
        # Using exclude_unset=True prevents default values in the schema from 
        # overwriting saved values when the frontend doesn't send all fields
        for key, value in settings_data.model_dump(exclude_unset=True).items():
            setattr(settings, key, value)
    
    await db.commit()
    await db.refresh(settings)
    return settings


# ============ Disclaimer Acknowledgment ============

@router.post("/disclaimer/acknowledge")
async def log_disclaimer_acknowledgment(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Log that a user has acknowledged the non-emergency disclaimer.
    This is stored for legal protection and audit purposes.
    Public endpoint - no authentication required."""
    
    # Get client info for logging
    body = await request.json()
    session_id = body.get("session_id", "unknown")
    
    # Get real IP (handle proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else "unknown"
    
    user_agent = request.headers.get("User-Agent", "unknown")[:500]
    
    # Create log entry
    acknowledgment = DisclaimerAcknowledgment(
        session_id=session_id,
        ip_address=ip_address,
        user_agent=user_agent,
        disclaimer_version="1.0"
    )
    db.add(acknowledgment)
    await db.commit()
    
    from app.core.sanitize import sanitize_for_log
    logger.info(f"Disclaimer acknowledged: session={sanitize_for_log(session_id)}, ip={sanitize_for_log(ip_address)}")
    
    return {"status": "acknowledged", "session_id": session_id}


# ============ Secrets ============

@router.get("/secrets", response_model=List[SecretResponse])
async def list_secrets(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """List all secrets (admin only). Non-sensitive config values are returned."""
    # These keys can have their values exposed (they're config choices, not secrets)
    SAFE_TO_RETURN = {'SMS_PROVIDER', 'EMAIL_ENABLED', 'SMTP_USE_TLS', 'SMTP_PORT'}
    
    result = await db.execute(select(SystemSecret))
    secrets = result.scalars().all()
    
    response = []
    for secret in secrets:
        data = SecretResponse.model_validate(secret)
        # Only include key_value for non-sensitive config options
        if secret.key_name in SAFE_TO_RETURN and secret.is_configured:
            data.key_value = secret.key_value
        response.append(data)
    
    return response


@router.post("/secrets", response_model=SecretResponse)
async def create_or_update_secret(
    secret_data: SecretCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Create or update a secret (admin only) - values are encrypted at rest and stored in Secret Manager"""
    from app.core.encryption import encrypt
    from app.core.managed import reject_platform_key_writes
    from app.services.secret_manager import set_secret, clear_cache

    reject_platform_key_writes(secret_data.key_name)

    # Bootstrap keys that must stay in database (needed to access Secret Manager)
    bootstrap_keys = {"GCP_SERVICE_ACCOUNT_JSON", "GOOGLE_CLOUD_PROJECT"}
    
    # Try to write to Secret Manager first (if not a bootstrap key)
    sm_success = False
    if secret_data.key_value and secret_data.key_name not in bootstrap_keys:
        try:
            sm_success = await set_secret(secret_data.key_name, secret_data.key_value)
            if sm_success:
                clear_cache()  # Clear cache so reads get fresh data
        except Exception as e:
            logger.warning(f"Failed to write to Secret Manager, using database only: {e}")
    
    # Always store in database as backup (encrypted)
    result = await db.execute(
        select(SystemSecret).where(SystemSecret.key_name == secret_data.key_name)
    )
    secret = result.scalar_one_or_none()
    
    # Encrypt the secret value before storing
    encrypted_value = encrypt(secret_data.key_value) if secret_data.key_value else None
    
    if secret:
        secret.key_value = encrypted_value
        secret.is_configured = bool(secret_data.key_value)
    else:
        secret = SystemSecret(
            key_name=secret_data.key_name,
            key_value=encrypted_value,
            description=secret_data.description,
            is_configured=bool(secret_data.key_value)
        )
        db.add(secret)
    
    await db.commit()
    await db.refresh(secret)
    
    return {
        **secret.__dict__,
        "secret_manager": sm_success,
        "_sa_instance_state": None  # Remove SQLAlchemy internal state
    }



@router.post("/secrets/sync")
async def sync_secrets(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Add any missing secrets from the default list (admin only)"""
    from app.db.init_db import DEFAULT_SECRETS
    
    added = []
    for secret_data in DEFAULT_SECRETS:
        result = await db.execute(
            select(SystemSecret).where(SystemSecret.key_name == secret_data["key_name"])
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            secret = SystemSecret(
                key_name=secret_data["key_name"],
                description=secret_data.get("description", ""),
                is_configured=False
            )
            db.add(secret)
            added.append(secret_data["key_name"])
    
    await db.commit()
    return {"status": "success", "added_secrets": added, "count": len(added)}


@router.post("/secrets/migrate-to-secret-manager")
async def migrate_secrets_to_secret_manager(
    _: User = Depends(get_current_admin)
):
    """
    Migrate all configured secrets from database to Google Secret Manager.
    
    This copies encrypted database secrets to Secret Manager for production use.
    Bootstrap keys (GCP_SERVICE_ACCOUNT_JSON, GOOGLE_CLOUD_PROJECT) are skipped
    as they're needed to access Secret Manager itself.
    
    Safe to run multiple times - existing secrets are overwritten with latest values.
    """
    from app.services.secret_manager import migrate_to_secret_manager
    
    result = await migrate_to_secret_manager()
    return result


@router.post("/secrets/migrate-encryption")
async def migrate_secrets_to_encrypted(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Migrate existing plaintext secrets to encrypted format.
    
    This is a one-time migration for secrets that were stored before 
    encryption was implemented. Safe to run multiple times - already
    encrypted values are skipped.
    """
    from app.core.encryption import encrypt, is_encrypted
    
    result = await db.execute(
        select(SystemSecret).where(SystemSecret.is_configured == True)
    )
    secrets = result.scalars().all()
    
    migrated = []
    already_encrypted = []
    errors = []
    
    for secret in secrets:
        if not secret.key_value:
            continue
            
        # Check if already encrypted (starts with gAAAA)
        if is_encrypted(secret.key_value):
            already_encrypted.append(secret.key_name)
            continue
        
        try:
            # Encrypt the plaintext value
            secret.key_value = encrypt(secret.key_value)
            migrated.append(secret.key_name)
        except Exception as e:
            errors.append({"key": secret.key_name, "error": "Migration failed"})
    
    await db.commit()
    
    return {
        "status": "success",
        "migrated": migrated,
        "migrated_count": len(migrated),
        "already_encrypted": already_encrypted,
        "already_encrypted_count": len(already_encrypted),
        "errors": errors
    }


# ============ Document Retention ============

@router.get("/retention/states")
async def get_retention_states(
    _: User = Depends(get_current_admin)
):
    """Get all supported states with their retention policies"""
    from app.services.retention_service import get_all_states
    return get_all_states()


@router.get("/retention/policy")
async def get_current_retention_policy(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Get current retention policy configuration"""
    from app.services.retention_service import get_retention_policy, get_retention_stats
    
    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    
    state_code = settings.retention_state_code if settings else "NJ"
    override_days = settings.retention_days_override if settings else None
    mode = settings.retention_mode if settings else "anonymize"
    
    policy = get_retention_policy(state_code)
    stats = await get_retention_stats(db, state_code, override_days)
    
    from app.services.retention_scrub import describe_selection, normalise_mode

    return {
        "state_code": state_code,
        "policy": policy,
        "override_days": override_days,
        "effective_days": override_days if override_days else policy["retention_days"],
        "mode": normalise_mode(mode),
        # The catalog and this town's choice in one object, so the screen never
        # has to hold its own copy of what the fields are called.
        "scrub_fields": describe_selection(
            getattr(settings, "retention_scrub_fields", None) if settings else None
        ),
        "stats": stats
    }


@router.post("/retention/policy")
async def update_retention_policy(
    state_code: str = None,
    override_days: int = None,
    mode: str = None,
    scrub_fields: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Update retention policy configuration (admin only)"""
    from app.services.retention_service import get_retention_policy

    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()

    if not settings:
        settings = SystemSettings()
        db.add(settings)

    # If the state has pushed a managed retention/legal-hold policy, the town
    # can't override it here — it's controlled from the hosting control plane.
    managed = getattr(settings, "managed_policy", None) or {}
    if any(k in managed for k in ("retention_days", "retention_mode", "pii_anonymization", "legal_hold")):
        raise HTTPException(
            403,
            "Data-retention policy is managed by your state and can't be changed here.",
        )

    if state_code:
        # Validate state code
        policy = get_retention_policy(state_code)
        if policy["state_code"] == "DEFAULT" and state_code != "DEFAULT":
            raise HTTPException(400, f"Unknown state code: {state_code}")
        settings.retention_state_code = state_code.upper()
    
    if override_days is not None:
        # 0 is the explicit "clear the override, revert to the state default"
        # signal — without this, an override once set could never be removed.
        if override_days == 0:
            settings.retention_days_override = None
        elif override_days < 365:
            raise HTTPException(400, "Override must be at least 365 days (1 year)")
        else:
            settings.retention_days_override = override_days
    
    if mode:
        from app.services.retention_scrub import MODES, normalise_mode
        resolved = normalise_mode(mode)
        if resolved not in MODES:
            raise HTTPException(400, f"Mode must be one of: {', '.join(MODES)}")
        settings.retention_mode = resolved

    if scrub_fields is not None:
        from app.services.retention_scrub import FIELD_IDS, normalise_fields
        unknown = [f for f in scrub_fields if f not in FIELD_IDS]
        if unknown:
            # Rejected rather than quietly dropped. A field silently ignored is
            # a town believing it removes something it does not.
            raise HTTPException(400, f"Unknown fields to scrub: {', '.join(sorted(unknown))}")
        settings.retention_scrub_fields = normalise_fields(scrub_fields)
    
    await db.commit()
    await db.refresh(settings)
    
    return {
        "status": "updated",
        "state_code": settings.retention_state_code,
        "override_days": settings.retention_days_override,
        "mode": settings.retention_mode,
        "scrub_fields": settings.retention_scrub_fields,
    }


@router.get("/timezone")
async def get_town_timezone(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Which clock the console shows times on.

    Storage does not move. Every timestamp column is timestamptz and stays in
    UTC; this only decides what a screen converts it into.
    """
    from app.services.town_time import COMMON_TIMEZONES, normalise_timezone, offset_label

    settings = await read_settings_row(db)
    current = normalise_timezone(getattr(settings, "timezone", None) if settings else None)
    return {
        "timezone": current,
        "offset": offset_label(current),
        "configured": bool(getattr(settings, "timezone", None)) if settings else False,
        "common": [{"id": z, "offset": offset_label(z)} for z in COMMON_TIMEZONES],
    }


@router.post("/timezone")
async def set_town_timezone(
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    from app.services.town_time import is_valid_timezone, offset_label

    name = str(payload.get("timezone", "")).strip()
    if not is_valid_timezone(name):
        # Rejected rather than quietly falling back to UTC. Silently storing
        # something other than what was chosen is how a town ends up certain
        # its times are local when they are not.
        raise HTTPException(status_code=400, detail=f"Not a timezone this server recognises: {name or '(empty)'}")

    settings = await read_settings_row(db, create=True)
    settings.timezone = name
    await db.commit()
    return {"timezone": name, "offset": offset_label(name)}


@router.get("/retention/preview")
async def preview_retention_run(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """What pressing "Run now" would actually do.

    The button had no preview and no confirmation. In `delete` mode it
    permanently destroys resident records on one click, and the response came
    back before the task had touched anything, so nothing on screen could say
    what happened. Somebody deserves to see the number and the mode before
    that, not after.
    """
    from app.models import ServiceRequest
    from app.services.retention_scrub import describe_selection, normalise_mode
    from app.services.retention_service import get_retention_policy, get_retention_stats

    settings = await read_settings_row(db)
    if settings is not None and getattr(settings, "legal_hold", False):
        return {
            "eligible": 0,
            "on_legal_hold": 0,
            "mode": getattr(settings, "retention_mode", None) or "anonymize",
            "blocked": "legal_hold",
        }

    state_code = (settings.retention_state_code if settings else None) or "NJ"
    override_days = settings.retention_days_override if settings else None
    mode = normalise_mode(settings.retention_mode if settings else None)
    policy = get_retention_policy(state_code)
    stats = await get_retention_stats(db, state_code, override_days)

    # Flagged records are past their date and must not be touched. They are
    # counted separately rather than hidden, because "142 eligible" and "142
    # eligible, 3 of which will be skipped" are different sentences to somebody
    # approving a deletion.
    held = (await db.execute(
        select(func.count(ServiceRequest.id)).where(
            and_(ServiceRequest.status == "closed", ServiceRequest.flagged.is_(True))
        )
    )).scalar() or 0

    eligible = stats.get("eligible_for_archival", 0) if isinstance(stats, dict) else 0
    return {
        "eligible": eligible,
        "on_legal_hold": held,
        "will_act_on": max(0, eligible - held),
        "mode": mode,
        "state_code": state_code,
        "policy_name": policy.get("name"),
        "retention_days": override_days or policy.get("retention_days"),
        "cutoff_date": stats.get("cutoff_date") if isinstance(stats, dict) else None,
        # The word the caller has to send back. Deleting resident records on a
        # single click is not something to make easy.
        # Purge clears every field on every eligible record and cannot be
        # undone, so it is typed out rather than clicked.
        "confirmation_required": "PURGE" if mode == "purge" else None,
        "scrub_fields": [
            f["label"] for f in describe_selection(
                getattr(settings, "retention_scrub_fields", None) if settings else None
            ) if f["selected"]
        ],
    }


@router.post("/retention/run")
async def run_retention_now(
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Run retention enforcement now.

    In `delete` mode this permanently destroys records, so it requires the
    caller to echo back a confirmation word. A modal alone is a client-side
    courtesy; anything that can be done by a stray fetch should not be able to
    delete resident data.
    """
    from app.tasks.service_requests import enforce_retention_policy

    from app.services.retention_scrub import normalise_mode

    settings = await read_settings_row(db)
    mode = normalise_mode(settings.retention_mode if settings else None)
    if mode == "purge" and str(payload.get("confirm", "")).strip() != "PURGE":
        raise HTTPException(
            status_code=400,
            detail='This policy clears every field on every eligible record and cannot be '
                   'undone. Send confirm="PURGE" to proceed.',
        )

    task = enforce_retention_policy.delay()
    return {
        "status": "triggered",
        "task_id": task.id,
        "mode": mode,
        "message": "Retention enforcement started. It works through every eligible record.",
    }


@router.get("/retention/legal-hold")
async def get_legal_hold_requests(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Get all requests currently under legal hold (flagged)"""
    from app.models import ServiceRequest
    
    result = await db.execute(
        select(ServiceRequest).where(
            and_(
                ServiceRequest.flagged == True,
                ServiceRequest.deleted_at.is_(None)
            )
        ).order_by(ServiceRequest.requested_datetime.desc())
    )
    requests = result.scalars().all()
    
    return {
        "count": len(requests),
        "requests": [
            {
                "id": r.id,
                "service_request_id": r.service_request_id,
                "service_name": r.service_name,
                "description": r.description[:100] + "..." if r.description and len(r.description) > 100 else r.description,
                "status": r.status,
                "address": r.address,
                "requested_datetime": r.requested_datetime.isoformat() if r.requested_datetime else None,
                "closed_datetime": r.closed_datetime.isoformat() if r.closed_datetime else None,
            }
            for r in requests
        ]
    }


@router.get("/retention/export")
async def export_for_public_records(
    start_date: str = None,
    end_date: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Export records for OPRA/FOIA/public records requests.
    Uses state-specific format based on configured retention policy.
    """
    from app.services.retention_service import get_retention_policy
    from app.models import ServiceRequest
    from datetime import datetime, timezone
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    # Get current state policy
    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    state_code = settings.retention_state_code if settings else "NJ"
    policy = get_retention_policy(state_code)
    
    # Build query
    query = select(ServiceRequest).where(
        ServiceRequest.deleted_at.is_(None)
    ).order_by(ServiceRequest.requested_datetime.desc())
    
    if start_date:
        query = query.where(ServiceRequest.requested_datetime >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.where(ServiceRequest.requested_datetime <= datetime.fromisoformat(end_date))
    
    result = await db.execute(query)
    records = result.scalars().all()
    
    # Generate CSV with state-specific header
    output = io.StringIO()
    
    # Write header with public records law info
    output.write(f"# {policy['public_records_law']} EXPORT\n")
    output.write(f"# State: {policy['name']} ({state_code})\n")
    output.write(f"# Generated: {datetime.now(timezone.utc).isoformat()}Z\n")
    output.write(f"# Total Records: {len(records)}\n")
    output.write(f"# Exported by: {current_user.username}\n")
    output.write("#\n")
    
    writer = csv.writer(output)
    writer.writerow([
        "Request ID", "Service Type", "Status", "Submitted Date", 
        "Address", "Lat", "Long", "Description",
        "Resolution Date", "Resolution Notes"
    ])
    
    for r in records:
        # Handle archived records - show [Archived] for description
        desc = "[Content archived per retention policy]" if r.archived_at else (r.description or "")
        writer.writerow([
            r.service_request_id,
            r.service_name,
            r.status,
            r.requested_datetime.isoformat() if r.requested_datetime else "",
            r.address or "",
            r.lat or "",
            r.long or "",
            desc,
            r.closed_datetime.isoformat() if r.closed_datetime else "",
            r.completion_message or ""
        ])
    
    output.seek(0)
    
    # Create filename with law name
    law_abbrev = policy['public_records_law'].split('(')[0].strip().replace(' ', '_')
    filename = f"{law_abbrev}_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============ Statistics ============

@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """Get system statistics (staff only)"""
    # Total counts by status
    total = await db.execute(select(func.count(ServiceRequest.id)))
    total_count = total.scalar() or 0
    
    open_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.status == "open")
    )
    open_count = open_result.scalar() or 0
    
    in_progress_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.status == "in_progress")
    )
    in_progress_count = in_progress_result.scalar() or 0
    
    closed_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.status == "closed")
    )
    closed_count = closed_result.scalar() or 0
    
    # Requests by category
    category_result = await db.execute(
        select(ServiceRequest.service_name, func.count(ServiceRequest.id))
        .group_by(ServiceRequest.service_name)
    )
    requests_by_category = {row[0]: row[1] for row in category_result.all()}
    
    # Recent requests
    recent_result = await db.execute(
        select(ServiceRequest)
        .order_by(ServiceRequest.requested_datetime.desc())
        .limit(10)
    )
    recent_requests = recent_result.scalars().all()
    
    return StatisticsResponse(
        total_requests=total_count,
        open_requests=open_count,
        in_progress_requests=in_progress_count,
        closed_requests=closed_count,
        requests_by_category=requests_by_category,
        requests_by_status={
            "open": open_count,
            "in_progress": in_progress_count,
            "closed": closed_count
        },
        recent_requests=recent_requests
    )


# ============ Advanced Statistics (PostGIS-powered) ============

from sqlalchemy import text, extract
from datetime import timedelta
import json
from app.schemas import (
    AdvancedStatisticsResponse, HeatmapDataResponse, HotspotData, TrendData, DepartmentMetrics,
    PredictiveInsights, CostEstimate, RepeatLocation
)
from app.models import Department

# Redis client import (reuse from open311)
try:
    from app.api.open311 import redis_client
except ImportError:
    redis_client = None

STATS_CACHE_TTL = 300  # 5 minutes


@router.get("/advanced-statistics", response_model=AdvancedStatisticsResponse)
async def get_advanced_statistics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """Get advanced PostGIS-powered statistics (staff only, cached for 5 minutes)"""
    
    # Check cache first
    cache_key = "advanced_statistics"
    try:
        if redis_client:
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                data["cached_at"] = data.get("cached_at")
                return AdvancedStatisticsResponse(**data)
    except Exception:
        pass  # Redis unavailable

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    # ========== Basic Counts ==========
    
    total_result = await db.execute(select(func.count(ServiceRequest.id)).where(ServiceRequest.deleted_at.is_(None)))
    total_count = total_result.scalar() or 0
    
    open_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.deleted_at.is_(None), ServiceRequest.status == "open")
    )
    open_count = open_result.scalar() or 0
    
    in_progress_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.deleted_at.is_(None), ServiceRequest.status == "in_progress")
    )
    in_progress_count = in_progress_result.scalar() or 0
    
    closed_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.deleted_at.is_(None), ServiceRequest.status == "closed")
    )
    closed_count = closed_result.scalar() or 0
    
    # ========== Temporal Analytics ==========
    
    # Requests by hour of day
    hour_query = select(
        extract('hour', ServiceRequest.requested_datetime).label('hour'),
        func.count(ServiceRequest.id)
    ).where(ServiceRequest.deleted_at.is_(None)).group_by('hour')
    hour_result = await db.execute(hour_query)
    requests_by_hour = {int(row[0]): row[1] for row in hour_result.all() if row[0] is not None}
    # Fill missing hours with 0
    for h in range(24):
        if h not in requests_by_hour:
            requests_by_hour[h] = 0
    
    # Requests by day of week
    dow_query = select(
        extract('dow', ServiceRequest.requested_datetime).label('dow'),
        func.count(ServiceRequest.id)
    ).where(ServiceRequest.deleted_at.is_(None)).group_by('dow')
    dow_result = await db.execute(dow_query)
    day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    requests_by_day_of_week = {}
    for row in dow_result.all():
        if row[0] is not None:
            requests_by_day_of_week[day_names[int(row[0])]] = row[1]
    for day in day_names:
        if day not in requests_by_day_of_week:
            requests_by_day_of_week[day] = 0
    
    # Requests by month (last 12 months)
    month_query = select(
        func.to_char(ServiceRequest.requested_datetime, 'YYYY-MM').label('month'),
        func.count(ServiceRequest.id)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.requested_datetime >= now - timedelta(days=365)
    ).group_by('month').order_by('month')
    month_result = await db.execute(month_query)
    requests_by_month = {row[0]: row[1] for row in month_result.all() if row[0]}
    
    # Average resolution hours by category
    resolution_query = select(
        ServiceRequest.service_name,
        func.avg(
            extract('epoch', ServiceRequest.closed_datetime - ServiceRequest.requested_datetime) / 3600
        ).label('avg_hours')
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status == "closed",
        ServiceRequest.closed_datetime.isnot(None)
    ).group_by(ServiceRequest.service_name)
    resolution_result = await db.execute(resolution_query)
    avg_resolution_hours_by_category = {
        row[0]: round(float(row[1]), 2) if row[1] else 0 
        for row in resolution_result.all() if row[0]
    }
    
    # ========== Geospatial Analytics (PostGIS) ==========
    
    # Hotspot detection using PostGIS ST_ClusterDBSCAN
    # Cluster points within 500m with minimum 2 points per cluster
    hotspots = []
    try:
        # Get clusters with addresses, categories, and unique reporter count
        hotspot_query = text("""
            WITH clustered AS (
                SELECT 
                    id, lat, long, address, service_name, email,
                    ST_ClusterDBSCAN(location, eps := 0.005, minpoints := 2) OVER () as cluster_id
                FROM service_requests
                WHERE deleted_at IS NULL 
                AND location IS NOT NULL
            ),
            cluster_stats AS (
                SELECT 
                    cluster_id,
                    AVG(lat) as center_lat,
                    AVG(long) as center_lng,
                    COUNT(*) as point_count,
                    COUNT(DISTINCT email) as unique_reporters,
                    (ARRAY_AGG(address ORDER BY id DESC))[1] as sample_address,
                    (ARRAY_AGG(DISTINCT service_name))[1:3] as top_categories
                FROM clustered
                WHERE cluster_id IS NOT NULL
                GROUP BY cluster_id
            )
            SELECT center_lat, center_lng, point_count, cluster_id, sample_address, top_categories, unique_reporters
            FROM cluster_stats
            ORDER BY point_count DESC
            LIMIT 10
        """)
        hotspot_result = await db.execute(hotspot_query)
        for row in hotspot_result.mappings().all():
            hotspots.append(HotspotData(
                lat=float(row['center_lat']),
                lng=float(row['center_lng']),
                count=int(row['point_count']),
                cluster_id=int(row['cluster_id']),
                sample_address=row.get('sample_address'),
                top_categories=row.get('top_categories') or [],
                unique_reporters=int(row['unique_reporters']) if row.get('unique_reporters') else None
            ))
    except Exception as e:
        logger.warning(f"Hotspot query failed (PostGIS may not be enabled): {e}")
    
    # Geographic center
    center_query = select(
        func.avg(ServiceRequest.lat),
        func.avg(ServiceRequest.long)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.lat.isnot(None),
        ServiceRequest.long.isnot(None)
    )
    center_result = await db.execute(center_query)
    center_row = center_result.one_or_none()
    geographic_center = None
    if center_row and center_row[0] and center_row[1]:
        geographic_center = {"lat": float(center_row[0]), "lng": float(center_row[1])}
    
    # Geospatial metrics in imperial units (miles)
    # 1 meter = 0.000621371 miles, 1 sq meter = 0.0000003861 sq miles
    geographic_spread_miles = None
    total_coverage_sq_miles = None
    avg_distance_from_center_miles = None
    furthest_request_miles = None
    
    try:
        geo_metrics_query = text("""
            WITH centroid AS (
                SELECT ST_Centroid(ST_Collect(location))::geography as center
                FROM service_requests 
                WHERE deleted_at IS NULL AND location IS NOT NULL
            ),
            distances AS (
                SELECT 
                    ST_Distance(location::geography, (SELECT center FROM centroid)) as dist_meters
                FROM service_requests
                WHERE deleted_at IS NULL AND location IS NOT NULL
            )
            SELECT 
                STDDEV(dist_meters) * 0.000621371 as spread_miles,
                AVG(dist_meters) * 0.000621371 as avg_distance_miles,
                MAX(dist_meters) * 0.000621371 as max_distance_miles,
                (SELECT ST_Area(ST_ConvexHull(ST_Collect(location))::geography) * 0.0000003861 
                 FROM service_requests WHERE deleted_at IS NULL AND location IS NOT NULL) as coverage_sq_miles
            FROM distances
        """)
        geo_result = await db.execute(geo_metrics_query)
        geo_row = geo_result.mappings().one_or_none()
        if geo_row:
            geographic_spread_miles = round(float(geo_row['spread_miles']), 2) if geo_row['spread_miles'] else None
            avg_distance_from_center_miles = round(float(geo_row['avg_distance_miles']), 2) if geo_row['avg_distance_miles'] else None
            furthest_request_miles = round(float(geo_row['max_distance_miles']), 2) if geo_row['max_distance_miles'] else None
            total_coverage_sq_miles = round(float(geo_row['coverage_sq_miles']), 2) if geo_row['coverage_sq_miles'] else None
    except Exception as e:
        logger.warning(f"Geographic metrics query failed: {e}")
    
    # ========== Department Analytics ==========
    
    dept_result = await db.execute(select(Department))
    departments = dept_result.scalars().all()
    
    department_metrics = []
    for dept in departments:
        dept_total = await db.execute(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.assigned_department_id == dept.id
            )
        )
        dept_total_count = dept_total.scalar() or 0
        
        dept_open = await db.execute(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.assigned_department_id == dept.id,
                ServiceRequest.status == "open"
            )
        )
        dept_open_count = dept_open.scalar() or 0
        
        dept_closed = await db.execute(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.assigned_department_id == dept.id,
                ServiceRequest.status == "closed"
            )
        )
        dept_closed_count = dept_closed.scalar() or 0
        
        # Average resolution time for department
        dept_resolution = await db.execute(
            select(func.avg(
                extract('epoch', ServiceRequest.closed_datetime - ServiceRequest.requested_datetime) / 3600
            )).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.assigned_department_id == dept.id,
                ServiceRequest.status == "closed",
                ServiceRequest.closed_datetime.isnot(None)
            )
        )
        dept_avg_hours = dept_resolution.scalar()
        
        department_metrics.append(DepartmentMetrics(
            name=dept.name,
            total_requests=dept_total_count,
            open_requests=dept_open_count,
            avg_resolution_hours=round(float(dept_avg_hours), 2) if dept_avg_hours else None,
            resolution_rate=round(dept_closed_count / dept_total_count * 100, 1) if dept_total_count > 0 else 0
        ))
    
    # Top staff by resolutions
    staff_query = select(
        ServiceRequest.assigned_to,
        func.count(ServiceRequest.id)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status == "closed",
        ServiceRequest.assigned_to.isnot(None),
        ServiceRequest.assigned_to != ""
    ).group_by(ServiceRequest.assigned_to).order_by(func.count(ServiceRequest.id).desc()).limit(10)
    staff_result = await db.execute(staff_query)
    top_staff_by_resolutions = {row[0]: row[1] for row in staff_result.all() if row[0]}
    
    # ========== Performance Metrics ==========
    
    # Average resolution time overall
    overall_resolution = await db.execute(
        select(func.avg(
            extract('epoch', ServiceRequest.closed_datetime - ServiceRequest.requested_datetime) / 3600
        )).where(
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.status == "closed",
            ServiceRequest.closed_datetime.isnot(None)
        )
    )
    avg_resolution_hours = overall_resolution.scalar()
    if avg_resolution_hours:
        avg_resolution_hours = round(float(avg_resolution_hours), 2)
    
    # Backlog by age
    backlog_by_age = {"<1 day": 0, "1-3 days": 0, "3-7 days": 0, "1-2 weeks": 0, ">2 weeks": 0}
    open_requests_query = select(ServiceRequest.requested_datetime).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status.in_(["open", "in_progress"])
    )
    open_requests_result = await db.execute(open_requests_query)
    for row in open_requests_result.all():
        if row[0]:
            age = now - row[0].replace(tzinfo=None)
            if age < timedelta(days=1):
                backlog_by_age["<1 day"] += 1
            elif age < timedelta(days=3):
                backlog_by_age["1-3 days"] += 1
            elif age < timedelta(days=7):
                backlog_by_age["3-7 days"] += 1
            elif age < timedelta(days=14):
                backlog_by_age["1-2 weeks"] += 1
            else:
                backlog_by_age[">2 weeks"] += 1
    
    # Resolution rate (fixed: proper completion rate)
    # This is the percentage of all requests that have been successfully closed
    resolution_rate = round(closed_count / total_count * 100, 1) if total_count > 0 else 0
    
    # Category distribution
    category_query = select(
        ServiceRequest.service_name,
        func.count(ServiceRequest.id)
    ).where(ServiceRequest.deleted_at.is_(None)).group_by(ServiceRequest.service_name)
    category_result = await db.execute(category_query)
    requests_by_category = {row[0]: row[1] for row in category_result.all() if row[0]}
    
    # Flagged count
    flagged_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.flagged == True
        )
    )
    flagged_count = flagged_result.scalar() or 0
    
    # ========== Infrastructure Metrics ==========
    
    # Backlog by priority (current open + in_progress)
    priority_query = select(
        ServiceRequest.priority,
        func.count(ServiceRequest.id)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status.in_(["open", "in_progress"])
    ).group_by(ServiceRequest.priority)
    priority_result = await db.execute(priority_query)
    backlog_by_priority = {int(row[0]): row[1] for row in priority_result.all() if row[0]}
    # Ensure all priorities 1-10 are represented
    for p in range(1, 11):
        if p not in backlog_by_priority:
            backlog_by_priority[p] = 0
    
    # Current workload by staff (active assignments)
    workload_query = select(
        ServiceRequest.assigned_to,
        func.count(ServiceRequest.id)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status.in_(["open", "in_progress"]),
        ServiceRequest.assigned_to.isnot(None),
        ServiceRequest.assigned_to != ""
    ).group_by(ServiceRequest.assigned_to)
    workload_result = await db.execute(workload_query)
    workload_by_staff = {row[0]: row[1] for row in workload_result.all() if row[0]}
    
    # SLA tracking (open requests only, by age)
    open_by_age_sla = {"<1 day": 0, "1-3 days": 0, "3-7 days": 0, "1-2 weeks": 0, ">2 weeks": 0}
    open_only_query = select(ServiceRequest.requested_datetime).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status == "open"  # Only "open" status, not in_progress
    )
    open_only_result = await db.execute(open_only_query)
    for row in open_only_result.all():
        if row[0]:
            age = now - row[0].replace(tzinfo=None)
            if age < timedelta(days=1):
                open_by_age_sla["<1 day"] += 1
            elif age < timedelta(days=3):
                open_by_age_sla["1-3 days"] += 1
            elif age < timedelta(days=7):
                open_by_age_sla["3-7 days"] += 1
            elif age < timedelta(days=14):
                open_by_age_sla["1-2 weeks"] += 1
            else:
                open_by_age_sla[">2 weeks"] += 1
    
    # ========== Predictive & Government Analytics ==========
    
    # Labor cost rates (hourly, in dollars)
    LABOR_RATES = {
        "Pothole": 50, "Street Repair": 75, "Snow Removal": 50,
        "Sewer": 85, "Water": 85, "Traffic Signal": 65,
        "Drainage": 70, "Road Maintenance": 65
    }
    DEFAULT_LABOR_RATE = 55
    
    # Cost estimates by category
    cost_estimates = []
    for category, total_cat_count in requests_by_category.items():
        # Get avg resolution hours for this category
        avg_hours = avg_resolution_hours_by_category.get(category, 2.5)
        labor_rate = LABOR_RATES.get(category, DEFAULT_LABOR_RATE)
        estimated_cost = avg_hours * labor_rate
        
        # Count open tickets in this category
        open_cat_query = await db.execute(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.service_name == category,
                ServiceRequest.status.in_(["open", "in_progress"])
            )
        )
        open_in_category = open_cat_query.scalar() or 0
        
        cost_estimates.append(CostEstimate(
            category=category,
            avg_hours=round(avg_hours, 2),
            estimated_cost=round(estimated_cost, 2),
            open_tickets=open_in_category,
            total_estimated_cost=round(open_in_category * estimated_cost, 2)
        ))
    
    # Sort by total cost descending
    cost_estimates.sort(key=lambda x: x.total_estimated_cost, reverse=True)
    
    # Repeat locations (infrastructure maintenance indicators)
    repeat_locations = []
    try:
        repeat_query = text("""
            SELECT address, lat, long, COUNT(*) as request_count
            FROM service_requests
            WHERE deleted_at IS NULL 
            AND address IS NOT NULL
            AND lat IS NOT NULL
            AND long IS NOT NULL
            GROUP BY address, lat, long
            HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC
            LIMIT 10
        """)
        repeat_result = await db.execute(repeat_query)
        for row in repeat_result.mappings().all():
            if row['address'] and row['lat'] and row['long']:
                repeat_locations.append(RepeatLocation(
                    address=str(row['address']),
                    lat=float(row['lat']),
                    lng=float(row['long']),
                    request_count=int(row['request_count'])
                ))
    except Exception as e:
        logger.warning(f"Repeat locations query failed: {e}")
    
    # High-priority aging: requests still unresolved (open or in progress) for
    # more than 7 days whose *effective* priority is high (>= 8 on the 1-10 scale
    # the rest of the app uses). Effective priority mirrors the UI: the
    # human-approved manual_priority_score if set, else the AI suggestion in
    # ai_analysis, else the neutral default of 5. The legacy `priority` column is
    # unused (always its default), so it must not be used here.
    aging_candidates = await db.execute(
        select(ServiceRequest.manual_priority_score, ServiceRequest.ai_analysis).where(
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.status.in_(["open", "in_progress"]),
            ServiceRequest.requested_datetime < now - timedelta(days=7),
        )
    )
    aging_high_priority_count = 0
    for manual_score, ai in aging_candidates.all():
        if manual_score is not None:
            effective = manual_score
        elif isinstance(ai, dict) and ai.get("priority_score") is not None:
            effective = ai.get("priority_score")
        else:
            effective = 5
        try:
            if float(effective) >= 8:
                aging_high_priority_count += 1
        except (TypeError, ValueError):
            # A non-numeric priority in ai_analysis is bad data, not a high
            # priority. Skip the row rather than counting or raising on it.
            pass
    
    # ========== Trends ==========
    
    # Weekly trend (last 8 weeks)
    weekly_trend = []
    for i in range(7, -1, -1):
        week_start = now - timedelta(weeks=i+1)
        week_end = now - timedelta(weeks=i)
        # Label each point with the week's start date (e.g. "Jul 21") rather than
        # a generic "W1"..."W8", so the axis and tooltip show real dates.
        week_label = f"{week_start.strftime('%b')} {week_start.day}"
        
        week_stats = {"period": week_label, "open": 0, "in_progress": 0, "closed": 0, "total": 0}
        for status in ["open", "in_progress", "closed"]:
            count_result = await db.execute(
                select(func.count(ServiceRequest.id)).where(
                    ServiceRequest.deleted_at.is_(None),
                    ServiceRequest.status == status,
                    ServiceRequest.requested_datetime >= week_start,
                    ServiceRequest.requested_datetime < week_end
                )
            )
            week_stats[status] = count_result.scalar() or 0
        week_stats["total"] = week_stats["open"] + week_stats["in_progress"] + week_stats["closed"]
        weekly_trend.append(TrendData(**week_stats))
    
    # Monthly trend (last 6 months)
    monthly_trend = []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=30*i)).replace(day=1)
        if i > 0:
            month_end = (now.replace(day=1) - timedelta(days=30*(i-1))).replace(day=1)
        else:
            month_end = now
        month_label = month_start.strftime("%b")
        
        month_stats = {"period": month_label, "open": 0, "in_progress": 0, "closed": 0, "total": 0}
        for status in ["open", "in_progress", "closed"]:
            count_result = await db.execute(
                select(func.count(ServiceRequest.id)).where(
                    ServiceRequest.deleted_at.is_(None),
                    ServiceRequest.status == status,
                    ServiceRequest.requested_datetime >= month_start,
                    ServiceRequest.requested_datetime < month_end
                )
            )
            month_stats[status] = count_result.scalar() or 0
        month_stats["total"] = month_stats["open"] + month_stats["in_progress"] + month_stats["closed"]
        monthly_trend.append(TrendData(**month_stats))
    
    # Predictive insights
    # Volume forecast (simple moving average of last 4 weeks)
    if len(weekly_trend) >= 4:
        recent_volumes = [w.total for w in weekly_trend[-4:]]
        volume_forecast_next_week = int(sum(recent_volumes) / len(recent_volumes))
    else:
        volume_forecast_next_week = 0
    
    # Trend direction (compare last 2 weeks vs previous 2 weeks)
    if len(weekly_trend) >= 4:
        recent_avg = sum(w.total for w in weekly_trend[-2:]) / 2
        previous_avg = sum(w.total for w in weekly_trend[-4:-2]) / 2
        if recent_avg > previous_avg * 1.1:
            trend_direction = "increasing"
        elif recent_avg < previous_avg * 0.9:
            trend_direction = "decreasing"
        else:
            trend_direction = "stable"
    else:
        trend_direction = "stable"
    
    # Seasonal patterns
    peak_day = max(requests_by_day_of_week.items(), key=lambda x: x[1])[0] if requests_by_day_of_week else "Monday"
    peak_month = max(requests_by_month.items(), key=lambda x: x[1])[0] if requests_by_month else "January"
    if peak_month:
        # Extract month name from YYYY-MM format
        try:
            from datetime import datetime as dt, timezone
            peak_month = dt.strptime(peak_month, "%Y-%m").strftime("%B")
        except Exception:
            pass  # Month format conversion failed, keep original
    
    predictive_insights = PredictiveInsights(
        volume_forecast_next_week=volume_forecast_next_week,
        trend_direction=trend_direction,
        seasonal_peak_day=peak_day,
        seasonal_peak_month=peak_month
    )
    
    # Build response
    response_data = AdvancedStatisticsResponse(
        total_requests=total_count,
        open_requests=open_count,
        in_progress_requests=in_progress_count,
        closed_requests=closed_count,
        requests_by_hour=requests_by_hour,
        requests_by_day_of_week=requests_by_day_of_week,
        requests_by_month=requests_by_month,
        avg_resolution_hours_by_category=avg_resolution_hours_by_category,
        hotspots=hotspots,
        geographic_center=geographic_center,
        geographic_spread_miles=geographic_spread_miles,
        total_coverage_sq_miles=total_coverage_sq_miles,
        avg_distance_from_center_miles=avg_distance_from_center_miles,
        furthest_request_miles=furthest_request_miles,
        requests_density_by_zone={},
        department_metrics=department_metrics,
        top_staff_by_resolutions=top_staff_by_resolutions,
        avg_resolution_hours=avg_resolution_hours,
        avg_first_response_hours=None,  # Would need audit log analysis
        backlog_by_age=backlog_by_age,
        resolution_rate=resolution_rate,
        backlog_by_priority=backlog_by_priority,
        workload_by_staff=workload_by_staff,
        open_by_age_sla=open_by_age_sla,
        predictive_insights=predictive_insights,
        cost_estimates=cost_estimates,
        avg_response_time_hours=None,  # Would need comment/audit log analysis
        repeat_locations=repeat_locations,
        aging_high_priority_count=aging_high_priority_count,
        requests_by_category=requests_by_category,
        flagged_count=flagged_count,
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        cached_at=now
    )
    
    # Cache the result
    try:
        if redis_client:
            cache_data = response_data.model_dump()
            cache_data["cached_at"] = now.isoformat()
            await redis_client.setex(cache_key, STATS_CACHE_TTL, json.dumps(cache_data, default=str))
    except Exception:
        pass  # Redis cache write failed, non-critical
    
    return response_data


# ============ Spatial Bias Heatmap ============


@router.get("/heatmap-data", response_model=HeatmapDataResponse)
async def get_heatmap_data(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """
    Return two sets of weighted coordinates for spatial bias detection:
    - report_points: every request location (weight 1)
    - reporter_points: deduplicated by reporter email, rounded to ~100m grid

    Comparing the two heatmaps reveals areas where many reports come from
    few unique reporters (potential reporting bias / squeaky wheel effect).
    """
    from sqlalchemy import text as sa_text

    # Check cache
    cache_key = "heatmap_data"
    try:
        if redis_client:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
    except Exception:
        # Cache read is an optimisation; on any failure fall through and
        # recompute from the database.
        pass

    # All request coordinates (for "reports" heatmap)
    # Rounded to ~100m grid to avoid pinpointing individual addresses
    report_query = sa_text("""
        SELECT ROUND(lat::numeric, 3) as lat, ROUND(long::numeric, 3) as lng
        FROM service_requests
        WHERE deleted_at IS NULL
          AND lat IS NOT NULL
          AND long IS NOT NULL
    """)
    report_result = await db.execute(report_query)
    report_points = [
        {"lat": float(r["lat"]), "lng": float(r["lng"]), "weight": 1}
        for r in report_result.mappings().all()
    ]

    # Deduplicated reporter locations (rounded to ~100m grid cells)
    # Each unique (email, grid_cell) pair counts as 1 point
    # ROUND(lat, 3) ≈ 111m, ROUND(long, 3) ≈ 85m at mid-latitudes
    reporter_query = sa_text("""
        SELECT
            ROUND(lat::numeric, 3) as lat,
            ROUND(long::numeric, 3) as lng,
            COUNT(*) as weight
        FROM (
            SELECT DISTINCT ON (COALESCE(email, id::text), ROUND(lat::numeric, 3), ROUND(long::numeric, 3))
                lat, long, email, id
            FROM service_requests
            WHERE deleted_at IS NULL
              AND lat IS NOT NULL
              AND long IS NOT NULL
        ) unique_reporters
        GROUP BY ROUND(lat::numeric, 3), ROUND(long::numeric, 3)
    """)
    reporter_result = await db.execute(reporter_query)
    reporter_points = [
        {"lat": float(r["lat"]), "lng": float(r["lng"]), "weight": int(r["weight"])}
        for r in reporter_result.mappings().all()
    ]

    result = {
        "report_points": report_points,
        "reporter_points": reporter_points,
        "total_reports": len(report_points),
        "total_unique_reporters": len(reporter_points),
    }

    # Cache for 5 minutes
    try:
        if redis_client:
            await redis_client.setex(cache_key, STATS_CACHE_TTL, json.dumps(result))
    except Exception:
        # Failing to cache costs the next caller a recompute. The result is
        # already correct and must still be returned.
        pass

    return result


# ============ System Update ============


def _reject_if_managed():
    """In state-hosted (managed) mode, in-app self-update is disabled — upgrades
    come only from the orchestrator (publish image → panel rolls out). This also
    removes the biggest infra risk (git pull + docker compose via a mounted
    Docker socket) from the hosted fleet."""
    from app.core.config import get_settings
    if get_settings().managed_mode:
        raise HTTPException(
            status_code=403,
            detail="Updates are managed by your state's hosting platform and can't be triggered from here.",
        )


@router.post("/update")
async def update_system(_: User = Depends(get_current_admin)):
    """Pull updates from GitHub (admin only). Code changes reload automatically."""
    from app.core.managed import ensure_not_managed
    ensure_not_managed("Upgrading")  # hosted upgrades come only from the orchestrator (A2)
    try:
        # Get the project root
        project_root = os.environ.get("PROJECT_ROOT", "/project")
        
        # Add safe directory to fix ownership issues in Docker
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_root],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Pull latest code
        pull_result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if pull_result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Git pull failed: {pull_result.stderr}"
            )
        
        # Check what was updated
        git_output = pull_result.stdout.strip()
        
        # Determine if restart is needed
        needs_restart = any(x in git_output.lower() for x in [
            'requirements.txt', 'dockerfile', 'docker-compose', 'package.json'
        ])
        
        return {
            "status": "success",
            "message": "Updates pulled successfully. " + (
                "Container restart may be needed for dependency changes." 
                if needs_restart 
                else "Code changes will reload automatically."
            ),
            "git_output": git_output,
            "needs_restart": needs_restart
        }
    
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Update operation timed out"
        )
    except Exception as e:
        logger.error(f"Update operation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Update operation failed"
        )


# ============ Version Switcher ============

GITHUB_REPO = "Pinpoint-311/Pinpoint-311"
GITHUB_API_BASE = "https://api.github.com"


@router.get("/current-version")
async def get_current_version(_: User = Depends(get_current_admin)):
    """Get current git version information (admin only)."""
    try:
        project_root = os.environ.get("PROJECT_ROOT", "/project")
        
        # Add safe directory to fix ownership issues in Docker
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_root],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Get current commit SHA
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        if sha_result.returncode != 0:
            logger.warning(f"Git rev-parse failed: {sha_result.stderr}")
        current_sha = sha_result.stdout.strip()[:7] if sha_result.returncode == 0 else "unknown"
        
        # Get current tag (if on a tag)
        tag_result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        current_tag = tag_result.stdout.strip() if tag_result.returncode == 0 else None
        
        # Get commit date
        date_result = subprocess.run(
            ["git", "log", "-1", "--format=%ci"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        commit_date = date_result.stdout.strip() if date_result.returncode == 0 else None
        
        # Get commit message (first line)
        msg_result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        commit_message = msg_result.stdout.strip()[:60] if msg_result.returncode == 0 else None
        
        return {
            "sha": current_sha,
            "tag": current_tag,
            "commit_date": commit_date,
            "commit_message": commit_message,
            "display": current_tag or f"@{current_sha}"
        }
    except Exception as e:
        logger.error(f"Failed to get current version: {e}")
        return {"sha": "unknown", "tag": None, "commit_date": None, "display": "@unknown"}


@router.get("/releases")
async def get_releases(_: User = Depends(get_current_admin)):
    """Fetch available releases from GitHub (admin only)."""
    import httpx
    
    logger.info(f"[Releases] Starting fetch from GitHub API")
    logger.info(f"[Releases] GITHUB_API_BASE={GITHUB_API_BASE}, GITHUB_REPO={GITHUB_REPO}")
    
    try:
        releases = []
        recent_commits = []
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch releases
            releases_url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/releases"
            logger.info(f"[Releases] Fetching releases from: {releases_url}")
            response = await client.get(
                releases_url,
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            logger.info(f"[Releases] Releases response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    for r in data:
                        releases.append({
                            "tag": r.get("tag_name", "unknown"),
                            "name": r.get("name") or r.get("tag_name", "unknown"),
                            "body": r.get("body") or "No release notes.",
                            "published_at": r.get("published_at"),
                            "author": r.get("author", {}).get("login") if r.get("author") else None,
                            "html_url": r.get("html_url", ""),
                            "prerelease": r.get("prerelease", False),
                            "target_commitish": r.get("target_commitish")
                        })
            else:
                logger.warning(f"GitHub releases API returned {response.status_code}")
            
            # Also get recent commits from main for unreleased versions
            commits_response = await client.get(
                f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/commits",
                params={"per_page": 15, "sha": "main"},
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            
            if commits_response.status_code == 200:
                data = commits_response.json()
                if isinstance(data, list):
                    for commit in data:
                        c = commit.get("commit", {})
                        recent_commits.append({
                            "sha": commit.get("sha", "")[:7],
                            "full_sha": commit.get("sha", ""),
                            "message": c.get("message", "").split("\n")[0][:80],
                            "date": c.get("committer", {}).get("date", ""),
                            "author": c.get("author", {}).get("name", "Unknown")
                        })
            else:
                logger.warning(f"GitHub commits API returned {commits_response.status_code}")
            
            return {
                "releases": releases,
                "recent_commits": recent_commits
            }
    except httpx.TimeoutException:
        logger.warning("GitHub API request timed out")
        return {"releases": [], "recent_commits": []}
    except Exception as e:
        logger.error(f"Failed to fetch releases: {e}")
        return {"releases": [], "recent_commits": []}


@router.get("/releases/{ref}/security")
async def get_release_security(ref: str, _: User = Depends(get_current_admin)):
    """
    Fetch security verification status for a specific release/commit (admin only).
    Returns workflow run status for security scans, CodeQL, accessibility, etc.
    """
    import httpx
    
    # Workflow names to check - must match exactly the 'name:' field in each workflow file
    # Note: Accessibility only runs on PRs and schedule, not direct pushes
    SECURITY_WORKFLOWS = {
        "Security Scan (OWASP ZAP)": {"icon": "🛡️", "key": "owasp_zap"},
        "CodeQL Security Analysis": {"icon": "🔒", "key": "codeql"},
        "Build and Publish Docker Images": {"icon": "📦", "key": "docker_build"},
        "Accessibility Audit (axe-core)": {"icon": "♿", "key": "accessibility"}
    }
    
    try:
        import re
        # Validate ref to prevent SSRF via URL manipulation
        if not re.match(r'^[a-zA-Z0-9._\-/]+$', ref):
            raise HTTPException(status_code=400, detail="Invalid ref format")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            # First, resolve the ref to a commit SHA if it's a tag
            commit_sha = ref
            if ref.startswith("v") or not ref.isalnum():
                # It's likely a tag, resolve to SHA
                tag_response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/git/refs/tags/{ref}",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                if tag_response.status_code == 200:
                    tag_data = tag_response.json()
                    # Handle both lightweight and annotated tags
                    if tag_data["object"]["type"] == "commit":
                        commit_sha = tag_data["object"]["sha"]
                    else:
                        # Annotated tag - need to dereference
                        annotated_response = await client.get(
                            tag_data["object"]["url"],
                            headers={"Accept": "application/vnd.github.v3+json"}
                        )
                        if annotated_response.status_code == 200:
                            commit_sha = annotated_response.json().get("object", {}).get("sha", ref)
            
            # Get workflow runs for this commit
            runs_response = await client.get(
                f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/actions/runs",
                params={"head_sha": commit_sha, "per_page": 50},
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            
            verification = {}
            
            if runs_response.status_code == 200:
                runs = runs_response.json().get("workflow_runs", [])
                
                for workflow_name, info in SECURITY_WORKFLOWS.items():
                    matching_runs = [r for r in runs if r["name"] == workflow_name]
                    
                    if matching_runs:
                        # Get the most recent run for this workflow
                        latest_run = matching_runs[0]
                        verification[info["key"]] = {
                            "name": workflow_name,
                            "icon": info["icon"],
                            "status": latest_run["status"],  # queued, in_progress, completed
                            "conclusion": latest_run.get("conclusion"),  # success, failure, neutral, cancelled, skipped, timed_out
                            "run_url": latest_run["html_url"],
                            "run_id": latest_run["id"],
                            "created_at": latest_run["created_at"],
                            "passed": latest_run.get("conclusion") == "success"
                        }
                    else:
                        verification[info["key"]] = {
                            "name": workflow_name,
                            "icon": info["icon"],
                            "status": "not_found",
                            "conclusion": None,
                            "run_url": None,
                            "passed": None
                        }
            
            # Calculate overall security score
            checks = [v for v in verification.values() if v.get("conclusion") is not None]
            passed_checks = len([v for v in checks if v.get("passed")])
            total_checks = len(checks)
            
            return {
                "ref": ref,
                "commit_sha": commit_sha[:7] if len(commit_sha) > 7 else commit_sha,
                "verification": verification,
                "summary": {
                    "passed": passed_checks,
                    "total": total_checks,
                    "all_passed": passed_checks == total_checks and total_checks > 0,
                    "score": f"{passed_checks}/{total_checks}" if total_checks > 0 else "N/A"
                }
            }
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="GitHub API request timed out"
        )
    except Exception as e:
        logger.error(f"Failed to fetch security status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch security status"
        )


@router.post("/switch-version")
async def switch_version(
    ref: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Production-grade version deployment with automatic rollback.
    Disabled in managed mode — rollouts come only from the orchestrator (A2).

    This endpoint performs a full deployment cycle:
    1. Save rollback point (current git HEAD)
    2. Create database backup (pg_dump)
    3. Git checkout target version
    4. Run database migrations (alembic upgrade)
    5. Rebuild and restart all containers
    6. Health check the new deployment
    7. Automatic rollback on any failure
    """
    from app.core.managed import ensure_not_managed
    ensure_not_managed("Upgrading")
    import httpx
    from datetime import datetime, timezone

    project_root = os.environ.get("PROJECT_ROOT", "/project")
    deployment_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = "/project/backups"
    
    # Auto-detect the Docker Compose project name from running containers
    # IMPORTANT: Multiple compose projects may be running (production + demo instances).
    # We must identify the production project by matching its ConfigFiles to our project_root.
    try:
        project_name_result = subprocess.run(
            ["docker", "compose", "ls", "--format", "json"],
            capture_output=True, text=True, timeout=10
        )
        import json as _json
        if project_name_result.returncode == 0:
            projects = _json.loads(project_name_result.stdout)
            compose_project = "wwf-open-source-311-template"  # sensible default
            
            # Find the project whose config files match our project root
            for proj in projects:
                config_files = proj.get("ConfigFiles", "")
                # The production project's docker-compose.yml lives in project_root's parent
                # e.g. /home/ubuntu/WWF-Open-Source-311-Template/docker-compose.yml
                if project_root in config_files or "WWF-Open-Source-311-Template/docker-compose.yml" in config_files:
                    # Skip demo projects (their names contain "demo" or "p311demo")
                    if "demo" not in proj["Name"].lower():
                        compose_project = proj["Name"]
                        break
        else:
            compose_project = "wwf-open-source-311-template"
    except Exception:
        compose_project = "wwf-open-source-311-template"
    
    logger.info(f"[Deploy] Using compose project: {compose_project}")
    
    # Deployment state tracking
    state = {
        "original_sha": None,
        "backup_file": None,
        "migrations_run": False,
        "containers_rebuilt": False,
        "steps_completed": [],
        "errors": []
    }
    
    def log_step(step: str, success: bool = True, detail: str = ""):
        state["steps_completed"].append({
            "step": step,
            "success": success,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        if not success:
            state["errors"].append(f"{step}: {detail}")
    
    async def rollback():
        """Rollback to original state on failure."""
        rollback_errors = []
        
        # 1. Restore git to original SHA
        if state["original_sha"]:
            try:
                subprocess.run(
                    ["git", "checkout", state["original_sha"]],
                    cwd=project_root,
                    capture_output=True,
                    timeout=60
                )
                log_step("rollback_git", True, f"Restored to {state['original_sha'][:7]}")
            except Exception as e:
                rollback_errors.append(f"Git rollback failed: {e}")
        
        # 2. Note: We don't auto-restore database because migrations are forward-only
        # and designed to be non-destructive. Admin should review if needed.
        if state["migrations_run"]:
            log_step("rollback_db", True, "Migrations were forward-only (additive). Manual review recommended if issues persist.")
        
        # 3. Restart original containers
        try:
            rollback_cmd = ["docker", "compose", "-p", compose_project]
            prod_compose = os.path.join(project_root, "docker-compose.prod.yml")
            if os.path.exists(prod_compose):
                rollback_cmd.extend(["-f", "docker-compose.yml", "-f", "docker-compose.prod.yml"])
            rollback_cmd.extend(["up", "-d", "--force-recreate", "backend", "frontend"])
            subprocess.run(
                rollback_cmd,
                cwd=project_root,
                capture_output=True,
                timeout=120
            )
            log_step("rollback_containers", True, "Restarted containers with original code")
        except Exception as e:
            rollback_errors.append(f"Container restart failed: {e}")
        
        return rollback_errors
    
    try:
        # ===== STEP 0: Setup =====
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_root],
            cwd=project_root,
            capture_output=True,
            timeout=10
        )
        
        # Create backup directory if it doesn't exist
        os.makedirs(backup_dir, exist_ok=True)
        
        # ===== STEP 1: Save Rollback Point =====
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        if sha_result.returncode != 0:
            raise Exception("Failed to get current git HEAD")
        
        state["original_sha"] = sha_result.stdout.strip()
        log_step("save_rollback_point", True, f"Saved: {state['original_sha'][:7]}")
        
        # ===== STEP 2: Create Database Backup =====
        backup_file = f"{backup_dir}/db_backup_{deployment_id}.sql"
        state["backup_file"] = backup_file
        
        # Get database URL from environment
        db_url = os.environ.get("DATABASE_URL", "")
        # Parse connection info (format: postgresql+asyncpg://user:pass@host/db)
        try:
            # Extract host, user, password, dbname from DATABASE_URL
            import re
            match = re.match(r"postgresql\+asyncpg://([^:]+):([^@]+)@([^/]+)/(.+)", db_url)
            if match:
                db_user, db_pass, db_host, db_name = match.groups()
                
                # Run pg_dump
                env = os.environ.copy()
                env["PGPASSWORD"] = db_pass
                
                backup_result = subprocess.run(
                    ["pg_dump", "-h", db_host.split(":")[0], "-U", db_user, "-d", db_name, "-f", backup_file],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 min timeout for large DBs
                )
                
                if backup_result.returncode == 0:
                    # Get backup size
                    backup_size = os.path.getsize(backup_file) if os.path.exists(backup_file) else 0
                    log_step("database_backup", True, f"Created {backup_size // 1024}KB backup")
                else:
                    log_step("database_backup", False, backup_result.stderr[:200])
                    # Continue anyway - backup failure shouldn't block deployment
            else:
                log_step("database_backup", False, "Could not parse DATABASE_URL")
        except Exception as e:
            log_step("database_backup", False, str(e)[:200])
        
        # ===== STEP 3: Git Fetch and Checkout =====
        # Stash any local changes
        subprocess.run(
            ["git", "stash"],
            cwd=project_root,
            capture_output=True,
            timeout=30
        )
        
        # Fetch all
        fetch_result = subprocess.run(
            ["git", "fetch", "--all", "--tags"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if fetch_result.returncode != 0:
            log_step("git_fetch", False, fetch_result.stderr[:200])
            raise Exception(f"Git fetch failed: {fetch_result.stderr}")
        
        log_step("git_fetch", True, "Fetched latest from remote")
        
        # Checkout target ref
        checkout_result = subprocess.run(
            ["git", "checkout", ref],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if checkout_result.returncode != 0:
            log_step("git_checkout", False, checkout_result.stderr[:200])
            raise Exception(f"Git checkout failed: {checkout_result.stderr}")
        
        # Get new SHA
        new_sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        new_sha = new_sha_result.stdout.strip()[:7] if new_sha_result.returncode == 0 else "unknown"
        log_step("git_checkout", True, f"Checked out {new_sha}")
        
        # ===== STEP 4: Run Database Migrations =====
        # Check if alembic.ini exists and run migrations
        alembic_cfg = os.path.join(project_root, "backend", "alembic.ini")
        if os.path.exists(alembic_cfg):
            try:
                migration_result = subprocess.run(
                    ["alembic", "upgrade", "head"],
                    cwd=os.path.join(project_root, "backend"),
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                if migration_result.returncode == 0:
                    state["migrations_run"] = True
                    log_step("database_migrations", True, "Applied pending migrations")
                else:
                    # Check if it's just "no migrations to run"
                    if "already at head" in migration_result.stdout.lower() or "no upgrade" in migration_result.stdout.lower():
                        log_step("database_migrations", True, "No new migrations")
                    else:
                        log_step("database_migrations", False, migration_result.stderr[:200])
                        raise Exception(f"Migration failed: {migration_result.stderr}")
            except subprocess.TimeoutExpired:
                log_step("database_migrations", False, "Migration timed out")
                raise Exception("Database migration timed out")
        else:
            log_step("database_migrations", True, "No alembic config found, skipping")
        
        # ===== STEP 5: Rebuild Containers =====
        try:
            # Detect which compose files are in use
            compose_files = []
            for f in ["docker-compose.yml", "docker-compose.prod.yml"]:
                fpath = os.path.join(project_root, f)
                if os.path.exists(fpath):
                    compose_files.append(f)
            log_step("compose_files_detected", True, ", ".join(compose_files))

            # Check if production compose is in use (uses prebuilt images, no local build)
            prod_compose = os.path.join(project_root, "docker-compose.prod.yml")
            uses_prebuilt = os.path.exists(prod_compose)

            if uses_prebuilt:
                # Production mode: pull latest images from GHCR instead of building locally
                log_step("deploy_mode", True, "Production (prebuilt GHCR images)")

                pull_result = subprocess.run(
                    ["docker", "compose", "-p", compose_project,
                     "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
                     "pull", "frontend", "backend"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=300
                )

                if pull_result.returncode != 0:
                    combined = (pull_result.stderr + pull_result.stdout)[-800:]
                    log_step("image_pull", False, combined)
                    raise Exception(f"Image pull failed: {combined}")

                log_step("image_pull", True, "Pulled latest images from GHCR")

                # Recreate containers with new images
                up_result = subprocess.run(
                    ["docker", "compose", "-p", compose_project,
                     "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml",
                     "up", "-d", "--force-recreate", "frontend", "backend"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if up_result.returncode != 0:
                    combined = (up_result.stderr + up_result.stdout)[-800:]
                    log_step("container_recreate", False, combined)
                    raise Exception(f"Container recreate failed: {combined}")

                state["containers_rebuilt"] = True
                log_step("container_recreate", True, "Recreated containers with new images")
            else:
                # Dev mode: build locally
                log_step("deploy_mode", True, "Development (local Docker build)")

                build_result = subprocess.run(
                    ["docker", "compose", "-p", compose_project, "build", "--no-cache", "frontend"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=600
                )

                if build_result.returncode != 0:
                    combined = (build_result.stderr + build_result.stdout)[-800:]
                    log_step("container_build", False, combined)
                    raise Exception(f"Container build failed: {combined}")

                log_step("container_build", True, "Built frontend image")

                restart_result = subprocess.run(
                    ["docker", "compose", "-p", compose_project, "up", "-d", "--force-recreate", "frontend"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if restart_result.returncode != 0:
                    combined = (restart_result.stderr + restart_result.stdout)[-800:]
                    log_step("container_restart", False, combined)
                    raise Exception(f"Container restart failed: {combined}")

                state["containers_rebuilt"] = True
                log_step("container_restart", True, "Restarted frontend container with new code")

        except subprocess.TimeoutExpired:
            log_step("container_rebuild", False, "Container rebuild timed out (10 min limit)")
            raise Exception("Container rebuild timed out")
        
        # ===== STEP 6: Health Check =====
        # Wait for containers to be healthy
        import asyncio
        await asyncio.sleep(10)  # Give containers time to start
        
        health_ok = False
        for attempt in range(6):  # 6 attempts over 30 seconds
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Check backend health
                    health_resp = await client.get("http://localhost:8000/api/health")
                    if health_resp.status_code == 200:
                        health_ok = True
                        break
            except Exception:
                pass  # Health check attempt failed, will retry
            await asyncio.sleep(5)
        
        if not health_ok:
            log_step("health_check", False, "Backend health check failed after 30s")
            raise Exception("Health check failed - backend not responding")
        
        log_step("health_check", True, "Backend healthy and responding")
        
        # ===== STEP 7: Log to Audit =====
        try:
            audit_entry = AuditLog(
                user_id=current_user.id,
                username=current_user.username if hasattr(current_user, 'username') else str(current_user.id),
                event_type="version_deployed",
                success=True,
                details={
                    "deployment_id": deployment_id,
                    "from_sha": state["original_sha"][:7],
                    "to_sha": new_sha,
                    "to_ref": ref,
                    "backup_file": state["backup_file"],
                    "migrations_run": state["migrations_run"],
                    "steps": state["steps_completed"]
                }
            )
            db.add(audit_entry)
            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to log deployment to audit: {e}")
        
        # ===== SUCCESS =====
        return {
            "status": "success",
            "message": f"Successfully deployed @{new_sha}",
            "deployment_id": deployment_id,
            "from_sha": state["original_sha"][:7],
            "to_sha": new_sha,
            "ref": ref,
            "backup_file": state["backup_file"],
            "migrations_run": state["migrations_run"],
            "steps": state["steps_completed"]
        }
        
    except Exception as e:
        # ===== ROLLBACK ON FAILURE =====
        log_step("deployment_failed", False, str(e)[:800])
        logger.error(f"Deployment failed, initiating rollback: {e}")
        
        rollback_errors = await rollback()
        
        # Log failed deployment to audit
        try:
            audit_entry = AuditLog(
                user_id=current_user.id,
                username=current_user.username if hasattr(current_user, 'username') else str(current_user.id),
                event_type="version_deployment_failed",
                success=False,
                failure_reason=str(e)[:255],
                details={
                    "deployment_id": deployment_id,
                    "target_ref": ref,
                    "error": str(e)[:1000],
                    "rollback_errors": rollback_errors,
                    "steps": state["steps_completed"]
                }
            )
            db.add(audit_entry)
            await db.commit()
        except Exception as audit_error:
            logger.warning(f"Failed to log deployment failure: {audit_error}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Deployment failed and rollback initiated",
                "error": str(e)[:1500],
                "rollback_performed": True,
                "rollback_errors": rollback_errors,
                "backup_available": state["backup_file"],
                "steps": state["steps_completed"],
                "deployment_id": deployment_id,
                "compose_project": compose_project,
            }
        )


# ============ Custom Domain ============

@router.post("/domain/configure")
async def configure_domain(
    domain: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Configure custom domain with automatic HTTPS via Caddy"""
    from app.core.managed import ensure_not_managed
    ensure_not_managed("Domain/DNS configuration")  # platform-managed in hosted mode (A1)
    import re
    import httpx

    # Validate domain format
    domain = domain.strip().lower()
    domain_regex = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$'
    if not re.match(domain_regex, domain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid domain format"
        )
    
    # Save domain to settings
    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    if settings:
        settings.custom_domain = domain
        await db.commit()
    
    # Generate Caddyfile with custom domain (Caddy auto-handles HTTPS)
    caddyfile_content = f"""# Global options - enable admin API for auto-reload
{{
    admin 0.0.0.0:2019
}}

# Caddy configuration for Township 311
# Auto-generated - Custom domain: {domain}

# Custom domain with automatic HTTPS
{domain} {{
    # API routes
    handle /api/* {{
        reverse_proxy backend:8000
    }}

    # Frontend - SPA routing
    handle {{
        reverse_proxy frontend:5173
    }}

    encode gzip

    header {{
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
    }}
}}

# Also keep IP access on HTTP for fallback
:80 {{
    handle /api/* {{
        reverse_proxy backend:8000
    }}
    handle {{
        reverse_proxy frontend:5173
    }}
    encode gzip
}}
"""
    
    # Write Caddyfile to shared volume
    caddyfile_path = os.environ.get("PROJECT_ROOT", "/project") + "/Caddyfile"
    
    try:
        with open(caddyfile_path, 'w') as f:
            f.write(caddyfile_content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to write Caddyfile"
        )
    
    # Try to reload Caddy via its admin API
    reload_success = False
    reload_message = ""
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to load the new Caddyfile config
            response = await client.post(
                "http://caddy:2019/load",
                content=caddyfile_content,
                headers={"Content-Type": "text/caddyfile"}
            )
            if response.status_code == 200:
                reload_success = True
                reload_message = "Caddy reloaded - HTTPS will be active shortly!"
            else:
                reload_message = f"Caddy API returned {response.status_code}. Container restart may be needed."
    except Exception as e:
        reload_message = f"Caddyfile saved but could not reload Caddy automatically. Please run: docker-compose restart caddy"
    
    return {
        "status": "success" if reload_success else "partial",
        "message": f"Domain {domain} configured! {reload_message}",
        "domain": domain,
        "url": f"https://{domain}",
        "reload_success": reload_success,
        "next_step": None if reload_success else "Run: docker-compose restart caddy"
    }


@router.get("/domain/status")
async def get_domain_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Get current domain configuration status"""
    result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = result.scalar_one_or_none()
    
    return {
        "custom_domain": settings.custom_domain if settings else None,
        "server_ip": "132.226.32.116"
    }


# ============ Image Upload ============

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/project/uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/upload/image")
async def upload_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_staff)
):
    """Upload an image file (staff only). Returns the URL to access it."""
    # Validate file extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Read and validate file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
        )
    
    # Generate unique filename
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    
    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Save file
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)
    
    # Return URL (relative to API)
    return {
        "url": f"/api/uploads/{unique_filename}",
        "filename": unique_filename
    }


# ============ Translation ============

from pydantic import BaseModel

class TranslationRequest(BaseModel):
    text: str
    source_lang: str = "en"
    target_lang: str = "es"


class MultiTranslationRequest(BaseModel):
    data: dict  # e.g., {"name": "Pothole", "description": "..."}
    source_lang: str = "en"
    target_languages: list[str] = None  # If None, translates to all supported languages


@router.get("/translate/languages")
async def get_supported_languages():
    """Get list of supported languages (public)"""
    from app.services.translation import get_supported_languages
    languages = get_supported_languages()
    return {
        "languages": [
            {"code": code, "name": name} 
            for code, name in languages.items()
        ]
    }


@router.post("/translate/health")
async def check_translation_service(
    _: User = Depends(get_current_admin)
):
    """Check if Google Cloud Translation API key is configured (admin only)"""
    from app.services.translation import check_translation_service
    is_available = await check_translation_service()
    return {
        "available": is_available,
        "service": "Google Cloud Translation",
        "url": "https://cloud.google.com/translate"
    }


@router.post("/translate/suggest")
async def suggest_translation(
    request: TranslationRequest,
    _: User = Depends(get_current_admin)
):
    """
    Auto-translate text using LibreTranslate (admin only).
    Used by Admin Console to suggest translations for service categories, departments, etc.
    """
    from app.services.translation import translate_text
    
    translated = await translate_text(
        request.text,
        request.source_lang,
        request.target_lang
    )
    
    if translated is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Translation service unavailable"
        )
    
    return {
        "original": request.text,
        "translated": translated,
        "source_lang": request.source_lang,
        "target_lang": request.target_lang
    }


@router.post("/translate/auto")
async def auto_translate_object(
    request: MultiTranslationRequest,
    _: User = Depends(get_current_admin)
):
    """
    Auto-translate an object (dictionary) to multiple languages (admin only).
    Returns translation dictionary ready to be saved to database.
    
    Example input:
    {
        "data": {"name": "Pothole Repair", "description": "Report road damage"},
        "source_lang": "en",
        "target_languages": ["es", "zh"]
    }
    
    Example output:
    {
        "translations": {
            "en": {"name": "Pothole Repair", "description": "Report road damage"},
            "es": {"name": "Repar

ación de Baches", "description": "Reportar daños en carreteras"},
            "zh": {"name": "坑洼修复", "description": "报告道路损坏"}
        }
    }
    """
    from app.services.translation import auto_translate_object as translate_obj
    
    translations = await translate_obj(
        request.data,
        request.source_lang,
        request.target_languages
    )
    
    return {"translations": translations}


@router.post("/translate/batch")
@_cost_limiter.limit("60/minute")
async def batch_translate(
    request: Request
):
    """
    Batch translate multiple UI strings (public endpoint).
    Used by frontend to translate static UI text.
    Uses database caching - first call hits Google API, subsequent calls use DB.
    """
    from app.services.translation import translate_batch
    
    data = await request.json()
    texts = data.get("texts", [])
    target_lang = data.get("target_lang", "es")
    
    if not texts:
        return {"translations": []}
    
    # Use batch translation with database caching
    results = await translate_batch(texts, "en", target_lang)
    
    # Return translations in order
    translations = [results.get(text, text) for text in texts]
    
    return {"translations": translations}



# ============ Database Backups ============

@router.get("/backups/status")
async def get_backup_status_endpoint(
    _: User = Depends(get_current_admin)
):
    """Get backup system status including configuration and last backup"""
    from app.services.backup_service import get_backup_status
    return await get_backup_status()


@router.get("/backups")
async def list_backups_endpoint(
    _: User = Depends(get_current_admin)
):
    """List all available database backups"""
    from app.services.backup_service import list_backups
    return await list_backups()


@router.post("/backups/create")
async def create_backup_endpoint(
    _: User = Depends(get_current_admin)
):
    """Trigger a manual database backup"""
    from app.core.managed import ensure_not_managed
    ensure_not_managed("Backup management")  # state-run DR in hosted mode (A1)
    from app.services.backup_service import create_backup

    result = await create_backup()
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail="Backup failed")
    
    return result


@router.post("/backups/cleanup")
async def cleanup_backups_endpoint(
    retention_days: int = None,
    _: User = Depends(get_current_admin)
):
    """Clean up old backups based on retention policy"""
    from app.core.managed import ensure_not_managed
    ensure_not_managed("Backup management")
    from app.services.backup_service import cleanup_old_backups
    return await cleanup_old_backups(retention_days)


@router.delete("/backups/{backup_name}")
async def delete_backup_endpoint(
    backup_name: str,
    _: User = Depends(get_current_admin)
):
    """Delete a specific backup"""
    from app.core.managed import ensure_not_managed
    ensure_not_managed("Backup management")
    from app.services.backup_service import delete_backup

    result = await delete_backup(backup_name)
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail="Delete failed")
    
    return result


@router.post("/backups/{backup_name}/restore")
async def restore_backup_endpoint(
    backup_name: str,
    confirm: bool = Query(False, description="Must be true to confirm restore - this will overwrite the database!"),
    _: User = Depends(get_current_admin)
):
    """
    Restore database from a backup.
    
    WARNING: This will overwrite the current database!
    You must pass confirm=true to proceed.
    """
    from app.core.managed import ensure_not_managed
    ensure_not_managed("Backup restore")
    if not confirm:
        raise HTTPException(
            status_code=400, 
            detail="You must pass confirm=true to restore. WARNING: This will overwrite the current database!"
        )
    
    from app.services.backup_service import restore_backup
    
    result = await restore_backup(backup_name)
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail="Restore failed")
    
    return result


# ============ Health Dashboard (Bus Factor Mitigation) ============

@router.get("/health-dashboard")
async def get_health_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Comprehensive system health dashboard for non-technical administrators.
    Returns status of all services, database metrics, and last backup info.
    """
    from datetime import datetime, timezone
    
    health = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {},
        "database": {},
        "cache": {},
        "last_backup": None,
        "overall_status": "healthy"
    }
    
    # Check service health via network (works from inside containers)
    
    # Every value in here is a *detail*, not an uptime.
    #
    # The field was called "uptime" and held strings like "Port 5173 active"
    # and "6.2 GB - 12 conns". Nothing in this product measures availability
    # over a period, so the name promised a statistic that does not exist and
    # was never computed. Renamed to `detail`; `uptime` is still emitted
    # alongside it for one release so an older frontend does not blank out.
    def _svc(status: str, detail: str) -> dict:
        return {"status": status, "detail": detail, "uptime": detail}

    # True by construction: this code is running, so the backend is.
    health["services"]["backend"] = _svc("running", "Responding to this request")
    
    # Check frontend via socket - try configured port or common ports
    import os
    frontend_ports = []
    # Check env var first
    if os.getenv("FRONTEND_PORT"):
        frontend_ports.append(int(os.getenv("FRONTEND_PORT")))
    # Common frontend ports (Vite default, then others)
    frontend_ports.extend([5173, 3000, 80, 8080])
    # Remove duplicates while preserving order
    frontend_ports = list(dict.fromkeys(frontend_ports))
    
    # The hostname was hardcoded to 'frontend', which is a docker-compose
    # service name. On any deployment not using that exact topology -- a single
    # container, a static bundle behind a CDN, separate hosts -- the connect
    # fails and the page reports the frontend down while a clerk is looking at
    # it. Configurable, and the failure below now says "could not check" rather
    # than "stopped".
    frontend_host = os.getenv("FRONTEND_HOST", "frontend")

    frontend_found = False
    for port in frontend_ports:
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((frontend_host, port))
            sock.close()
            if result == 0:
                health["services"]["frontend"] = _svc("running", f"Reachable on port {port}")
                frontend_found = True
                break
        except Exception:
            continue
    
    if not frontend_found:
        # "stopped" would be a claim. All that is known is that nothing
        # answered at the address we tried, which on an unusual topology says
        # more about the address than about the frontend.
        health["services"]["frontend"] = {
            **_svc("unknown", f"No answer from {frontend_host} on "
                              f"{', '.join(str(p) for p in frontend_ports[:3])}"),
            "error": "No ports reachable",
        }
    
    # Database - checked below via SQL
    health["services"]["db"] = _svc("pending", "Checking...")
    
    # Redis - checked via redis_client
    health["services"]["redis"] = _svc("pending", "Checking...")
    
    # Caddy was hardcoded to "running" with no probe at all, on the reasoning
    # that a received request proves the proxy routed it. That holds only when
    # the request came through the proxy, and an admin on a port-forward or a
    # dev server talking to the backend directly gets a confident green tick on
    # a proxy that may be stopped.
    #
    # Now it says which of those it is, and never claims more than it checked.
    from app.services.system_probes import proxy_status
    _proxy = proxy_status(request.headers)
    health["services"]["caddy"] = _svc(_proxy["status"], _proxy["detail"])
    
    # Database size and connection count
    try:
        db_size_result = await db.execute(text(
            "SELECT pg_size_pretty(pg_database_size(current_database())) as size"
        ))
        health["database"]["size"] = db_size_result.scalar()
        
        conn_result = await db.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        ))
        health["database"]["connections"] = conn_result.scalar()
        health["database"]["status"] = "healthy"
        # Update service status
        health["services"]["db"] = _svc(
            "running",
            f"{health['database']['size']} • {health['database']['connections']} connections",
        )
    except Exception as e:
        health["database"]["status"] = "error"
        health["database"]["error"] = str(e)
        health["overall_status"] = "degraded"
        health["services"]["db"] = {"status": "error", "error": str(e)[:50]}
    
    # Redis health check - use dynamic port from environment
    try:
        import redis
        import os
        redis_port = 6379  # default
        # Check for explicit port
        if os.getenv("REDIS_PORT"):
            redis_port = int(os.getenv("REDIS_PORT"))
        # Or parse from REDIS_URL if available
        elif os.getenv("REDIS_URL"):
            import re
            match = re.search(r':(\d+)', os.getenv("REDIS_URL", ""))
            if match:
                redis_port = int(match.group(1))
        
        redis_direct = redis.Redis(host="redis", port=redis_port, socket_timeout=3)
        info = redis_direct.info()
        health["cache"]["status"] = "healthy"
        health["cache"]["used_memory"] = info.get("used_memory_human", "unknown")
        health["cache"]["connected_clients"] = info.get("connected_clients", 0)
        # Update service status
        health["services"]["redis"] = _svc(
            "running", f"Port {redis_port} • {health['cache']['used_memory']} memory",
        )
    except redis.ConnectionError:
        health["cache"]["status"] = "not_configured"
        health["cache"]["error"] = "Redis not available"
        health["services"]["redis"] = _svc("stopped", "Not reachable")
    except Exception as e:
        health["cache"]["status"] = "error"
        health["cache"]["error"] = str(e)
        health["overall_status"] = "degraded"
        health["services"]["redis"] = {"status": "error", "error": str(e)[:50]}
    
    # Last backup info
    try:
        from app.services.backup_service import list_backups
        backups = await list_backups()
        if backups.get("backups"):
            last = backups["backups"][0]
            health["last_backup"] = {
                "name": last.get("name"),
                "created": last.get("created"),
                "size": last.get("size")
            }
    except Exception:
        health["last_backup"] = {"status": "unknown"}
    
    # Check for any down services
    for svc, data in health["services"].items():
        if data.get("status") != "running":
            health["overall_status"] = "degraded"
            break
    
    return health


# ============ Runbook Automation (Emergency Operations) ============

@router.post("/runbook/{action}")
async def execute_runbook(
    action: str,
    backup_name: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Execute emergency runbook actions (admin only).
    
    Available actions:
    - restart-all: Restart all containers
    - restart-{service}: Restart specific service (backend, frontend, redis, caddy)
    - clear-cache: Clear Redis cache
    - vacuum: Run PostgreSQL vacuum analyze
    - restore: Restore from backup (requires backup_name parameter)

    Disabled in managed mode — infrastructure operations come only from the
    orchestrator (A2).
    """
    from app.core.managed import ensure_not_managed
    ensure_not_managed("Infrastructure runbook execution")
    from datetime import datetime, timezone
    
    result = {
        "action": action,
        "executed_by": current_user.email,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "success",
        "details": {}
    }
    
    import shutil

    def _compose_cmd():
        """Resolve a usable Docker Compose command, or None if unavailable.

        Prefers Compose v2 (`docker compose`) and falls back to v1
        (`docker-compose`). Also requires the project directory to exist — the
        app can only drive Compose if it has the Docker socket + the repo on disk
        (e.g. a self-hosted host mount), which isn't the case in many
        environments. Returns (cmd_list, project_root) or (None, project_root)."""
        project_root = os.environ.get("PROJECT_ROOT", "/project")
        if not os.path.isdir(project_root):
            return None, project_root
        if shutil.which("docker"):
            return ["docker", "compose"], project_root
        if shutil.which("docker-compose"):
            return ["docker-compose"], project_root
        return None, project_root

    try:
        if action == "restart-all" or action.startswith("restart-"):
            services = (
                ["backend", "frontend", "redis", "caddy"]
                if action == "restart-all"
                else [action.replace("restart-", "")]
            )
            for service in services:
                if service not in ["backend", "frontend", "redis", "caddy"]:
                    raise HTTPException(status_code=400, detail=f"Cannot restart service: {service}")

            compose, project_root = _compose_cmd()
            if not compose:
                # Report honestly rather than pretending it worked.
                result["status"] = "unavailable"
                result["details"]["error"] = (
                    "Container restarts aren't available to the app in this environment "
                    "(Docker Compose or the project directory isn't reachable). "
                    "Run `docker compose restart <service>` on the host instead."
                )
            else:
                restarted, failed = [], {}
                for service in services:
                    proc = subprocess.run(
                        compose + ["restart", service],
                        cwd=project_root, capture_output=True, timeout=60, text=True,
                    )
                    if proc.returncode == 0:
                        restarted.append(service)
                    else:
                        failed[service] = (proc.stderr or proc.stdout or "restart failed").strip()[:300]
                result["details"]["restarted"] = restarted
                if failed:
                    result["details"]["failed"] = failed
                    result["status"] = "partial" if restarted else "error"
                if action == "restart-all":
                    result["details"]["note"] = "Database not restarted for safety"

        elif action == "clear-cache":
            if redis_client:
                await redis_client.flushdb()
                result["details"]["cleared"] = True
            else:
                result["status"] = "skipped"
                result["details"]["reason"] = "Redis not configured"

        elif action == "vacuum":
            # VACUUM cannot run inside a transaction block, so use a dedicated
            # AUTOCOMMIT connection rather than the request's transactional session.
            from app.db.session import engine
            async with engine.connect() as conn:
                ac = conn.execution_options(isolation_level="AUTOCOMMIT")
                await ac.execute(text("VACUUM ANALYZE"))
            result["details"]["operation"] = "VACUUM ANALYZE completed"
        
        elif action == "restore":
            if not backup_name:
                raise HTTPException(status_code=400, detail="backup_name required for restore action")
            from app.services.backup_service import restore_backup
            restore_result = await restore_backup(backup_name)
            result["details"] = restore_result
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        
        # Log the action to audit
        try:
            from app.models import RequestAuditLog
            audit = RequestAuditLog(
                request_id=None,
                user_id=current_user.id,
                action=f"runbook_{action}",
                details=json.dumps(result["details"])
            )
            db.add(audit)
            await db.commit()
        except Exception:
            pass  # Don't fail if audit logging fails
        
        return result
        
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["details"]["error"] = "Operation timed out after 60 seconds"
        raise HTTPException(status_code=504, detail="Operation timed out")
    except HTTPException:
        raise
    except Exception as e:
        result["status"] = "error"
        result["details"]["error"] = str(e)
        raise HTTPException(status_code=500, detail="Operation failed")


# ============ AI Analytics Chat ============

from pydantic import BaseModel
from datetime import timedelta

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class AnalyticsChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []

class AnalyticsChatResponse(BaseModel):
    response: str
    context_used: List[str]


@router.post("/analytics-chat", response_model=AnalyticsChatResponse)
@_cost_limiter.limit("20/minute")
async def analytics_chat(
    request: Request,
    body: AnalyticsChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """
    Conversational AI analytics — chat with Vertex AI about all system data.
    Gathers comprehensive context from across the platform (excluding resident PII)
    and uses Gemini 3.1 Flash-Lite to answer questions.
    """
    from datetime import datetime, timezone
    
    context_used = []
    now = datetime.now(timezone.utc)
    
    # ========== 1. System Settings (Township Identity) ==========
    settings_result = await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
    settings = settings_result.scalar_one_or_none()
    township_name = settings.township_name if settings and hasattr(settings, 'township_name') and settings.township_name else "the municipality"
    context_used.append("system_settings")
    
    # ========== 2. All Requests — Sanitized (No PII) ==========
    all_requests_result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.deleted_at.is_(None))
    )
    all_requests = all_requests_result.scalars().all()
    context_used.append("all_service_requests")
    
    total = len(all_requests)
    open_count = sum(1 for r in all_requests if r.status == "open")
    in_progress_count = sum(1 for r in all_requests if r.status == "in_progress")
    closed_count = sum(1 for r in all_requests if r.status == "closed")
    
    # Category breakdown
    categories = {}
    for r in all_requests:
        cat = r.service_name or "Unknown"
        categories[cat] = categories.get(cat, 0) + 1
    
    # Priority distribution
    high_priority = sum(1 for r in all_requests if (getattr(r, 'manual_priority_score', None) or (r.ai_analysis or {}).get('priority_score', 5) if isinstance(r.ai_analysis, dict) else 5) >= 8)
    med_priority = sum(1 for r in all_requests if 5 <= (getattr(r, 'manual_priority_score', None) or (r.ai_analysis or {}).get('priority_score', 5) if isinstance(r.ai_analysis, dict) else 5) < 8)
    low_priority = total - high_priority - med_priority
    
    # Resolution time for closed requests
    resolution_times = []
    for r in all_requests:
        if r.status == "closed" and r.closed_datetime and r.requested_datetime:
            hours = (r.closed_datetime - r.requested_datetime).total_seconds() / 3600
            resolution_times.append(hours)
    avg_resolution = sum(resolution_times) / len(resolution_times) if resolution_times else 0
    
    # ========== 3. Temporal Patterns ==========
    hourly = {}
    daily = {}
    monthly = {}
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for r in all_requests:
        if r.requested_datetime:
            h = r.requested_datetime.hour
            hourly[h] = hourly.get(h, 0) + 1
            d = day_names[r.requested_datetime.weekday()]
            daily[d] = daily.get(d, 0) + 1
            m = r.requested_datetime.strftime("%Y-%m")
            monthly[m] = monthly.get(m, 0) + 1
    
    busiest_hour = max(hourly, key=hourly.get) if hourly else "N/A"
    busiest_day = max(daily, key=daily.get) if daily else "N/A"
    context_used.append("temporal_patterns")
    
    # ========== 4. Geographic Data — Addresses + Hotspots ==========
    # Top addresses by request count (no resident names)
    address_counts = {}
    for r in all_requests:
        if r.address:
            address_counts[r.address] = address_counts.get(r.address, 0) + 1
    top_addresses = sorted(address_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    context_used.append("geographic_data")
    
    # ========== 5. Staff Data (No personal info beyond names/roles) ==========
    staff_result = await db.execute(
        select(User).where(User.role.in_(["staff", "admin"]))
    )
    staff_result.scalars().all()  # Materialize query results
    
    # Staff workload
    staff_workload = {}
    staff_resolutions = {}
    for r in all_requests:
        assigned = getattr(r, 'assigned_to', None) or getattr(r, 'agency_responsible', None)
        if assigned:
            if r.status in ("open", "in_progress"):
                staff_workload[assigned] = staff_workload.get(assigned, 0) + 1
            if r.status == "closed":
                staff_resolutions[assigned] = staff_resolutions.get(assigned, 0) + 1
    context_used.append("staff_data")
    
    # ========== 6. Department Data ==========
    from app.models import Department
    dept_result = await db.execute(select(Department).where(Department.is_active == True))
    departments = dept_result.scalars().all()
    dept_info = [{"name": d.name, "description": d.description or ""} for d in departments]
    context_used.append("departments")
    
    # ========== 7. AI Analysis Summaries ==========
    ai_summaries = []
    flagged_requests = []
    for r in all_requests:
        if r.ai_summary:
            ai_summaries.append({
                "id": r.service_request_id,
                "category": r.service_name,
                "address": r.address or "Unknown",
                "summary": r.ai_summary[:200],
                "classification": r.ai_classification,
                "priority": (r.ai_analysis or {}).get("priority_score") if isinstance(r.ai_analysis, dict) else None
            })
        if r.flagged:
            flagged_requests.append({
                "id": r.service_request_id,
                "reason": r.flag_reason,
                "category": r.service_name,
                "address": r.address or "Unknown"
            })
    context_used.append("ai_analysis")
    
    # ========== 8. Weather Context ==========
    weather_summary = ""
    try:
        # Get weather for the township's approximate center (from most common request coords)
        lats = [r.lat for r in all_requests if r.lat]
        lngs = [r.long for r in all_requests if r.long]
        if lats and lngs:
            center_lat = sum(lats) / len(lats)
            center_lng = sum(lngs) / len(lngs)
            from app.api.research import get_weather_context
            weather = get_weather_context(now, center_lat, center_lng)
            if weather.get("temp_max_c") is not None:
                weather_summary = f"Recent weather: High {weather['temp_max_c']}°C, Low {weather['temp_min_c']}°C, Precip {weather['precip_24h_mm']}mm"
                context_used.append("weather")
    except Exception as e:
        logger.warning(f"Weather context unavailable: {e}")
    
    # ========== 9. Research Fields — Social Equity, Sentiment, Friction ==========
    equity_summary = ""
    sentiment_summary = ""
    friction_summary = ""
    infra_summary = ""
    
    try:
        from app.api.research import (
            get_infrastructure_category, analyze_sentiment,
            detect_trust_indicators, generate_zone_id
        )
        
        # --- Infrastructure category breakdown (lightweight string lookup) ---
        infra_categories = {}
        for r in all_requests:
            cat = get_infrastructure_category(r.service_code)
            if cat:
                infra_categories[cat] = infra_categories.get(cat, 0) + 1
        if infra_categories:
            infra_summary = "Infrastructure Category Breakdown:\n" + \
                chr(10).join(f"- {cat}: {count}" for cat, count in sorted(infra_categories.items(), key=lambda x: x[1], reverse=True))
            context_used.append("infrastructure_categories")
        
        # --- Sentiment & Trust aggregates (sample ~50 recent with descriptions) ---
        desc_requests = [r for r in all_requests if r.description and len(r.description.strip()) > 10][:50]
        if desc_requests:
            sentiments = [analyze_sentiment(r.description) for r in desc_requests]
            valid_sentiments = [s for s in sentiments if s is not None]
            avg_sentiment = sum(valid_sentiments) / len(valid_sentiments) if valid_sentiments else 0
            
            trust_results = [detect_trust_indicators(r.description) for r in desc_requests]
            repeat_pct = sum(1 for t in trust_results if t.get('is_repeat_report')) / len(trust_results) * 100
            frustration_pct = sum(1 for t in trust_results if t.get('frustration_expressed')) / len(trust_results) * 100
            prior_ref_pct = sum(1 for t in trust_results if t.get('prior_report_mentioned')) / len(trust_results) * 100
            
            sentiment_summary = f"""Resident Sentiment Analysis (sampled {len(desc_requests)} recent requests):
- Average sentiment score: {avg_sentiment:.2f} (scale: -1.0 angry to +1.0 positive)
- Frustration expressed: {frustration_pct:.0f}% of requests
- Repeat reports: {repeat_pct:.0f}% of requests
- Prior report referenced: {prior_ref_pct:.0f}% of requests"""
            context_used.append("sentiment_trust")
        
        # --- Social Equity aggregates (sample requests with coordinates) ---
        try:
            from app.api.research import (
                get_census_tract_geoid, get_social_vulnerability_index,
                get_income_quintile_from_zone, get_population_density_category,
                get_housing_tenure_mix
            )
            
            geo_requests = [r for r in all_requests if r.lat and r.long][:30]
            if geo_requests:
                svi_values = []
                income_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
                density_dist = {"low": 0, "medium": 0, "high": 0}
                renter_pcts = []
                import asyncio
                
                async def fetch_equity_data(r):
                    try:
                        zone_id = generate_zone_id(r.lat, r.long)
                        geoid = await get_census_tract_geoid(r.lat, r.long)
                        
                        if not geoid:
                            return None
                        
                        # Fetch all metrics for this geoid concurrently
                        svi_task = get_social_vulnerability_index(geoid)
                        iq_task = get_income_quintile_from_zone(zone_id, geoid)
                        pd_cat_task = get_population_density_category(zone_id, geoid)
                        ht_task = get_housing_tenure_mix(geoid)
                        
                        svi, iq, pd_cat, ht = await asyncio.gather(
                            svi_task, iq_task, pd_cat_task, ht_task, 
                            return_exceptions=True
                        )
                        
                        return {
                            "svi": svi if not isinstance(svi, Exception) else None,
                            "iq": iq if not isinstance(iq, Exception) else None,
                            "pd_cat": pd_cat if not isinstance(pd_cat, Exception) else None,
                            "ht": ht if not isinstance(ht, Exception) else None
                        }
                    except Exception as e:
                        return None
                
                # Fetch all requests concurrently, with an overall timeout of 8 seconds
                tasks = [fetch_equity_data(r) for r in geo_requests]
                try:
                    results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=8.0)
                except asyncio.TimeoutError:
                    results = []
                
                for res in results:
                    if isinstance(res, dict):
                        if res.get("svi") is not None:
                            svi_values.append(res["svi"])
                        if res.get("iq") and res["iq"] in income_dist:
                            income_dist[res["iq"]] += 1
                        if res.get("pd_cat") and res["pd_cat"] in density_dist:
                            density_dist[res["pd_cat"]] += 1
                        if res.get("ht") is not None:
                            renter_pcts.append(res["ht"])
                
                avg_svi = sum(svi_values) / len(svi_values) if svi_values else None
                avg_renter = sum(renter_pcts) / len(renter_pcts) if renter_pcts else None
                
                equity_parts = [f"Social Equity Metrics (sampled {len(geo_requests)} requests):"]
                if avg_svi is not None:
                    equity_parts.append(f"- Average Social Vulnerability Index: {avg_svi:.2f} (0=low, 1=high)")
                if any(income_dist.values()):
                    equity_parts.append(f"- Income quintile distribution: Q1(lowest)={income_dist[1]}, Q2={income_dist[2]}, Q3={income_dist[3]}, Q4={income_dist[4]}, Q5(highest)={income_dist[5]}")
                if any(density_dist.values()):
                    equity_parts.append(f"- Population density: Low={density_dist['low']}, Medium={density_dist['medium']}, High={density_dist['high']}")
                if avg_renter is not None:
                    equity_parts.append(f"- Average renter percentage in request areas: {avg_renter*100:.0f}%")
                
                if len(equity_parts) > 1:
                    equity_summary = chr(10).join(equity_parts)
                    context_used.append("social_equity")
        except Exception as e:
            logger.warning(f"Social equity data unavailable: {e}")
        
        # --- Bureaucratic Friction aggregates ---
        try:
            from app.api.research import (
                calculate_time_to_triage, count_reassignments,
                is_off_hours_submission, calculate_escalation_occurred
            )
            
            # Load audit logs for a sample of requests
            sample_ids = [r.id for r in all_requests[:100]]
            if sample_ids:
                from app.models import RequestAuditLog
                audit_result = await db.execute(
                    select(RequestAuditLog).where(
                        RequestAuditLog.service_request_id.in_(sample_ids)
                    )
                )
                audit_logs_all = audit_result.scalars().all()
                
                # Group by request ID
                audit_by_request = {}
                for log in audit_logs_all:
                    audit_by_request.setdefault(log.service_request_id, []).append(log)
                
                triage_times = []
                reassignment_counts = []
                off_hours_count = 0
                escalation_count = 0
                sample_count = min(len(all_requests), 100)
                
                for r in all_requests[:100]:
                    req_audits = audit_by_request.get(r.id, [])
                    
                    tt = calculate_time_to_triage(r.requested_datetime, req_audits)
                    if tt is not None:
                        triage_times.append(tt)
                    
                    rc = count_reassignments(req_audits)
                    reassignment_counts.append(rc)
                    
                    if is_off_hours_submission(r.requested_datetime):
                        off_hours_count += 1
                    
                    if calculate_escalation_occurred(req_audits):
                        escalation_count += 1
                
                avg_triage = sum(triage_times) / len(triage_times) if triage_times else None
                avg_reassign = sum(reassignment_counts) / len(reassignment_counts) if reassignment_counts else 0
                
                friction_parts = [f"Bureaucratic Friction Metrics (sampled {sample_count} requests):"]
                if avg_triage is not None:
                    friction_parts.append(f"- Average time-to-triage: {avg_triage:.1f} hours")
                friction_parts.append(f"- Average reassignment count: {avg_reassign:.1f}")
                friction_parts.append(f"- Off-hours submissions: {off_hours_count}/{sample_count} ({off_hours_count/sample_count*100:.0f}%)")
                friction_parts.append(f"- Escalated requests: {escalation_count}/{sample_count} ({escalation_count/sample_count*100:.0f}%)")
                
                friction_summary = chr(10).join(friction_parts)
                context_used.append("bureaucratic_friction")
        except Exception as e:
            logger.warning(f"Bureaucratic friction data unavailable: {e}")
    
    except Exception as e:
        logger.warning(f"Research field aggregates unavailable: {e}")
    
    # ========== 10. Request Details — Sanitized List ==========
    request_details = []
    for r in all_requests[:100]:  # Cap at 100 most recent
        detail = {
            "id": r.service_request_id,
            "category": r.service_name,
            "status": r.status,
            "priority": r.priority,
            "address": r.address or "Unknown",
            "description": (r.description[:150] + "...") if r.description and len(r.description) > 150 else r.description,
            "source": r.source,
            "created": r.requested_datetime.isoformat() if r.requested_datetime else None,
            "closed": r.closed_datetime.isoformat() if r.closed_datetime else None,
        }
        if r.ai_analysis and isinstance(r.ai_analysis, dict):
            detail["ai_priority"] = r.ai_analysis.get("priority_score")
            detail["ai_category"] = r.ai_classification
        if r.flagged:
            detail["flagged"] = True
            detail["flag_reason"] = r.flag_reason
        request_details.append(detail)
    
    # ========== Build the System Prompt ==========
    system_prompt = f"""You are an expert municipal analytics advisor for {township_name}. You have deep access to the community's 311 service request system INCLUDING advanced research-grade data: social equity metrics, resident sentiment analysis, bureaucratic friction indicators, and infrastructure categorization.

Your role is to provide **specific, data-driven insights** with exact numbers. You are speaking to municipal staff who need actionable intelligence.

## CURRENT SYSTEM DATA

### Overview
- **Total requests (all time): {total}**
- Open: {open_count} | In Progress: {in_progress_count} | Closed: {closed_count}
- Resolution rate: {(closed_count / total * 100) if total else 0:.1f}%
- Average resolution time: {avg_resolution:.1f} hours

### Priority Distribution
- High priority (8-10): {high_priority} ({(high_priority/total*100) if total else 0:.1f}%)
- Medium priority (5-7): {med_priority} ({(med_priority/total*100) if total else 0:.1f}%)
- Low priority (1-4): {low_priority} ({(low_priority/total*100) if total else 0:.1f}%)

### Requests by Category
{chr(10).join(f'- {cat}: {count}' for cat, count in sorted(categories.items(), key=lambda x: x[1], reverse=True))}

### Temporal Patterns
- Busiest hour: {busiest_hour}:00
- Busiest day: {busiest_day}
- Hourly distribution: {json.dumps(dict(sorted(hourly.items())))}
- Daily distribution: {json.dumps(daily)}
- Monthly trend: {json.dumps(dict(sorted(monthly.items())))}

### Top Problem Locations (by request count)
{chr(10).join(f'- {addr}: {count} requests' for addr, count in top_addresses)}

### Staff Performance
Top Resolvers:
{chr(10).join(f'- {staff}: {count} resolved' for staff, count in sorted(staff_resolutions.items(), key=lambda x: x[1], reverse=True)[:10]) if staff_resolutions else '- No resolution data yet'}

Current Workload:
{chr(10).join(f'- {staff}: {count} active' for staff, count in sorted(staff_workload.items(), key=lambda x: x[1], reverse=True)[:10]) if staff_workload else '- No active assignments'}

### Departments
{chr(10).join(f'- {d["name"]}: {d["description"]}' for d in dept_info) if dept_info else '- No departments configured'}

### AI Analysis Highlights
- Requests with AI analysis: {len(ai_summaries)}
- Flagged requests: {len(flagged_requests)}
{chr(10).join(f'- FLAGGED [{r["id"]}] at {r["address"]}: {r["reason"]}' for r in flagged_requests[:10]) if flagged_requests else ''}

### Infrastructure Categories
{infra_summary if infra_summary else 'No infrastructure category data available'}

### Social Equity Metrics
{equity_summary if equity_summary else 'Social equity data not available (Census API may be unavailable)'}

### Resident Sentiment & Trust
{sentiment_summary if sentiment_summary else 'Sentiment data not available'}

### Government Responsiveness (Bureaucratic Friction)
{friction_summary if friction_summary else 'Friction metrics not available'}

### Environmental Context
{weather_summary if weather_summary else 'Weather data not available'}
Season: {'Winter' if now.month in [12,1,2] else 'Spring' if now.month in [3,4,5] else 'Summer' if now.month in [6,7,8] else 'Fall'}

### Recent Request Details (sanitized, no personal info)
{json.dumps(request_details[:50], indent=None, default=str)}

## RESPONSE FORMAT RULES
The chat UI renders plain text with basic inline markdown only — it does NOT render markdown tables or headers, so those come out as raw pipes and hashes. Format accordingly:
- NEVER use markdown tables (| col | col |). To compare departments, categories, or time periods, use a bullet list with a bold label per item instead — e.g. "**Public Works** — 42 requests, 3.1 day avg".
- Do NOT use markdown headers (#, ##, ###). For a section title, put a short **bold line** on its own line instead.
- Use bullet points ("- ") for lists of 3+ items, and numbered lists ("1. ") for prioritized actions.
- **Bold** all key numbers, percentages, and metric values.
- Keep paragraphs short: 2-3 sentences maximum.
- End substantive responses with a bold **Key Takeaway** line followed by 1-2 sentences.

## IMPORTANT RULES
- NEVER share or reference resident names, emails, or phone numbers
- Always cite specific data points — never say "some" or "several" when you have exact numbers
- If asked about something not in the data, say so clearly
- When discussing equity metrics, explain what the numbers mean in plain language (e.g., "An SVI of 0.7 means this area is in the top 30% most vulnerable nationally")
- Provide actionable recommendations when relevant
- Cross-reference data across categories when it adds insight (e.g., connect sentiment to response time, or equity to priority patterns)
"""


    # ========== Build Conversation & Call Vertex AI ==========
    try:
        from app.services.secret_manager import get_secret as sm_get_secret
        
        project_id = await sm_get_secret("VERTEX_AI_PROJECT")
        if not project_id:
            # Try alternative key
            project_id = os.getenv("GOOGLE_VERTEX_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
        
        if not project_id:
            raise HTTPException(status_code=503, detail="Vertex AI not configured — VERTEX_AI_PROJECT not set")
        
        service_account_json = await sm_get_secret("VERTEX_AI_SERVICE_ACCOUNT_KEY")
        
        # Build the full conversation prompt
        conversation = system_prompt + "\n\n## CONVERSATION\n"
        for msg in body.history[-20:]:  # Last 20 messages for context
            role_label = "Staff" if msg.role == "user" else "AI Advisor"
            conversation += f"\n**{role_label}:** {msg.content}\n"
        conversation += f"\n**Staff:** {body.message}\n\n**AI Advisor:**"
        
        # Call Vertex AI — use lower temperature for factual responses
        import google.auth
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        import aiohttp
        
        if service_account_json:
            sa_info = json.loads(service_account_json)
            credentials = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
        else:
            credentials, _ = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
        
        credentials.refresh(Request())
        
        endpoint = f"https://aiplatform.googleapis.com/v1/projects/{project_id}/locations/global/publishers/google/models/gemini-3.1-flash-lite:generateContent"
        
        payload = {
            "contents": [{"role": "user", "parts": [{"text": conversation}]}],
            "generationConfig": {
                "temperature": 0.3,
                "topP": 0.8,
                "maxOutputTokens": 4096,
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json"
                },
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Vertex AI error: {error_text}")
                    raise HTTPException(status_code=502, detail=f"AI service error: {response.status}")
                
                result = await response.json()
        
        # Extract response text
        ai_response = ""
        if 'candidates' in result and result['candidates']:
            parts = result['candidates'][0].get('content', {}).get('parts', [])
            for part in parts:
                if 'text' in part:
                    ai_response += part['text']
        
        if not ai_response:
            ai_response = "I wasn't able to generate a response. Please try rephrasing your question."
        
        # Track API usage
        try:
            from app.services.api_usage import track_api_call
            await track_api_call(db, "vertex_ai", endpoint="analytics_chat", tokens_used=len(conversation) // 4 + len(ai_response) // 4)
        except Exception:
            pass  # API usage tracking is non-critical
        
        return AnalyticsChatResponse(
            response=ai_response.strip(),
            context_used=context_used
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analytics chat error: {e}")
        raise HTTPException(status_code=500, detail="AI analytics chat failed")



@router.get("/statistics/redirected")
async def get_redirected_statistics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """How many residents were redirected instead of filing, and to whom.

    These are not service requests -- nobody worked them and they appear in no
    queue, feed, export or map. But the count is the only way a town learns that
    one road is turning away twenty people a month, which is either evidence for
    a conversation with the county or a sign the routing config is wrong.

    Road-based redirects (this road belongs to someone else) and whole-category
    redirects (the whole service is handled elsewhere) are reported separately
    because they mean different things to a clerk.
    """
    # system.py imports datetime lazily per-function; do the same rather than
    # adding a module-level import that the rest of the file does not expect.
    from datetime import datetime, timedelta, timezone

    from app.models import BlockedRequestLog

    since = datetime.now(timezone.utc) - timedelta(days=days)

    async def grouped(column):
        rows = (
            await db.execute(
                select(column, func.count(BlockedRequestLog.id).label("count"))
                .where(BlockedRequestLog.created_at >= since)
                .group_by(column)
                .order_by(func.count(BlockedRequestLog.id).desc())
            )
        ).all()
        return [{"label": row[0] or "Unspecified", "count": row[1]} for row in rows]

    try:
        total = (
            await db.execute(
                select(func.count(BlockedRequestLog.id)).where(BlockedRequestLog.created_at >= since)
            )
        ).scalar() or 0

        by_type = {
            row["label"]: row["count"] for row in await grouped(BlockedRequestLog.block_type)
        }

        return {
            "days": days,
            "total": total,
            "road_based": by_type.get("road_based", 0),
            "category": by_type.get("category", 0),
            "by_jurisdiction": await grouped(BlockedRequestLog.jurisdiction_name),
            # road_name is null for whole-category redirects, which is why this
            # list will not sum to `total`.
            "by_road": [
                r for r in await grouped(BlockedRequestLog.road_name) if r["label"] != "Unspecified"
            ],
            "by_service": await grouped(BlockedRequestLog.service_name),
        }
    except Exception as e:
        # A town that has never redirected anyone has no table rows and possibly
        # no table yet; that is an empty report, not a failure.
        logger.info(f"Redirected statistics unavailable: {e}")
        return {
            "days": days, "total": 0, "road_based": 0, "category": 0,
            "by_jurisdiction": [], "by_road": [], "by_service": [],
        }
