"""Google Vertex AI adapter (Gemini). Wraps the existing, battle-tested
`analyze_with_gemini` call so behavior is identical to today for the default
deployment — this is the unchanged default provider."""

import logging
from typing import Any, Dict, List, Optional

from app.services.ai.base import AIProvider, AIProviderError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.1-flash-lite"


class VertexAIProvider(AIProvider):
    provider = "vertex"

    def __init__(self, project_id: str, service_account_json: Optional[str] = None,
                 model: Optional[str] = None, location: str = "global"):
        super().__init__(model or DEFAULT_MODEL)
        self.project_id = project_id
        self.service_account_json = service_account_json
        self.location = location

    async def complete_json(self, prompt: str, image_data: Optional[List[str]] = None) -> Dict[str, Any]:
        # Delegate to the existing implementation (returns analysis_fallback shape on error)
        from app.services.vertex_ai_service import analyze_with_gemini
        return await analyze_with_gemini(
            project_id=self.project_id,
            location=self.location,
            prompt=prompt,
            image_data=image_data,
            service_account_json=self.service_account_json or None,
            model=self.model,
        )

    async def complete_text(self, prompt: str, temperature: float = 0.3,
                            max_tokens: int = 4096) -> str:
        import json
        import os

        import aiohttp
        import google.auth
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        from app.services.ai import vertex_publishers as vp

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        try:
            if self.service_account_json:
                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(self.service_account_json), scopes=scopes)
            else:
                credentials, _ = google.auth.default(scopes=scopes)
            credentials.refresh(Request())
        except Exception as e:  # noqa: BLE001
            raise AIProviderError(f"Vertex AI credentials: {e}") from e

        location = os.getenv("VERTEX_AI_LOCATION") or self.location or "global"
        endpoint = vp.endpoint_for(self.model, self.project_id, location)
        payload = vp.build_payload(self.model, prompt, None, max_tokens=max_tokens)
        # Same envelope as triage, minus what only suits a JSON verdict: a chat
        # reads better a little warmer, and HIGH thinking spends the output
        # budget before the answer starts.
        if "generationConfig" in payload:
            payload["generationConfig"]["temperature"] = temperature
            payload["generationConfig"].pop("thinkingConfig", None)
        else:
            payload["temperature"] = temperature

        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                headers={"Authorization": f"Bearer {credentials.token}",
                         "Content-Type": "application/json"},
                json=payload,
            ) as response:
                if response.status != 200:
                    raise AIProviderError(
                        f"Vertex AI HTTP {response.status}: {(await response.text())[:300]}")
                result = await response.json()
        return vp.extract_text(self.model, result)
