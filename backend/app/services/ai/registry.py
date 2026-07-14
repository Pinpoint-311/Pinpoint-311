"""AI provider catalog + config-driven factory.

AI_CATALOG drives the admin UI (provider cards, model pickers, field hints)
and documents which secret keys each provider needs. `get_ai_provider(db)`
reads the configured provider + its secrets and returns a ready adapter, or
None when AI is not configured (triage then skips, exactly as today).

Default provider is **vertex**, so existing deployments are unchanged.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# secret key that selects the provider; model is per-provider
AI_PROVIDER_KEY = "AI_PROVIDER"
AI_MODEL_KEY = "AI_MODEL"

AI_CATALOG: Dict[str, Dict[str, Any]] = {
    "vertex": {
        "name": "Google Vertex AI",
        "boundary": "Google Cloud (Assured Workloads / FedRAMP High)",
        "description": "Gemini models on Vertex AI. The default — cheapest for triage and already integrated.",
        "models": [
            {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite (fast, cheap — recommended for triage)"},
            {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash (near-Pro quality, 1M context)"},
        ],
        "default_model": "gemini-3.1-flash-lite",
        "credential_fields": [
            {"key": "VERTEX_AI_PROJECT", "label": "GCP Project ID", "secret": False},
            {"key": "VERTEX_AI_SERVICE_ACCOUNT_KEY", "label": "Service Account JSON", "secret": True},
        ],
        "field_help": {
            "VERTEX_AI_PROJECT": "Your Google Cloud project id.",
            "VERTEX_AI_SERVICE_ACCOUNT_KEY": "Optional if the host provides default credentials; otherwise paste the service-account JSON.",
        },
    },
    "azure": {
        "name": "Azure Government AI",
        "boundary": "Azure Government / GCC High (FedRAMP High / DoD)",
        "description": "Azure OpenAI (GPT models) in US government regions. Best for Microsoft/M365 states.",
        "models": [
            {"id": "gpt-4o-mini", "label": "GPT-4o mini (fast, cheap)"},
            {"id": "gpt-4o", "label": "GPT-4o (higher quality)"},
        ],
        "default_model": "gpt-4o-mini",
        "credential_fields": [
            {"key": "AZURE_OPENAI_ENDPOINT", "label": "Azure OpenAI Endpoint", "secret": False},
            {"key": "AZURE_OPENAI_API_KEY", "label": "API Key", "secret": True},
            {"key": "AZURE_OPENAI_DEPLOYMENT", "label": "Deployment name", "secret": False},
            {"key": "AZURE_OPENAI_API_VERSION", "label": "API version (optional)", "secret": False},
        ],
        "field_help": {
            "AZURE_OPENAI_ENDPOINT": "e.g. https://your-resource.openai.azure.us — the Gov-cloud endpoint from the Azure portal.",
            "AZURE_OPENAI_API_KEY": "Key 1 or Key 2 from your Azure OpenAI resource.",
            "AZURE_OPENAI_DEPLOYMENT": "The deployment name you created for the model (acts as the model id).",
            "AZURE_OPENAI_API_VERSION": "Leave blank to use the supported default.",
        },
    },
    "bedrock": {
        "name": "AWS Bedrock",
        "boundary": "AWS GovCloud (FedRAMP High)",
        "description": "Claude and other models via Amazon Bedrock. Best for AWS GovCloud states that want Claude in-boundary.",
        "models": [
            {"id": "anthropic.claude-3-5-sonnet-20240620-v1:0", "label": "Claude 3.5 Sonnet (quality)"},
            {"id": "anthropic.claude-3-haiku-20240307-v1:0", "label": "Claude 3 Haiku (fast, cheap)"},
        ],
        "default_model": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "credential_fields": [
            {"key": "AWS_REGION", "label": "AWS Region", "secret": False},
            {"key": "AWS_ACCESS_KEY_ID", "label": "Access Key ID (optional)", "secret": False},
            {"key": "AWS_SECRET_ACCESS_KEY", "label": "Secret Access Key (optional)", "secret": True},
        ],
        "field_help": {
            "AWS_REGION": "e.g. us-gov-west-1. Shared across all AWS services (Bedrock, Translate, Secrets Manager, KMS, SES, SNS).",
            "AWS_ACCESS_KEY_ID": "Optional — omit to use the host's instance role. Shared by every AWS service.",
            "AWS_SECRET_ACCESS_KEY": "Optional — omit to use the host's instance role. Shared by every AWS service.",
        },
    },
}


def catalog_for_api() -> List[Dict[str, Any]]:
    """Public catalog shape for the admin UI (no secrets)."""
    return [{"provider": key, **{k: v for k, v in meta.items()}} for key, meta in AI_CATALOG.items()]


def build_ai_provider(provider: str, model: Optional[str], creds: Dict[str, str]):
    """Construct an adapter from a provider name + resolved secrets. Returns
    None if the required config for that provider is missing."""
    if provider == "vertex":
        project = creds.get("VERTEX_AI_PROJECT")
        if not project:
            return None
        from app.services.ai.vertex import VertexAIProvider
        return VertexAIProvider(
            project_id=project,
            service_account_json=creds.get("VERTEX_AI_SERVICE_ACCOUNT_KEY"),
            model=model,
        )
    if provider == "azure":
        endpoint = creds.get("AZURE_OPENAI_ENDPOINT")
        api_key = creds.get("AZURE_OPENAI_API_KEY")
        if not endpoint or not api_key:
            return None
        from app.services.ai.azure_openai import AzureOpenAIProvider
        return AzureOpenAIProvider(
            endpoint=endpoint,
            api_key=api_key,
            deployment=model or creds.get("AZURE_OPENAI_DEPLOYMENT"),
            api_version=creds.get("AZURE_OPENAI_API_VERSION") or "2024-06-01",
        )
    if provider == "bedrock":
        region = creds.get("AWS_REGION")
        if not region:
            return None
        from app.services.ai.bedrock import BedrockProvider
        return BedrockProvider(
            region=region,
            model_id=model,
            # Shared AWS credentials (fall back to legacy BEDROCK_* if present).
            access_key_id=creds.get("AWS_ACCESS_KEY_ID") or creds.get("BEDROCK_ACCESS_KEY_ID"),
            secret_access_key=creds.get("AWS_SECRET_ACCESS_KEY") or creds.get("BEDROCK_SECRET_ACCESS_KEY"),
        )
    return None


async def get_ai_provider(db=None):
    """Read config from the secret store and return a ready AIProvider, or None
    if AI is not configured for this instance (triage then skips, as today)."""
    from app.services.secret_manager import get_secret

    provider = (await get_secret(AI_PROVIDER_KEY)) or "vertex"
    provider = provider.strip().lower()
    if provider not in AI_CATALOG:
        from app.core.sanitize import sanitize_for_log
        logger.warning(f"[AI] Unknown AI_PROVIDER '{sanitize_for_log(provider)}', falling back to vertex")
        provider = "vertex"

    model = (await get_secret(AI_MODEL_KEY)) or AI_CATALOG[provider].get("default_model")

    # Resolve just the secrets this provider needs
    creds: Dict[str, str] = {}
    for field in AI_CATALOG[provider]["credential_fields"]:
        val = await get_secret(field["key"])
        if val:
            creds[field["key"]] = val

    return build_ai_provider(provider, model, creds)
