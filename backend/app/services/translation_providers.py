"""Pluggable translation providers (Google Cloud Translation / Azure Translator).

The public translation API (translation.py: translate_text / translate_batch)
keeps its DB caching and usage tracking; only the raw provider call is
abstracted here so a jurisdiction can run translation on Google or Azure by
config. Default is google — existing deployments are unchanged.
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)

TRANSLATION_PROVIDER_KEY = "TRANSLATION_PROVIDER"

GOOGLE_TRANSLATE_API_URL = "https://translation.googleapis.com/language/translate/v2"
# Azure Translator: global host by default; Gov cloud uses ...microsofttranslator.us
DEFAULT_AZURE_TRANSLATOR_ENDPOINT = "https://api.cognitive.microsofttranslator.com"
# Where Translator lives on a resource's own subdomain.
AZURE_CUSTOM_DOMAIN_TRANSLATOR_PATH = "/translator/text/v3.0"


def normalise_azure_translator_endpoint(endpoint: Optional[str]) -> str:
    """Return the base URL that `/translate` is appended to.

    The global and Gov hosts serve Translator at the root. A resource's own
    subdomain (`NAME.cognitiveservices.azure.com`, which is what the Azure
    portal shows as "Endpoint" for an AI Services / Foundry resource) serves it
    under /translator/text/v3.0 and answers a bare /translate with a 404 --
    which is what a town saw live, with nothing in the error to say the path
    was the problem. Any path pasted along with such a host (the portal's
    sample request, or the right prefix already) is replaced by the one
    Translator actually uses.
    """
    raw = (endpoint or "").strip() or DEFAULT_AZURE_TRANSLATOR_ENDPOINT
    parts = urlsplit(raw)
    if parts.scheme and ".cognitiveservices.azure." in parts.netloc.lower():
        return urlunsplit((parts.scheme, parts.netloc, AZURE_CUSTOM_DOMAIN_TRANSLATOR_PATH, "", ""))
    return raw.rstrip("/")


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
        self.endpoint = normalise_azure_translator_endpoint(endpoint)

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


class AWSTranslateProvider(TranslationProvider):
    """Amazon Translate via boto3. boto3 is synchronous, so calls run in a
    thread executor. For AWS GovCloud stacks (us-gov-*)."""
    provider = "aws"

    def __init__(self, region: str, access_key: Optional[str] = None,
                 secret_key: Optional[str] = None, session_token: Optional[str] = None):
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self.session_token = session_token

    def _client(self):
        import boto3
        kwargs = {"region_name": self.region}
        if self.access_key and self.secret_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
            if self.session_token:
                kwargs["aws_session_token"] = self.session_token
        return boto3.client("translate", **kwargs)

    async def translate(self, texts, source_lang, target_lang):
        if not self.region:
            return None
        import asyncio

        def _run():
            client = self._client()
            out = []
            # Kept alongside the originals rather than raised: one bad string
            # must not cost the rest of the batch, but swallowing the error
            # entirely is how a ThrottlingException storm stays invisible --
            # the caller substitutes originals and nobody upstream ever sees
            # AWS said "Rate exceeded". The first error is enough evidence.
            errors = []
            # Amazon Translate is one string per call; batch sequentially.
            for t in texts:
                try:
                    resp = client.translate_text(
                        Text=t, SourceLanguageCode=source_lang, TargetLanguageCode=target_lang,
                    )
                    out.append(resp.get("TranslatedText", t))
                except Exception as exc:
                    if not errors:
                        errors.append(exc)
                    out.append(t)
            return out, errors

        try:
            out, errors = await asyncio.get_event_loop().run_in_executor(None, _run)
            if errors:
                # Back on the event loop, so the async health write is possible.
                from app.services import connector_health
                await connector_health.note_quota_failure(
                    "translation", errors[0], provider=self.provider)
            return out
        except Exception as e:
            logger.warning(f"AWS Translate failed: {e}")
            return None


TRANSLATION_CATALOG: Dict[str, Dict[str, Any]] = {
    "google": {
        "name": "Google Cloud Translation",
        "description": "Google Translate — the default; ~100+ languages.",
        # Dispatch authenticates with the service account
        # (translation._get_auth_headers reads GCP_SERVICE_ACCOUNT_JSON); the
        # project id is never read on this path. This card used to collect
        # GOOGLE_CLOUD_PROJECT as its required credential, so "configured"
        # meant "typed a project name" on a translator that could not
        # authenticate. The service account is a bootstrap credential the
        # first-run setup collects, so it is declared in `requires` -- the
        # badge sees it -- rather than offered as a second box writing the
        # same secret.
        "credential_fields": [],
        "requires": [
            {"key": "GCP_SERVICE_ACCOUNT_JSON", "label": "Google service account", "where": "Setup"},
        ],
    },
    "azure": {
        "name": "Azure AI Translator",
        "description": "Azure AI Translator — for Microsoft and Azure Government stacks.",
        "credential_fields": [
            {"key": "AZURE_TRANSLATOR_KEY", "label": "Translator Key", "secret": True},
            {"key": "AZURE_TRANSLATOR_REGION", "label": "Region", "secret": False},
            {"key": "AZURE_TRANSLATOR_ENDPOINT", "label": "Endpoint (optional; .us for Gov)", "secret": False, "required": False},
        ],
        "field_help": {
            "AZURE_TRANSLATOR_KEY": "Key from your Azure Translator resource.",
            "AZURE_TRANSLATOR_REGION": "e.g. usgovvirginia or eastus.",
            "AZURE_TRANSLATOR_ENDPOINT": "Leave blank for global; use https://api.cognitive.microsofttranslator.us for Azure Government.",
        },
    },
    "aws": {
        "name": "Amazon Translate",
        "description": "AWS Translate — for AWS GovCloud stacks; uses your AWS credentials.",
        "credential_fields": [
            {"key": "AWS_REGION", "label": "AWS Region", "secret": False},
            {"key": "AWS_ACCESS_KEY_ID", "label": "Access Key ID (optional with instance role)", "secret": False, "required": False},
            {"key": "AWS_SECRET_ACCESS_KEY", "label": "Secret Access Key (optional with instance role)", "secret": True, "required": False},
        ],
        "field_help": {
            "AWS_REGION": "e.g. us-gov-west-1.",
            "AWS_ACCESS_KEY_ID": "Leave blank to use the instance role / default credential chain.",
            "AWS_SECRET_ACCESS_KEY": "Leave blank to use the instance role / default credential chain.",
        },
    },
}


def catalog_for_api() -> List[Dict[str, Any]]:
    return [
        {"provider": k, **v, "language_count": len(SUPPORTED_LANGUAGES.get(k, ()))}
        for k, v in TRANSLATION_CATALOG.items()
    ]


# --------------------------------------------------------------------------- #
# Supported target languages -- the one list.
#
# Codes are the platform's own (Google Translate v2 codes, which is what the
# resident portal's picker has always stored: `zh`, `zh-TW`, `he`, `jw`, `tl`,
# `no`). Each provider lists the platform codes it can translate into; a code it
# does not list is refused with a 400 rather than sent, billed and answered with
# an error (or worse, with the source text echoed back as if translated).
#
# Static lists rather than a live `/languages` call per request: the provider's
# list changes a few times a year, a live call is another outbound dependency
# on the resident's page load, and refusing a code the provider has just added
# costs a town one language until this list is updated -- whereas accepting one
# it does not support costs money every time. Conservative on purpose: a code
# goes in only where the provider's published language list shows it.
#   Google:  cloud.google.com/translate/docs/languages      (v2 / NMT, 2024)
#   Azure:   learn.microsoft.com/azure/ai-services/translator/language-support
#   AWS:     docs.aws.amazon.com/translate/latest/dg/what-is-languages.html
#
# The frontend's names live in frontend/src/utils/languages.ts; which of those
# the picker offers comes from GET /api/system/translate/languages, i.e. here.
# --------------------------------------------------------------------------- #

GOOGLE_LANGUAGES = frozenset({
    "af", "sq", "am", "ar", "hy", "az", "eu", "be", "bn", "bs", "bg", "ca", "ceb",
    "ny", "zh", "zh-TW", "co", "hr", "cs", "da", "nl", "en", "eo", "et", "tl", "fi",
    "fr", "fy", "gl", "ka", "de", "el", "gu", "ht", "ha", "haw", "he", "hi", "hmn",
    "hu", "is", "ig", "id", "ga", "it", "ja", "jw", "kn", "kk", "km", "rw", "ko",
    "ku", "ky", "lo", "la", "lv", "lt", "lb", "mk", "mg", "ms", "ml", "mt", "mi",
    "mr", "mn", "my", "ne", "no", "or", "ps", "fa", "pl", "pt", "pa", "ro", "ru",
    "sm", "gd", "sr", "st", "sn", "sd", "si", "sk", "sl", "so", "es", "su", "sw",
    "sv", "tg", "ta", "tt", "te", "th", "tr", "tk", "uk", "ur", "ug", "uz", "vi",
    "cy", "xh", "yi", "yo", "zu",
})

AZURE_LANGUAGES = frozenset({
    "af", "sq", "am", "ar", "hy", "az", "eu", "bn", "bs", "bg", "ca", "ny", "zh",
    "zh-TW", "hr", "cs", "da", "nl", "en", "et", "tl", "fi", "fr", "gl", "ka", "de",
    "el", "gu", "ht", "ha", "he", "hi", "hmn", "hu", "is", "ig", "id", "ga", "it",
    "ja", "kn", "kk", "km", "rw", "ko", "ku", "ky", "lo", "lv", "lt", "mk", "mg",
    "ms", "ml", "mt", "mi", "mr", "mn", "my", "ne", "no", "or", "ps", "fa", "pl",
    "pt", "pa", "ro", "ru", "sm", "sr", "st", "sn", "sd", "si", "sk", "sl", "so",
    "es", "sw", "sv", "ta", "tt", "te", "th", "tr", "tk", "uk", "ur", "ug", "uz",
    "vi", "cy", "xh", "yo", "zu",
})

AWS_LANGUAGES = frozenset({
    "af", "sq", "am", "ar", "hy", "az", "bn", "bs", "bg", "ca", "zh", "zh-TW", "hr",
    "cs", "da", "nl", "en", "et", "fa", "tl", "fi", "fr", "ka", "de", "el", "gu",
    "ht", "ha", "he", "hi", "hu", "is", "id", "ga", "it", "ja", "kn", "kk", "ko",
    "lv", "lt", "mk", "ms", "ml", "mt", "mr", "mn", "no", "ps", "pl", "pt", "pa",
    "ro", "ru", "sr", "si", "sk", "sl", "so", "es", "sw", "sv", "ta", "te", "th",
    "tr", "uk", "ur", "uz", "vi", "cy",
})

SUPPORTED_LANGUAGES: Dict[str, frozenset] = {
    "google": GOOGLE_LANGUAGES,
    "azure": AZURE_LANGUAGES,
    "aws": AWS_LANGUAGES,
}

# Where a provider spells a platform code differently. Applied at dispatch
# only; the cache and every API keep the platform code.
PROVIDER_CODE_MAP: Dict[str, Dict[str, str]] = {
    "azure": {
        "zh": "zh-Hans", "zh-TW": "zh-Hant", "no": "nb", "tl": "fil",
        "mn": "mn-Cyrl", "sr": "sr-Cyrl", "ny": "nya", "hmn": "mww", "ku": "kmr",
    },
}

_CANONICAL = {code.lower(): code for codes in SUPPORTED_LANGUAGES.values() for code in codes}


def canonical_language(code: Any) -> Optional[str]:
    """The platform spelling of a language code (`zh-tw` -> `zh-TW`), or None."""
    if not isinstance(code, str):
        return None
    return _CANONICAL.get(code.strip().lower())


def supported_languages(provider: Optional[str]) -> frozenset:
    """Target codes the named provider can translate into.

    An unknown or switched-off provider answers with Google's list: nothing is
    dispatched in that state, and the picker should keep offering what the
    platform default supports rather than collapse to nothing.
    """
    return SUPPORTED_LANGUAGES.get((provider or "google").strip().lower(), GOOGLE_LANGUAGES)


def provider_language_code(provider: Optional[str], code: str) -> str:
    """The code to send to `provider` for platform code `code`."""
    return PROVIDER_CODE_MAP.get((provider or "").lower(), {}).get(code, code)


async def selected_provider_name() -> str:
    """The provider the town chose (default google), credentials or not."""
    try:
        from app.services.secret_manager import get_secret

        name = ((await get_secret(TRANSLATION_PROVIDER_KEY)) or "google").strip().lower()
    except Exception:
        name = "google"
    return name if name in SUPPORTED_LANGUAGES else "google"


async def validate_target_language(code: Any) -> Optional[str]:
    """The canonical code if the selected provider supports it, else None."""
    canonical = canonical_language(code)
    if canonical is None:
        return None
    return canonical if canonical in supported_languages(await selected_provider_name()) else None


async def get_translation_provider() -> Optional[TranslationProvider]:
    """Return the configured translation provider (default google), or None if
    the selected provider isn't configured -- or if the town switched
    translation off while leaving its credentials in place.

    Google is the default and needs no key of its own beyond the cloud account,
    so before the switch existed a town on Google Cloud got translation whether
    or not it wanted it, and had nothing it could remove to stop it.
    """
    from app.services import capability_switches
    from app.services.secret_manager import get_secret

    if not await capability_switches.enabled("translation"):
        return None

    provider = (await get_secret(TRANSLATION_PROVIDER_KEY)) or "google"
    provider = provider.strip().lower()
    # A stored "none" is a choice, not a missing value -- the same words
    # image_redaction.resolve_provider honours. Falling through to the Google
    # default here dispatched translations for a town whose status page said
    # translation was off.
    if provider in ("none", "off", "disabled"):
        return None
    if provider == "azure":
        key = await get_secret("AZURE_TRANSLATOR_KEY")
        if not key:
            return None
        return AzureTranslationProvider(
            api_key=key,
            region=await get_secret("AZURE_TRANSLATOR_REGION") or "",
            endpoint=await get_secret("AZURE_TRANSLATOR_ENDPOINT"),
        )
    if provider == "aws":
        region = await get_secret("AWS_REGION")
        if not region:
            return None
        return AWSTranslateProvider(
            region=region,
            access_key=await get_secret("AWS_ACCESS_KEY_ID"),
            secret_key=await get_secret("AWS_SECRET_ACCESS_KEY"),
            session_token=await get_secret("AWS_SESSION_TOKEN"),
        )
    # Google is validated by _get_auth_headers at call time
    return GoogleTranslationProvider()
