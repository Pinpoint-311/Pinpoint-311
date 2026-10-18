"""The chat assistants use the town's configured AI provider.

The staff Analytics Advisor and the Research Data Assistant used to call
Vertex/Gemini directly, so a town on Azure OpenAI or Bedrock got "Vertex AI not
configured" from them while triage and the console's AI test worked. They now
go through `AIProvider.complete_text`.
"""

import asyncio
import inspect

import pytest

pytest.importorskip("httpx")
azure_mod = pytest.importorskip("app.services.ai.azure_openai")
from app.services.ai.base import AIProviderError  # noqa: E402


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses, seen):
        self._responses = responses
        self._seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self._seen.append(json)
        return self._responses.pop(0)


def _patch(monkeypatch, responses):
    seen = []
    monkeypatch.setattr(azure_mod.httpx, "AsyncClient", lambda **kw: _Client(responses, seen))
    return seen


def test_azure_complete_text_is_free_text(monkeypatch):
    seen = _patch(monkeypatch, [_Resp(200, {"choices": [{"message": {"content": "Hello."}}]})])
    p = azure_mod.AzureOpenAIProvider("https://x.openai.azure.com", "k", "chat-dep")
    out = asyncio.run(p.complete_text("hi", temperature=0.3))
    assert out == "Hello."
    body = seen[0]
    # A chat answer is prose: no JSON mode, no triage system prompt.
    assert "response_format" not in body
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["temperature"] == 0.3


def test_azure_complete_text_retries_like_triage(monkeypatch):
    azure_mod._NO_TEMPERATURE.discard("reasoner")
    seen = _patch(monkeypatch, [
        _Resp(400, text="Unsupported value: 'temperature' does not support 0.3"),
        _Resp(200, {"choices": [{"message": {"content": "ok"}}]}),
    ])
    p = azure_mod.AzureOpenAIProvider("https://x.openai.azure.com", "k", "reasoner")
    assert asyncio.run(p.complete_text("hi")) == "ok"
    assert "temperature" not in seen[1]
    azure_mod._NO_TEMPERATURE.discard("reasoner")


def test_azure_complete_text_raises_on_error(monkeypatch):
    _patch(monkeypatch, [_Resp(404, text='{"error":{"code":"DeploymentNotFound"}}')])
    p = azure_mod.AzureOpenAIProvider("https://x.openai.azure.com", "k", "missing")
    with pytest.raises(AIProviderError, match="missing"):
        asyncio.run(p.complete_text("hi"))


@pytest.mark.parametrize("module, fn", [
    ("app.api.system", "analytics_chat"),
    ("app.api.research", "research_chat"),
])
def test_chat_endpoints_use_the_configured_provider(module, fn):
    mod = pytest.importorskip(module)
    src = inspect.getsource(getattr(mod, fn))
    assert "get_ai_provider" in src and "complete_text" in src
    assert "aiplatform.googleapis.com" not in src
    assert "VERTEX_AI_PROJECT" not in src
