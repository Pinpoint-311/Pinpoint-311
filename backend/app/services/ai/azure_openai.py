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

logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2024-06-01"
DEFAULT_DEPLOYMENT = "gpt-4o-mini"


class AzureOpenAIProvider(AIProvider):
    provider = "azure"

    def __init__(self, endpoint: str, api_key: str, deployment: Optional[str] = None,
                 api_version: str = DEFAULT_API_VERSION):
        super().__init__(deployment or DEFAULT_DEPLOYMENT)
        self.endpoint = (endpoint or "").rstrip("/")
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

    async def complete_json(self, prompt: str, image_data: Optional[List[str]] = None) -> Dict[str, Any]:
        if not self.endpoint or not self.api_key:
            return analysis_fallback("Azure OpenAI not configured (endpoint/api_key missing)")
        url = f"{self.endpoint}/openai/deployments/{self.model}/chat/completions?api-version={self.api_version}"
        payload = {
            "messages": self._build_messages(prompt, image_data),
            "temperature": 0.2,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                resp = await client.post(url, headers={"api-key": self.api_key}, json=payload)
                if resp.status_code >= 400:
                    return analysis_fallback(f"Azure OpenAI HTTP {resp.status_code}: {resp.text[:200]}")
                body = resp.json()
            text = body["choices"][0]["message"]["content"]
            return parse_json_response(text)
        except Exception as e:  # noqa: BLE001 — providers must never raise
            logger.warning(f"[AI/azure] analysis failed: {e}")
            return analysis_fallback(str(e))
