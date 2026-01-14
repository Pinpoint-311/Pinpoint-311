"""
Translation service for multilingual notifications.
Uses Google Cloud Translation API to translate email and SMS content.
"""
import httpx
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


async def translate_text(text: str, target_lang: str, source_lang: str = "en") -> str:
    """
    Translate text to target language using Google Cloud Translation API.
    
    Args:
        text: Text to translate
        target_lang: Target language code (e.g., 'es', 'hi', 'zh')
        source_lang: Source language code (default: 'en')
    
    Returns:
        Translated text, or original text if translation fails
    """
    # If target is English, no translation needed
    if target_lang == "en" or not target_lang:
        return text
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "/api/system/translate/batch",
                json={
                    "texts": [text],
                    "target_lang": target_lang
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("translations") and len(data["translations"]) > 0:
                    return data["translations"][0]
        
        logger.warning(f"Translation failed for lang={target_lang}, using original text")
        return text
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text


async def translate_batch(texts: List[str], target_lang: str, source_lang: str = "en") -> List[str]:
    """
    Translate multiple texts in a single API call for efficiency.
    
    Args:
        texts: List of texts to translate
        target_lang: Target language code
        source_lang: Source language code (default: 'en')
    
    Returns:
        List of translated texts (same order as input)
    """
    # If target is English, no translation needed
    if target_lang == "en" or not target_lang:
        return texts
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "/api/system/translate/batch",
                json={
                    "texts": texts,
                    "target_lang": target_lang
                },
                timeout=15.0
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("translations"):
                    return data["translations"]
        
        logger.warning(f"Batch translation failed for lang={target_lang}, using original texts")
        return texts
    except Exception as e:
        logger.error(f"Batch translation error: {e}")
        return texts
