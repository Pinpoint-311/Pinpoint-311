"""Azure Government AI adapter — Azure OpenAI Service (GPT models) in the
US Government / GCC High regions. Uses the REST API over httpx (OpenAI-
compatible), so no extra SDK dependency and it's fully mockable.

Config/creds:
    endpoint    e.g. https://your-resource.openai.azure.us   (Gov cloud)
    api_key     Azure OpenAI key
    deployment  the model deployment name (acts as the model id)
    api_version default 2024-06-01
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.services.ai.base import (
    AIProvider, analysis_fallback, parse_json_response, split_data_url,
)

from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2024-06-01"
# Kept in step with the catalog's default_model in registry.py; a test fails
# if they drift. Two defaults for the same thing is how a town ends up on a
# deployment the picker never offered.
DEFAULT_DEPLOYMENT = "gpt-4.1-mini"

# deployment name -> the token-limit parameter it accepts. Learned at
# runtime from Azure's own rejection; see complete_json.
_TOKEN_PARAM: Dict[str, str] = {}


def normalise_azure_endpoint(endpoint: Optional[str]) -> str:
    """Reduce whatever was pasted to the account's base URL.

    The Azure portal puts a complete sample request on the same screen as the
    key -- "Target URI", ending in a path and an api-version query -- and it is
    what an operator copies, because it is the thing that looks like the
    endpoint. Pinpoint then appends `/openai/deployments/...` to it and Azure
    answers a bare 404 "Resource not found", which says nothing about the URL
    being the problem. Live, the saved value was:

        https://NAME.openai.azure.com/openai/responses?api-version=2025-04-01-preview

    An Azure OpenAI data-plane base is always scheme + host with no path, so a
    query string is never right and a path beginning `/openai` is always the
    sample request rather than the endpoint. Anything else is left alone: a town
    behind a reverse proxy on a path prefix is unusual but not wrong, and
    silently rewriting that would break a working deployment to fix a typo.
    """
    raw = (endpoint or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")
    path = parts.path or ""
    marker = path.lower().find("/openai")
    if marker >= 0:
        path = path[:marker]
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))


class AzureOpenAIProvider(AIProvider):
    provider = "azure"

    def __init__(self, endpoint: str, api_key: str, deployment: Optional[str] = None,
                 api_version: str = DEFAULT_API_VERSION):
        super().__init__(deployment or DEFAULT_DEPLOYMENT)
        self.endpoint = normalise_azure_endpoint(endpoint)
        self.api_key = api_key
        self.api_version = api_version or DEFAULT_API_VERSION

    def _build_messages(self, prompt: str, image_data: Optional[List[str]]):
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in (image_data or [])[:3]:
            parsed = split_data_url(img)
            if not parsed:
                continue
            mime, b64 = parsed
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
        return [
            {"role": "system", "content": "You are a municipal 311 triage analyst. Respond ONLY with a single JSON object."},
            {"role": "user", "content": content},
        ]


    def _explain(self, resp) -> str:
        """Say which deployment was asked for, not just that one was missing.

        Azure answers DeploymentNotFound with the name nowhere in the message,
        and on this deployment the name being asked for was `gemini-3.6-flash`
        -- a Google model id left behind by an earlier provider. The operator
        reading the raw error has no way to see that: it looks like Azure
        losing a deployment they are sure they made, rather than Pinpoint
        asking for one that was never theirs.
        """
        body = resp.text[:200]
        if resp.status_code == 404 and "DeploymentNotFound" in resp.text:
            return (
                f"Azure has no deployment named \"{self.model}\". A deployment name is "
                "one you choose in Azure AI Foundry when you deploy a model -- it is not "
                "a model id, and a name from another provider will never match. Create a "
                "deployment there and put its name in the Deployment name box."
            )
        return f"Azure OpenAI HTTP {resp.status_code}: {body}"

    async def complete_json(self, prompt: str, image_data: Optional[List[str]] = None) -> Dict[str, Any]:
        if not self.endpoint or not self.api_key:
            return analysis_fallback("Azure OpenAI not configured (endpoint/api_key missing)")
        url = f"{self.endpoint}/openai/deployments/{self.model}/chat/completions?api-version={self.api_version}"

        def build(token_key: str) -> Dict[str, Any]:
            return {
                "messages": self._build_messages(prompt, image_data),
                "temperature": 0.2,
                token_key: 4096,
                "response_format": {"type": "json_object"},
            }

        token_key = _TOKEN_PARAM.get(self.model, "max_tokens")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                resp = await client.post(url, headers={"api-key": self.api_key},
                                         json=build(token_key))

                # Newer models reject `max_tokens` and want `max_completion_tokens`.
                # Which ones is not knowable from here and moves: this codebase
                # has already been bitten by a hardcoded model list going stale,
                # so the switch is driven by Azure saying so rather than by a
                # list we maintain. Remembered per deployment, so the wasted
                # round trip happens once per process and not per report.
                if (resp.status_code == 400
                        and "max_completion_tokens" in resp.text
                        and token_key == "max_tokens"):
                    token_key = "max_completion_tokens"
                    _TOKEN_PARAM[self.model] = token_key
                    resp = await client.post(url, headers={"api-key": self.api_key},
                                             json=build(token_key))

                if resp.status_code >= 400:
                    return analysis_fallback(self._explain(resp))
                body = resp.json()
            text = body["choices"][0]["message"]["content"]
            return parse_json_response(text)
        except Exception as e:  # noqa: BLE001 — providers must never raise
            logger.warning(f"[AI/azure] analysis failed: {e}")
            return analysis_fallback(str(e))
