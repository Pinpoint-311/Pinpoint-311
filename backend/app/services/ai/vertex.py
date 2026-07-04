"""Google Vertex AI adapter (Gemini). Wraps the existing, battle-tested
`analyze_with_gemini` call so behavior is identical to today for the default
deployment — this is the unchanged default provider."""

import logging
from typing import Any, Dict, List, Optional

from app.services.ai.base import AIProvider

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"


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
