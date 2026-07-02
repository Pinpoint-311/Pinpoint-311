"""AWS Bedrock adapter (Claude and other Bedrock models) — for AWS GovCloud
deployments. Uses boto3's Bedrock Runtime `converse` API, which gives one
uniform request/response shape across model families and supports vision.

boto3 is synchronous, so calls run in a thread executor.

Config/creds:
    region          AWS region (e.g. us-gov-west-1)
    model_id        Bedrock model id (e.g. anthropic.claude-3-5-sonnet-20240620-v1:0)
    access_key_id / secret_access_key   optional; omit to use the instance role
"""

import asyncio
import base64
import logging
from typing import Any, Dict, List, Optional

from app.services.ai.base import (
    AIProvider, analysis_fallback, parse_json_response, split_data_url,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic.claude-3-5-sonnet-20240620-v1:0"


class BedrockProvider(AIProvider):
    provider = "bedrock"

    def __init__(self, region: str, model_id: Optional[str] = None,
                 access_key_id: Optional[str] = None, secret_access_key: Optional[str] = None):
        super().__init__(model_id or DEFAULT_MODEL)
        self.region = region
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key

    def _client(self):
        import boto3
        kwargs = {"region_name": self.region}
        if self.access_key_id and self.secret_access_key:
            kwargs["aws_access_key_id"] = self.access_key_id
            kwargs["aws_secret_access_key"] = self.secret_access_key
        return boto3.client("bedrock-runtime", **kwargs)

    def _content_blocks(self, prompt: str, image_data: Optional[List[str]]):
        blocks: List[Dict[str, Any]] = [{"text": prompt}]
        for img in (image_data or [])[:3]:
            parsed = split_data_url(img)
            if not parsed:
                continue
            mime, b64 = parsed
            fmt = mime.split("/")[-1]
            fmt = "jpeg" if fmt in ("jpg", "jpeg") else fmt
            try:
                raw = base64.b64decode(b64)
            except Exception:
                continue
            blocks.append({"image": {"format": fmt, "source": {"bytes": raw}}})
        return blocks

    def _invoke_sync(self, prompt: str, image_data: Optional[List[str]]) -> Dict[str, Any]:
        client = self._client()
        resp = client.converse(
            modelId=self.model,
            messages=[{"role": "user", "content": self._content_blocks(prompt, image_data)}],
            system=[{"text": "You are a municipal 311 triage analyst. Respond ONLY with a single JSON object."}],
            inferenceConfig={"temperature": 0.2, "maxTokens": 4096},
        )
        parts = resp["output"]["message"]["content"]
        text = "".join(p.get("text", "") for p in parts)
        return parse_json_response(text)

    async def complete_json(self, prompt: str, image_data: Optional[List[str]] = None) -> Dict[str, Any]:
        if not self.region:
            return analysis_fallback("Bedrock not configured (region missing)")
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._invoke_sync, prompt, image_data)
        except Exception as e:  # noqa: BLE001 — providers must never raise
            logger.warning(f"[AI/bedrock] analysis failed: {e}")
            return analysis_fallback(str(e))
