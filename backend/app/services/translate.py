"""
Translation for multilingual notifications (email and SMS).

A thin wrapper over app.services.translation, which uses the town's configured
provider, the database cache and the translation spend budget. This module used
to POST to "/api/system/translate/batch" -- a relative URL, which httpx cannot
send -- so every notification went out untranslated and the failure was only a
warning in the worker log.

Both functions keep their old signatures (target before source) because the
notification tasks call them that way, and both always return text: the
original when translation is off, unsupported for the language, or over budget.
"""
import logging
from typing import List

logger = logging.getLogger(__name__)


async def translate_text(text: str, target_lang: str, source_lang: str = "en") -> str:
    """Translate one string; the original text if translation is unavailable."""
    if not text or not target_lang or target_lang == source_lang:
        return text
    try:
        from app.services.translation import translate_text as service_translate
        translated = await service_translate(text, source_lang, target_lang)
        return translated or text
    except Exception as e:  # noqa: BLE001 -- a notification must still go out
        logger.warning("Notification translation failed (lang=%s): %s", target_lang, e)
        return text


async def translate_batch(texts: List[str], target_lang: str, source_lang: str = "en") -> List[str]:
    """Translate several strings, same order as input; originals where unavailable."""
    if not texts or not target_lang or target_lang == source_lang:
        return texts
    try:
        from app.services.translation import translate_batch as service_batch
        results = await service_batch(texts, source_lang, target_lang)
        return [results.get(t) or t for t in texts]
    except Exception as e:  # noqa: BLE001
        logger.warning("Notification translation failed (lang=%s): %s", target_lang, e)
        return texts
