"""Live AI model discovery.

Each provider can list the models it currently offers, so the admin UI doesn't
have to trust a hardcoded catalog that silently goes stale (e.g. a Gemini
preview id being retired). This module fetches that live list per provider,
merges it with the curated catalog (which supplies friendly labels and the
recommended default), and flags when a currently-configured model is no longer
offered.

Design:
  * discover_models(provider, creds) does the live call. It is defensive: any
    error, missing credential, or unexpected response shape returns None, and
    the caller falls back to the curated list. It never raises.
  * merge_models() unions curated + live, preferring curated labels for known
    ids and appending newly-discovered ids with a plain label.
  * A short in-process TTL cache avoids hammering the provider on every admin
    page load; the daily Celery task refreshes the shared DB cache.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.services.ai.registry import AI_CATALOG

logger = logging.getLogger(__name__)

# In-process cache: provider -> (fetched_monotonic, list[{id,label}] | None)
# Bounded to one small entry per provider (~3-4 keys), each a short list — the
# daily refresh replaces entries in place, so it never grows.
_CACHE: Dict[str, tuple] = {}
_TTL_SECONDS = 60 * 60 * 12  # 12h; the daily beat task refreshes the DB copy
# Hard cap on how many models we keep per provider, so a pathological provider
# response can't bloat memory or the persisted cache. Chat/gen model lists are
# tens of entries at most; anything beyond this is noise.
_MAX_MODELS = 60


def _curated(provider: str) -> List[Dict[str, str]]:
    return list(AI_CATALOG.get(provider, {}).get("models", []) or [])


def merge_models(provider: str, live: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """Union curated + live. Curated order/labels win for known ids (they carry
    the human guidance and recommended-for-triage notes); newly-discovered ids
    are appended with a plain label so nothing the provider offers is hidden."""
    curated = _curated(provider)
    if not live:
        return curated
    by_id = {m["id"]: dict(m) for m in curated}
    ordered = [m["id"] for m in curated]
    for m in live:
        mid = m.get("id")
        if not mid:
            continue
        if mid not in by_id:
            by_id[mid] = {"id": mid, "label": m.get("label") or mid, "discovered": True}
            ordered.append(mid)
    return [by_id[i] for i in ordered]


def model_is_available(models: List[Dict[str, str]], model_id: Optional[str]) -> bool:
    """True if model_id is offered (or nothing is pinned). Used to warn the admin
    that a configured model was retired."""
    if not model_id:
        return True
    return any(m.get("id") == model_id for m in models)


# --------------------------- per-provider discovery --------------------------

async def _discover_vertex(creds: Dict[str, str]) -> Optional[List[Dict[str, str]]]:
    project = creds.get("VERTEX_AI_PROJECT")
    if not project:
        return None
    location = creds.get("VERTEX_AI_LOCATION") or "global"
    sa_json = creds.get("VERTEX_AI_SERVICE_ACCOUNT_KEY")

    def _sync() -> Optional[List[Dict[str, str]]]:
        import json
        import google.auth
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        import httpx

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        if sa_json:
            info = json.loads(sa_json)
            credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        else:
            credentials, _ = google.auth.default(scopes=scopes)
        credentials.refresh(Request())

        host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
        url = f"https://{host}/v1/publishers/google/models"
        out: List[Dict[str, str]] = []
        page_token = None
        for _ in range(5):  # bound pagination
            params = {"pageSize": 200}
            if page_token:
                params["pageToken"] = page_token
            resp = httpx.get(url, params=params,
                             headers={"Authorization": f"Bearer {credentials.token}"}, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("publisherModels", []) or data.get("models", []):
                name = m.get("name", "")
                mid = name.split("/")[-1] if name else m.get("modelId", "")
                # Gemini text-generation models only; drop embeddings/vision-only variants.
                if not mid or "gemini" not in mid.lower():
                    continue
                if any(x in mid.lower() for x in ("embedding", "vision", "aqa")):
                    continue
                out.append({"id": mid, "label": mid})
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        # de-dupe, stable
        seen, uniq = set(), []
        for m in out:
            if m["id"] not in seen:
                seen.add(m["id"])
                uniq.append(m)
        return uniq or None

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


async def _discover_azure(creds: Dict[str, str]) -> Optional[List[Dict[str, str]]]:
    endpoint = (creds.get("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    api_key = creds.get("AZURE_OPENAI_API_KEY")
    if not endpoint or not api_key:
        return None
    version = creds.get("AZURE_OPENAI_API_VERSION") or "2023-05-15"
    import httpx
    url = f"{endpoint}/openai/deployments?api-version={version}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
        resp = await client.get(url, headers={"api-key": api_key})
        resp.raise_for_status()
        data = resp.json()
    out: List[Dict[str, str]] = []
    for d in data.get("data", []):
        # Azure addresses models by *deployment* id; label with the underlying model.
        dep_id = d.get("id")
        model = d.get("model")
        if not dep_id:
            continue
        label = f"{dep_id} ({model})" if model and model != dep_id else dep_id
        out.append({"id": dep_id, "label": label})
    return out or None


async def _discover_bedrock(creds: Dict[str, str]) -> Optional[List[Dict[str, str]]]:
    region = creds.get("AWS_REGION")
    if not region:
        return None

    def _sync() -> Optional[List[Dict[str, str]]]:
        import boto3
        kwargs = {"region_name": region}
        if creds.get("AWS_ACCESS_KEY_ID") and creds.get("AWS_SECRET_ACCESS_KEY"):
            kwargs["aws_access_key_id"] = creds["AWS_ACCESS_KEY_ID"]
            kwargs["aws_secret_access_key"] = creds["AWS_SECRET_ACCESS_KEY"]
            if creds.get("AWS_SESSION_TOKEN"):
                kwargs["aws_session_token"] = creds["AWS_SESSION_TOKEN"]
        client = boto3.client("bedrock", **kwargs)
        resp = client.list_foundation_models(byOutputModality="TEXT", byInferenceType="ON_DEMAND")
        out: List[Dict[str, str]] = []
        for m in resp.get("modelSummaries", []):
            mid = m.get("modelId")
            if not mid:
                continue
            if m.get("modelLifecycle", {}).get("status") not in (None, "ACTIVE"):
                continue
            name = m.get("modelName") or mid
            prov = m.get("providerName") or ""
            label = f"{prov} {name}".strip() or mid
            out.append({"id": mid, "label": label})
        return out or None

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


_DISCOVERERS = {
    "vertex": _discover_vertex,
    "azure": _discover_azure,
    "bedrock": _discover_bedrock,
}


async def discover_models(provider: str, creds: Dict[str, str]) -> Optional[List[Dict[str, str]]]:
    """Live-list a provider's models, or None on any failure (caller falls back
    to the curated catalog). Never raises."""
    fn = _DISCOVERERS.get(provider)
    if not fn:
        return None
    try:
        result = await fn(creds or {})
    except Exception as e:
        from app.core.sanitize import sanitize_for_log
        logger.info("[AI models] live discovery for %s unavailable: %s",
                    provider, sanitize_for_log(str(e)))
        return None
    # Bound the list so neither memory nor the persisted cache can balloon.
    return result[:_MAX_MODELS] if result else result


async def provider_creds(provider: str) -> Dict[str, str]:
    """Resolve the stored credential values a provider needs to list its models."""
    from app.services.secret_manager import get_secret
    meta = AI_CATALOG.get(provider, {})
    creds: Dict[str, str] = {}
    for f in meta.get("credential_fields", []):
        val = await get_secret(f["key"])
        if val:
            creds[f["key"]] = val
    # Vertex/Bedrock share region/location keys not always in credential_fields.
    for extra in ("VERTEX_AI_LOCATION", "AWS_SESSION_TOKEN"):
        val = await get_secret(extra)
        if val:
            creds[extra] = val
    return creds


async def load_db_cache(db) -> Dict[str, Any]:
    """Read the shared (fleet-wide) model cache off SystemSettings."""
    from sqlalchemy import select as _select
    from app.models import SystemSettings
    row = (await db.execute(_select(SystemSettings).limit(1))).scalar_one_or_none()
    return dict((row.ai_models_cache or {})) if row else {}


async def save_db_cache(db, provider: str, entry: Dict[str, Any]) -> None:
    """Persist one provider's discovered list into the shared cache."""
    from sqlalchemy import select as _select
    from sqlalchemy.orm.attributes import flag_modified
    from app.models import SystemSettings
    row = (await db.execute(_select(SystemSettings).limit(1))).scalar_one_or_none()
    if not row:
        row = SystemSettings()
        db.add(row)
    cache = dict(row.ai_models_cache or {})
    cache[provider] = entry
    row.ai_models_cache = cache
    flag_modified(row, "ai_models_cache")
    await db.commit()


async def refresh_provider(db, provider: str) -> Dict[str, Any]:
    """Live-discover one provider, persist to the shared cache, and return the
    merged result with staleness against the currently-configured model."""
    from app.services.secret_manager import get_secret
    from app.services.ai.registry import AI_MODEL_KEY
    creds = await provider_creds(provider)
    live = await discover_models(provider, creds)
    epoch = time.time()
    _CACHE[provider] = (time.monotonic(), live, epoch)
    models = merge_models(provider, live)
    entry = {"models": models, "source": "live" if live else "curated",
             "fetched_at": epoch if live else None}
    if live:  # only persist a real live list; never overwrite with a curated fallback
        await save_db_cache(db, provider, entry)
    current_model = await get_secret(AI_MODEL_KEY)
    entry["current_model"] = current_model
    entry["current_model_available"] = model_is_available(models, current_model)
    return entry


async def get_models(provider: str, creds: Dict[str, str], *, force: bool = False) -> Dict[str, Any]:
    """Return merged models for a provider with cache + source metadata:
    {models, source: 'live'|'curated', fetched_at: epoch|None}."""
    now = time.monotonic()
    if not force:
        cached = _CACHE.get(provider)
        if cached and (now - cached[0]) < _TTL_SECONDS:
            live = cached[1]
            return {"models": merge_models(provider, live),
                    "source": "live" if live else "curated",
                    "fetched_at": cached[2] if len(cached) > 2 else None}
    live = await discover_models(provider, creds)
    epoch = time.time()
    _CACHE[provider] = (now, live, epoch)
    return {"models": merge_models(provider, live),
            "source": "live" if live else "curated",
            "fetched_at": epoch if live else None}
