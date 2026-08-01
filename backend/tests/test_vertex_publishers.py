"""Vertex serves more than Gemini, and the picker must only offer what we call.

PR #433 listed eight publishers from Model Garden while the caller still built
`publishers/google/.../:generateContent` for every one of them. A clerk could
select Claude on Vertex, save it, and watch triage 404 -- a setting that stores
fine and silently does nothing, which is the shape this console keeps being
fixed for.

The answer is not to hide them. It is to speak their protocol, and to offer
exactly the publishers we have a handler for.
"""

from app.services.ai import vertex_publishers as V


class TestWhoseModelIsThis:
    def test_gemini_is_google(self):
        assert V.publisher_for("gemini-3.5-flash") == V.GOOGLE

    def test_claude_is_anthropic(self):
        assert V.publisher_for("claude-sonnet-4@20250514") == V.ANTHROPIC

    def test_an_explicit_prefix_wins(self):
        assert V.publisher_for("anthropic/claude-x") == V.ANTHROPIC

    def test_an_unknown_id_falls_back_to_google(self):
        """Which is where every stored id came from before this existed, so an
        upgrade cannot reroute a town's working model somewhere else."""
        assert V.publisher_for("some-new-google-thing") == V.GOOGLE
        assert V.publisher_for(None) == V.GOOGLE
        assert V.publisher_for("") == V.GOOGLE

    def test_case_and_stray_slashes_do_not_change_the_answer(self):
        assert V.publisher_for("  Claude-Opus-4  ") == V.ANTHROPIC
        assert V.publisher_for("/gemini-3.5-flash") == V.GOOGLE


class TestOnlyOfferWhatWeCanCall:
    def test_the_supported_list_is_what_has_a_handler(self):
        for publisher in V.SUPPORTED_PUBLISHERS:
            model = "gemini-3.5-flash" if publisher == V.GOOGLE else "claude-sonnet-4"
            assert V.publisher_for(model) == publisher
            assert V.build_payload(model, "hi")
            assert V.endpoint_for(model, "proj")

    def test_meta_and_mistral_are_not_offered_yet(self):
        """They are real on Vertex and served through a third shape, the
        OpenAI-compatible MaaS endpoint. Listing them before that is
        implemented would be offering models that cannot be called."""
        assert "meta" not in V.SUPPORTED_PUBLISHERS
        assert "mistral" not in V.SUPPORTED_PUBLISHERS


class TestTheEndpoint:
    def test_gemini_uses_generate_content(self):
        url = V.endpoint_for("gemini-3.5-flash", "town-311")
        assert url.endswith(":generateContent")
        assert "publishers/google" in url

    def test_claude_uses_raw_predict(self):
        url = V.endpoint_for("claude-sonnet-4", "town-311")
        assert url.endswith(":rawPredict")
        assert "publishers/anthropic" in url

    def test_claude_is_not_asked_for_from_the_global_endpoint(self):
        """Anthropic models are not served there, and the 404 reads like a
        wrong model name rather than a wrong host."""
        url = V.endpoint_for("claude-sonnet-4", "town-311", "global")
        assert "global" not in url
        assert "-aiplatform.googleapis.com" in url

    def test_a_configured_region_is_honoured(self):
        """PR #433 hardcoded us-central1 and dropped VERTEX_AI_LOCATION, which
        is the wrong direction for a product sold on compliance boundaries."""
        assert "europe-west4" in V.endpoint_for("gemini-3.5-flash", "p", "europe-west4")
        assert "us-east5" in V.endpoint_for("claude-sonnet-4", "p", "us-east5")

    def test_a_qualified_id_does_not_leak_into_the_path(self):
        url = V.endpoint_for("anthropic/claude-sonnet-4", "p")
        assert "models/claude-sonnet-4:" in url
        assert "anthropic/claude" not in url.split("publishers/")[1]


class TestTheEnvelope:
    def test_gemini_gets_contents_and_parts(self):
        body = V.build_payload("gemini-3.5-flash", "describe this")
        assert body["contents"][0]["parts"][-1]["text"] == "describe this"
        assert "anthropic_version" not in body

    def test_claude_gets_messages_and_the_version_marker(self):
        body = V.build_payload("claude-sonnet-4", "describe this")
        assert body["anthropic_version"] == "vertex-2023-10-16"
        assert body["messages"][0]["content"][-1]["text"] == "describe this"
        assert "contents" not in body

    def test_claude_requires_max_tokens(self):
        """Anthropic's API rejects a request without it, so a missing default
        would fail every call rather than degrade."""
        assert V.build_payload("claude-sonnet-4", "x")["max_tokens"] > 0

    def test_images_ride_in_each_publisher_own_shape(self):
        img = [{"mime_type": "image/jpeg", "data": "AAA"}]
        g = V.build_payload("gemini-3.5-flash", "x", img)
        assert g["contents"][0]["parts"][0]["inline_data"]["data"] == "AAA"
        a = V.build_payload("claude-sonnet-4", "x", img)
        assert a["messages"][0]["content"][0]["source"]["data"] == "AAA"

    def test_the_prompt_comes_last_so_images_precede_it(self):
        img = [{"mime_type": "image/png", "data": "B"}]
        for model in ("gemini-3.5-flash", "claude-sonnet-4"):
            body = V.build_payload(model, "the question", img)
            blocks = body.get("contents", [{}])[0].get("parts") or body["messages"][0]["content"]
            assert "text" in blocks[-1]


class TestReadingTheAnswer:
    def test_gemini_text_is_joined_and_thoughts_are_skipped(self):
        result = {"candidates": [{"content": {"parts": [
            {"text": "ignore me", "thought": True},
            {"text": '{"priority'}, {"text": '_score": 5}'},
        ]}}]}
        assert V.extract_text("gemini-3.5-flash", result) == '{"priority_score": 5}'

    def test_claude_text_blocks_are_joined(self):
        result = {"content": [{"type": "text", "text": '{"a":'}, {"type": "text", "text": " 1}"}]}
        assert V.extract_text("claude-sonnet-4", result) == '{"a": 1}'

    def test_a_non_text_block_is_ignored(self):
        result = {"content": [{"type": "thinking", "thinking": "hmm"},
                              {"type": "text", "text": "answer"}]}
        assert V.extract_text("claude-sonnet-4", result) == "answer"

    def test_an_empty_response_is_empty_rather_than_an_error(self):
        for model in ("gemini-3.5-flash", "claude-sonnet-4"):
            assert V.extract_text(model, {}) == ""


# ---------------------------------------------------------------------------
# The rest of what PR #433 changed
# ---------------------------------------------------------------------------

def _source(rel: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / rel).read_text()


class TestDiscoveryOffersOnlyUsableModels:
    def test_bedrock_still_asks_for_text_and_on_demand(self):
        """Without these an embedding model, an image model, or one needing
        provisioned throughput lands in a triage picker and fails at request
        time rather than at selection."""
        src = _source("app/services/ai/model_discovery.py")
        assert 'byOutputModality="TEXT"' in src
        assert 'byInferenceType="ON_DEMAND"' in src

    def test_vertex_honours_the_configured_region(self):
        src = _source("app/services/ai/model_discovery.py")
        assert 'creds.get("VERTEX_AI_LOCATION")' in src
        assert "us-central1-aiplatform" not in src, "the region is hardcoded again"

    def test_vertex_lists_only_publishers_with_a_handler(self):
        src = _source("app/services/ai/model_discovery.py")
        assert "SUPPORTED_PUBLISHERS" in src
        for unsupported in ('"meta"', '"mistral"', '"cohere"', '"ai21"', '"writer"', '"xai"'):
            assert unsupported not in src, f"{unsupported} is offered without a handler"

    def test_a_failing_publisher_is_logged_rather_than_swallowed(self):
        """Eight silent excepts meant all eight could fail while the picker
        showed a short list and nobody learned why."""
        src = _source("app/services/ai/model_discovery.py")
        assert "failures.append" in src


class TestTheCallerSpeaksMoreThanGemini:
    def test_it_dispatches_on_publisher(self):
        src = _source("app/services/vertex_ai_service.py")
        assert "vertex_publishers" in src
        assert "vp.endpoint_for" in src and "vp.build_payload" in src

    def test_the_endpoint_is_no_longer_hardcoded_to_google(self):
        src = _source("app/services/vertex_ai_service.py")
        assert "publishers/google/models/{model_id}:generateContent" not in src


class TestOneDefaultPerProvider:
    def test_azure_agrees_with_itself(self):
        """The catalog's default and the client's fallback are two defaults for
        the same thing; drift puts a town on a deployment the picker never
        offered."""
        registry = _source("app/services/ai/registry.py")
        client = _source("app/services/ai/azure_openai.py")
        import re
        catalog_default = re.search(r'"default_model": "(gpt[^"]+)"', registry).group(1)
        client_default = re.search(r'DEFAULT_DEPLOYMENT = "([^"]+)"', client).group(1)
        assert catalog_default == client_default
