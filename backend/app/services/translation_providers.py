"""Pluggable translation providers (Google Cloud Translation / Azure Translator).

The public translation API (translation.py: translate_text / translate_batch)
keeps its DB caching and usage tracking; only the raw provider call is
abstracted here so a jurisdiction can run translation on Google or Azure by
config. Default is google — existing deployments are unchanged.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

TRANSLATION_PROVIDER_KEY = "TRANSLATION_PROVIDER"

GOOGLE_TRANSLATE_API_URL = "https://translation.googleapis.com/language/translate/v2"
# Azure Translator: global host by default; Gov cloud uses ...microsofttranslator.us
DEFAULT_AZURE_TRANSLATOR_ENDPOINT = "https://api.cognitive.microsofttranslator.com"


class TranslationProvider:
    provider = "base"

    async def translate(self, texts: List[str], source_lang: str, target_lang: str) -> Optional[List[str]]:
        """Translate texts (aligned to input order). Return None if the provider
        is not configured; raise only on unexpected errors (callers handle)."""
        raise NotImplementedError


class GoogleTranslationProvider(TranslationProvider):
    provider = "google"

    async def translate(self, texts, source_lang, target_lang):
        # Reuse the existing Google auth resolution (service account or API key)
        from app.services.translation import _get_auth_headers
        auth = await _get_auth_headers()
        if not auth:
            return None
        headers, params = {}, {}
        if "_api_key" in auth:
            params["key"] = auth["_api_key"]
        else:
            headers = auth
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GOOGLE_TRANSLATE_API_URL, params=params, headers=headers,
                json={"q": texts, "source": source_lang, "target": target_lang, "format": "text"},
            )
            resp.raise_for_status()
            data = resp.json()
        translations = data.get("data", {}).get("translations", [])
        out = []
        for i, t in enumerate(texts):
            out.append(translations[i].get("translatedText", t) if i < len(translations) else t)
        return out


class AzureTranslationProvider(TranslationProvider):
    provider = "azure"

    def __init__(self, api_key: str, region: str, endpoint: Optional[str] = None):
        self.api_key = api_key
        self.region = region
        self.endpoint = (endpoint or DEFAULT_AZURE_TRANSLATOR_ENDPOINT).rstrip("/")

    async def translate(self, texts, source_lang, target_lang):
        if not self.api_key:
            return None
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/json",
        }
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region
        params = {"api-version": "3.0", "from": source_lang, "to": target_lang}
        body = [{"Text": t} for t in texts]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.endpoint}/translate", params=params, headers=headers, json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        out = []
        for i, t in enumerate(texts):
            try:
                out.append(data[i]["translations"][0]["text"])
            except (IndexError, KeyError, TypeError):
                out.append(t)
        return out


TRANSLATION_CATALOG: Dict[str, Dict[str, Any]] = {
    "google": {
        "name": "Google Cloud Translation",
        "description": "Google Translate — the default; ~100+ languages.",
        "credential_fields": [
            {"key": "GOOGLE_CLOUD_PROJECT", "label": "GCP Project (uses the same GCP creds)", "secret": False},
        ],
        "field_help": {"GOOGLE_CLOUD_PROJECT": "Uses your existing Google Cloud credentials; no extra key needed if GCP is already set up."},
    },
    "azure": {
        "name": "Azure AI Translator",
        "description": "Azure Cognitive Services Translator — for Microsoft/Azure-Government stacks.",
        "credential_fields": [
            {"key": "AZURE_TRANSLATOR_KEY", "label": "Translator Key", "secret": True},
            {"key": "AZURE_TRANSLATOR_REGION", "label": "Region", "secret": False},
            {"key": "AZURE_TRANSLATOR_ENDPOINT", "label": "Endpoint (optional; .us for Gov)", "secret": False},
        ],
        "field_help": {
            "AZURE_TRANSLATOR_KEY": "Key from your Azure Translator resource.",
            "AZURE_TRANSLATOR_REGION": "e.g. usgovvirginia or eastus.",
            "AZURE_TRANSLATOR_ENDPOINT": "Leave blank for global; use https://api.cognitive.microsofttranslator.us for Azure Government.",
        },
    },
}


def catalog_for_api() -> List[Dict[str, Any]]:
    return [{"provider": k, **v} for k, v in TRANSLATION_CATALOG.items()]


async def get_translation_provider() -> Optional[TranslationProvider]:
    """Return the configured translation provider (default google), or None if
    the selected provider isn't configured."""
    from app.services.secret_manager import get_secret

    provider = (await get_secret(TRANSLATION_PROVIDER_KEY)) or "google"
    provider = provider.strip().lower()
    if provider == "azure":
        key = await get_secret("AZURE_TRANSLATOR_KEY")
        if not key:
            return None
        return AzureTranslationProvider(
            api_key=key,
            region=await get_secret("AZURE_TRANSLATOR_REGION") or "",
            endpoint=await get_secret("AZURE_TRANSLATOR_ENDPOINT"),
        )
    # Google is validated by _get_auth_headers at call time
    return GoogleTranslationProvider()
