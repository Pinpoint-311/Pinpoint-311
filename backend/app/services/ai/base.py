"""Provider-agnostic AI interface for Pinpoint 311.

An AIProvider turns a prompt (+ optional images) into a parsed JSON analysis
object. The concrete adapters (Vertex AI / Azure Government AI / AWS Bedrock)
all return the same shape, so the triage pipeline and analytics assistant don't
care which boundary/model a jurisdiction chose.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def analysis_fallback(reason: str) -> Dict[str, Any]:
    """Neutral analysis object returned when a provider call fails, so triage
    never crashes — the request simply gets a manual-review default."""
    return {
        "priority_score": 5.0,
        "priority_justification": f"AI analysis failed: {reason[:100]}",
        "qualitative_analysis": "AI analysis could not be completed due to a service error. Manual review recommended.",
        "quantitative_metrics": {
            "estimated_severity": "unknown",
            "estimated_affected_area": "unknown",
            "is_likely_duplicate": False,
            "recurrence_risk": "unknown",
        },
        "safety_flags": [],
        "recommended_response_time": "48h",
        "_error": reason,
    }


def parse_json_response(text: str) -> Dict[str, Any]:
    """Extract a JSON object from a model text response (handles ```json fences)."""
    if not text:
        raise ValueError("empty model response")
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    payload = match.group(1) if match else text.strip()
    # Some models wrap in a plain ``` fence
    if payload.startswith("```"):
        payload = payload.strip("`").strip()
    return json.loads(payload)


def split_data_url(img: str) -> Optional[tuple]:
    """Return (mime_type, base64_data) for a data URL or raw base64, else None."""
    if not isinstance(img, str) or not img:
        return None
    if img.startswith("data:"):
        m = re.match(r"data:(image/[\w.+-]+);base64,(.+)", img, re.DOTALL)
        if not m:
            return None
        return m.group(1), m.group(2)
    # bare base64 — assume jpeg
    return "image/jpeg", img


class AIProvider:
    """Base adapter. Subclasses implement `complete_json`."""

    provider: str = "base"

    def __init__(self, model: Optional[str] = None):
        self.model = model

    async def complete_json(self, prompt: str, image_data: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run the prompt (+ optional images) and return a parsed JSON analysis.
        Implementations must never raise — return analysis_fallback(...) on error."""
        raise NotImplementedError
