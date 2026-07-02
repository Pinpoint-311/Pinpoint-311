"""Pluggable AI providers (Vertex AI / Azure Government AI / AWS Bedrock).

Every deployment — self-hosted or centrally hosted — can choose its AI
boundary and model via config, with Vertex/Gemini as the unchanged default.
"""

from app.services.ai.base import AIProvider, analysis_fallback  # noqa: F401
from app.services.ai.registry import (  # noqa: F401
    AI_CATALOG,
    build_ai_provider,
    catalog_for_api,
    get_ai_provider,
)
