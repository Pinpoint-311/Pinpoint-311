"""
Translation service using Google Cloud Translation API with database caching.
Uses the GCP Service Account (server-side only) for authentication.
The Google Maps API key is public (sent to the browser) and should NOT be used here.

Flow:
1. Check database first for cached translation
2. If not found, call Google Translate API via service account auth
3. Store result in database for future use (persistent cache)
"""
from typing import Optional, Dict, List, Tuple
import logging
import json
from sqlalchemy import select, and_

logger = logging.getLogger(__name__)

GOOGLE_TRANSLATE_API_URL = "https://translation.googleapis.com/language/translate/v2"


async def _get_auth_headers() -> Optional[Dict[str, str]]:
    """
    Get OAuth2 authorization headers from GCP Service Account.
    Uses the server-side service account JSON (never exposed to frontend).
    """
    try:
        from app.services.secret_manager import get_secret

        sa_json = await get_secret("GCP_SERVICE_ACCOUNT_JSON")
        if not sa_json:
            logger.warning("GCP_SERVICE_ACCOUNT_JSON not configured, translation unavailable")
            return None

        # Use google-auth to generate an access token from the service account
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request

        sa_info = json.loads(sa_json) if isinstance(sa_json, str) else sa_json
        credentials = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/cloud-translation"]
        )
        credentials.refresh(Request())
        return {"Authorization": f"Bearer {credentials.token}"}
    except ImportError:
        logger.warning("google-auth not installed, falling back to API key auth")
        # Fallback: try the Maps API key (less secure, but works)
        return await _get_api_key_fallback()
    except Exception as e:
        logger.error(f"Failed to get GCP auth for translation: {e}")
        return None


async def _get_api_key_fallback() -> Optional[Dict[str, str]]:
    """Fallback: use API key if google-auth is not available."""
    try:
        from app.services.secret_manager import get_secret
        api_key = await get_secret("GOOGLE_MAPS_API_KEY")
        if api_key:
            # Return as a special marker so callers know to use ?key= param
            return {"_api_key": api_key}
        return None
    except Exception as e:
        logger.error(f"Fallback API key retrieval failed: {e}")
        return None


async def get_api_key() -> Optional[str]:
    """Check if translation is available (service account or API key)."""
    auth = await _get_auth_headers()
    if auth:
        return "configured"  # Just indicates availability
    return None



async def get_cached_translation(text: str, target_lang: str) -> Optional[str]:
    """Check database for cached translation."""
    try:
        from app.db.session import SessionLocal
        from app.models import Translation
        
        async with SessionLocal() as db:
            result = await db.execute(
                select(Translation).where(
                    and_(
                        Translation.source_text == text,
                        Translation.target_lang == target_lang
                    )
                ).order_by(Translation.id).limit(1)
            )
            # first(), not scalar_one_or_none(): the table has no unique key, so
            # two concurrent batches can both cache the same string, and from
            # then on every lookup raised "Multiple rows were found", was read
            # as a miss, and paid the translation API again.
            cached = result.scalars().first()
            
            if cached:
                from app.core.sanitize import sanitize_for_log
                logger.debug(f"DB cache hit: '{text[:30]}...' -> '{sanitize_for_log(target_lang)}'")
                return cached.translated_text
            return None
    except Exception as e:
        logger.error(f"Failed to check translation cache: {e}")
        return None


async def save_translation_to_cache(text: str, target_lang: str, translated: str) -> None:
    """Save translation to database cache."""
    try:
        from app.db.session import SessionLocal
        from app.models import Translation
        
        async with SessionLocal() as db:
            # Check if already exists (race condition protection)
            result = await db.execute(
                select(Translation).where(
                    and_(
                        Translation.source_text == text,
                        Translation.target_lang == target_lang
                    )
                ).order_by(Translation.id).limit(1)
            )
            existing = result.scalars().first()
            
            if not existing:
                translation = Translation(
                    source_text=text,
                    source_lang="en",
                    target_lang=target_lang,
                    translated_text=translated
                )
                db.add(translation)
                await db.commit()
                from app.core.sanitize import sanitize_for_log
                logger.info(f"Cached translation: '{text[:30]}...' -> '{translated[:30]}...' ({sanitize_for_log(target_lang)})")
    except Exception as e:
        logger.error(f"Failed to save translation to cache: {e}")


async def _resolve_target(provider, target_lang: str) -> Optional[str]:
    """The provider's spelling of `target_lang`, or None if it cannot do it.

    Checked here as well as at the API, because not every caller is the API:
    the service catalog takes the language from a browser's Accept-Language
    header, and the notification path from a stored preference. A code the
    provider does not support is not sent -- it would be billed and answered
    with an error, or with the source echoed back as if translated.
    """
    from app.services.translation_providers import (
        canonical_language, provider_language_code, supported_languages,
    )
    name = getattr(provider, "provider", None)
    canonical = canonical_language(target_lang)
    if canonical is None or canonical not in supported_languages(name):
        from app.core.sanitize import sanitize_for_log
        logger.info("Translation skipped: %s does not support %s",
                    sanitize_for_log(str(name)), sanitize_for_log(str(target_lang)))
        return None
    return provider_language_code(name, canonical)


async def translate_text_detailed(
    text: str,
    source_lang: str = "en",
    target_lang: str = "es",
) -> Tuple[Optional[str], bool]:
    """`translate_text`, plus whether the spend budget is what stopped it.

    Returns (translated or None, budget_exhausted).
    """
    if not text or not text.strip():
        return text, False

    if source_lang == target_lang:
        return text, False

    # 1. Check database cache first -- free, so never counted against the budget
    cached = await get_cached_translation(text, target_lang)
    if cached:
        return cached, False

    # 2. Call the configured translation provider (Google default, or Azure)
    from app.services.translation_providers import get_translation_provider, provider_language_code
    provider = await get_translation_provider()
    if not provider:
        logger.warning("Translation not configured (no provider credentials)")
        return None, False

    target_code = await _resolve_target(provider, target_lang)
    if target_code is None:
        return None, False

    # 3. Reserve the characters before they are sent; refuse past the budget.
    from app.services import translation_budget
    reservation = await translation_budget.reserve(len(text))
    if reservation is None:
        return None, True

    try:
        out = await provider.translate(
            [text], provider_language_code(provider.provider, source_lang), target_code)
        if not out:
            # Not configured after all (no auth): nothing was billed.
            await translation_budget.refund(reservation)
            return None, False
        translated = out[0]

        # Track API usage for cost estimation
        try:
            from app.db.session import SessionLocal
            from app.services.api_usage import track_api_usage
            async with SessionLocal() as db:
                await track_api_usage(
                    db=db,
                    service_name="translation",
                    operation="translate_text",
                    characters=len(text)
                )
        except Exception as e:
            logger.warning(f"Failed to track translation usage: {e}")

        # 4. Save to database cache
        await save_translation_to_cache(text, target_lang, translated)

        return translated, False
    except Exception as e:
        await translation_budget.refund(reservation)
        from app.core.sanitize import sanitize_for_log
        logger.error(f"Translation failed ({sanitize_for_log(source_lang)} -> {sanitize_for_log(target_lang)}): {e}")
        # Returning None already keeps the caller (and the resident) whole;
        # a quota failure additionally belongs on the admin's health card, or
        # a town at its hard limit serves English silently for a month.
        from app.services import connector_health
        await connector_health.note_quota_failure(
            "translation", e, provider=getattr(provider, "provider", None))
        return None, False


async def translate_text(
    text: str,
    source_lang: str = "en",
    target_lang: str = "es"
) -> Optional[str]:
    """
    Translate text using the configured provider with database caching.
    1. Check database cache first
    2. If miss, reserve the characters against the spend budget
    3. Call the provider, store the result in the database

    None when translation is unavailable, unsupported for this language, or
    over budget -- every caller already falls back to the source text.
    """
    translated, _exhausted = await translate_text_detailed(text, source_lang, target_lang)
    return translated


async def translate_batch_detailed(
    texts: List[str],
    source_lang: str = "en",
    target_lang: str = "es",
) -> Tuple[Dict[str, str], bool]:
    """`translate_batch`, plus whether the spend budget stopped any of it.

    Returns ({original: translated}, budget_exhausted). Strings the budget
    refused come back as their originals; cached strings are still served
    translated, because a cache hit costs nothing.
    """
    if not texts:
        return {}, False

    if source_lang == target_lang:
        return {t: t for t in texts}, False

    results = {}
    uncached = []

    # 1. Check database cache for each text
    for text in texts:
        if not text or not text.strip():
            results[text] = text
            continue

        cached = await get_cached_translation(text, target_lang)
        if cached:
            results[text] = cached
        elif text not in uncached:
            uncached.append(text)

    if not uncached:
        return results, False

    # 2. Call the configured translation provider (Google default, or Azure)
    from app.services.translation_providers import get_translation_provider, provider_language_code
    provider = await get_translation_provider()
    if not provider:
        logger.warning("Translation not configured (no provider credentials)")
        for t in uncached:
            results[t] = t
        return results, False

    target_code = await _resolve_target(provider, target_lang)
    if target_code is None:
        for t in uncached:
            results[t] = t
        return results, False

    # 3. Reserve what is about to be sent. All or nothing: a batch is one
    # provider call, and a page half in one language is worse than one in
    # English with a notice.
    from app.services import translation_budget
    chars = sum(len(t) for t in uncached)
    reservation = await translation_budget.reserve(chars)
    if reservation is None:
        for t in uncached:
            results[t] = t
        return results, True

    try:
        out = await provider.translate(
            uncached, provider_language_code(provider.provider, source_lang), target_code)
        if out is None:
            # The provider was not configured after all; nothing was billed.
            await translation_budget.refund(reservation)
            for t in uncached:
                results[t] = t
            return results, False
        # Recorded here as well as in translate_text, because this path bills
        # too and did not say so. Everything the admin's usage page knew came
        # from the single-string path, so the resident-facing catalog
        # translation -- the one an unauthenticated request can trigger -- was
        # invisible: 6,569 characters reported against 846,782 actually
        # translated. A spend nobody can see is a spend nobody can cap.
        try:
            from app.db.session import SessionLocal
            from app.services.api_usage import track_api_usage
            async with SessionLocal() as db:
                await track_api_usage(
                    db=db,
                    service_name="translation",
                    operation="translate_batch",
                    characters=chars,
                )
        except Exception:  # noqa: BLE001 -- accounting must not fail a request
            logger.warning("could not record batch translation usage", exc_info=True)
        for i, text in enumerate(uncached):
            translated = out[i] if i < len(out) else text
            results[text] = translated
            if translated != text:
                # 4. Save each to database
                await save_translation_to_cache(text, target_lang, translated)
        return results, False
    except Exception as e:
        await translation_budget.refund(reservation)
        logger.error(f"Batch translation failed: {e}")
        # Originals below keep /translate/batch a 200 whatever the provider
        # said; the health note is the only place a rate-limit surfaces.
        from app.services import connector_health
        await connector_health.note_quota_failure(
            "translation", e, provider=getattr(provider, "provider", None))
        for t in uncached:
            results[t] = t
        return results, False


async def translate_batch(
    texts: List[str],
    source_lang: str = "en",
    target_lang: str = "es"
) -> Dict[str, str]:
    """
    Translate multiple texts with database caching.
    Returns dict of {original_text: translated_text}.
    """
    results, _exhausted = await translate_batch_detailed(texts, source_lang, target_lang)
    return results


async def translate_service_response(service_dict: dict, target_lang: str) -> dict:
    """
    Translate service response dict without modifying database.
    Returns a new dict with translated fields.
    """
    if target_lang == 'en':
        return service_dict
    
    result = dict(service_dict)
    
    # Translate service name
    if result.get('service_name'):
        translated = await translate_text(result['service_name'], 'en', target_lang)
        if translated:
            result['service_name'] = translated
    
    # Translate description
    if result.get('description'):
        translated = await translate_text(result['description'], 'en', target_lang)
        if translated:
            result['description'] = translated
    
    return result


# Supported languages: see translation_providers.SUPPORTED_LANGUAGES -- the
# one list, per provider. (A six-entry dict here used to answer
# /translate/languages while the picker offered over a hundred.)


async def check_translation_service() -> bool:
    """Check if Google Translate API key is configured."""
    api_key = await get_api_key()
    return api_key is not None


async def get_translation_cache_stats() -> Dict:
    """Get statistics about the translation cache."""
    try:
        from app.db.session import SessionLocal
        from app.models import Translation
        from sqlalchemy import func
        
        async with SessionLocal() as db:
            # Count total translations
            total = await db.execute(select(func.count(Translation.id)))
            total_count = total.scalar()
            
            # Count by language
            by_lang = await db.execute(
                select(
                    Translation.target_lang,
                    func.count(Translation.id)
                ).group_by(Translation.target_lang)
            )
            lang_counts = {row[0]: row[1] for row in by_lang.fetchall()}
            
            return {
                "total_cached": total_count,
                "by_language": lang_counts
            }
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return {"total_cached": 0, "by_language": {}}
