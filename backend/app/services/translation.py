"""
Translation service using Google Cloud Translation API with database caching.
Flow:
1. Check database first for cached translation
2. If not found, call Google Translate API
3. Store result in database for future use (persistent cache)
"""
from typing import Optional, Dict, List
import logging
import httpx
from sqlalchemy import select, and_

logger = logging.getLogger(__name__)

GOOGLE_TRANSLATE_API_URL = "https://translation.googleapis.com/language/translate/v2"


async def get_api_key() -> Optional[str]:
    """Get Google Maps API key (also used for Translation API)"""
    try:
        from app.db.session import SessionLocal
        from app.models import SystemSecret
        from app.core.encryption import decrypt_safe
        
        async with SessionLocal() as db:
            result = await db.execute(
                select(SystemSecret).where(SystemSecret.key_name == "GOOGLE_MAPS_API_KEY")
            )
            secret = result.scalar_one_or_none()
            
            if secret and secret.key_value:
                decrypted = decrypt_safe(secret.key_value)
                return decrypted if decrypted else None
            return None
    except Exception as e:
        logger.error(f"Failed to get Google API key: {e}")
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
                )
            )
            cached = result.scalar_one_or_none()
            
            if cached:
                logger.debug(f"DB cache hit: '{text[:30]}...' -> '{target_lang}'")
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
                )
            )
            existing = result.scalar_one_or_none()
            
            if not existing:
                translation = Translation(
                    source_text=text,
                    source_lang="en",
                    target_lang=target_lang,
                    translated_text=translated
                )
                db.add(translation)
                await db.commit()
                logger.info(f"Cached translation: '{text[:30]}...' -> '{translated[:30]}...' ({target_lang})")
    except Exception as e:
        logger.error(f"Failed to save translation to cache: {e}")


async def translate_text(
    text: str,
    source_lang: str = "en",
    target_lang: str = "es"
) -> Optional[str]:
    """
    Translate text using Google Cloud Translation API with database caching.
    1. Check database cache first
    2. If miss, call Google Translate API
    3. Store result in database
    """
    if not text or not text.strip():
        return text
        
    if source_lang == target_lang:
        return text
    
    # 1. Check database cache first
    cached = await get_cached_translation(text, target_lang)
    if cached:
        return cached
    
    # 2. Call Google Translate API
    api_key = await get_api_key()
    if not api_key:
        logger.warning("Google Translate API key not configured")
        return None
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                GOOGLE_TRANSLATE_API_URL,
                params={"key": api_key},
                json={
                    "q": text,
                    "source": source_lang,
                    "target": target_lang,
                    "format": "text"
                }
            )
            response.raise_for_status()
            result = response.json()
            
            if "data" in result and "translations" in result["data"]:
                translated = result["data"]["translations"][0]["translatedText"]
                
                # 3. Save to database cache
                await save_translation_to_cache(text, target_lang, translated)
                
                return translated
            return None
    except Exception as e:
        logger.error(f"Translation failed ({source_lang} -> {target_lang}): {e}")
        return None


async def translate_batch(
    texts: List[str],
    source_lang: str = "en",
    target_lang: str = "es"
) -> Dict[str, str]:
    """
    Translate multiple texts with database caching.
    Returns dict of {original_text: translated_text}.
    """
    if not texts:
        return {}
        
    if source_lang == target_lang:
        return {t: t for t in texts}
    
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
        else:
            uncached.append(text)
    
    if not uncached:
        return results
    
    # 2. Call Google Translate API for uncached texts
    api_key = await get_api_key()
    if not api_key:
        logger.warning("Google Translate API key not configured")
        for t in uncached:
            results[t] = t
        return results
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GOOGLE_TRANSLATE_API_URL,
                params={"key": api_key},
                json={
                    "q": uncached,
                    "source": source_lang,
                    "target": target_lang,
                    "format": "text"
                }
            )
            response.raise_for_status()
            result = response.json()
            
            translations = result.get("data", {}).get("translations", [])
            for i, text in enumerate(uncached):
                if i < len(translations):
                    translated = translations[i].get("translatedText", text)
                    results[text] = translated
                    # 3. Save each to database
                    await save_translation_to_cache(text, target_lang, translated)
                else:
                    results[text] = text
                    
            return results
    except Exception as e:
        logger.error(f"Batch translation failed: {e}")
        for t in uncached:
            results[t] = t
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


def get_supported_languages() -> Dict[str, str]:
    """Get list of supported language codes and names."""
    return {
        "en": "English",
        "es": "Español", 
        "zh": "中文",
        "fr": "Français",
        "hi": "हिन्दी",
        "ar": "العربية"
    }


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
