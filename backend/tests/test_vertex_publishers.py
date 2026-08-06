"""Vertex serves more than Gemini, and the picker must only offer what we call.

PR #433 listed eight publishers from Model Garden while the caller still built
`publishers/google/.../:generateContent` for every one of them. A clerk could
select Claude on Vertex, save it, and watch triage 404 -- a setting that stores
fine and silently does nothing, which is the shape this console keeps being
fixed for.

The answer is not to hide them. It is to speak their protocol, and to offer
exactly the publishers we have a handler for.
"""

import re
from urllib.parse import urlparse

from app.services.ai import vertex_publishers as V

# Vertex hosts are `aiplatform.googleapis.com` or `{region}-aiplatform...` --
# a hyphen, not a dot. That hyphen is why a substring check was tempting and
# why `endswith(".aiplatform.googleapis.com")` is wrong; matching the whole
# host is the only form that is both correct and unambiguous.
VERTEX_HOST = re.compile(r"^(?:[a-z0-9-]+-)?aiplatform\.googleapis\.com$")


def host_of(url: str) -> str:
    """The actual host, not a substring of the URL.

    CodeQL rates `"-aiplatform.googleapis.com" in url` as a high-severity
    finding and it is right to: that assertion also passes for
    `evil-aiplatform.googleapis.com.attacker.com`. In production that pattern
    is an SSRF bypass, and in a test it is an assertion that does not check
    what it claims to.
    """
    return urlparse(url).hostname or ""


class TestWhoseModelIsThis:
    def test_gemini_is_google(self):
        assert V.publisher_for("gemini-3.5-flash") == V.GOOGLE

    def test_claude_is_anthropic(self):
        assert V.publisher_for("claude-sonnet-4@20250514") == V.ANTHROPIC

    def test_an_explicit_prefix_wins(self):
        assert V.publisher_for("anthropic/claude-x") == V.ANTHROPIC

    def test_llama_is_meta(self):
        assert V.publisher_for("llama-3.3-70b-instruct-maas") == V.META
        assert V.publisher_for("meta/llama-4-maverick-17b-128e-instruct-maas") == V.META

    def test_mistral_family_names_are_mistralai(self):
        """Their ids do not share a prefix -- ministral and codestral are
        Mistral's too -- and a missed prefix falls back to a Gemini-shaped
        request that 404s at triage."""
        for mid in ("mistral-small-2503", "mistral-large-3", "mixtral-8x7b",
                    "ministral-3", "codestral-2", "mistralai/mistral-medium-3"):
            assert V.publisher_for(mid) == V.MISTRAL, mid

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
        samples = {
            V.GOOGLE: "gemini-3.5-flash",
            V.ANTHROPIC: "claude-sonnet-4",
            V.META: "llama-3.3-70b-instruct-maas",
            V.MISTRAL: "mistral-small-2503",
        }
        for publisher in V.SUPPORTED_PUBLISHERS:
            model = samples[publisher]
            assert V.publisher_for(model) == publisher
            assert V.build_payload(model, "hi")
            assert V.endpoint_for(model, "proj")

    def test_the_remaining_maas_publishers_are_not_offered_yet(self):
        """AI21, Cohere and xAI are real on Vertex but nobody has verified
        their wire shape against a live project. Listing them before that
        would be offering models that cannot be called."""
        for absent in ("ai21", "cohere", "xai"):
            assert absent not in V.SUPPORTED_PUBLISHERS


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
        assert "/locations/global/" not in url
        assert VERTEX_HOST.match(host_of(url))

    def test_maas_models_share_the_openai_endpoint(self):
        """One URL for Meta and Mistral both -- the model rides in the body,
        not the path (see the envelope tests)."""
        for model in ("llama-3.3-70b-instruct-maas", "mistral-small-2503"):
            url = V.endpoint_for(model, "town-311")
            assert url.endswith("/endpoints/openapi/chat/completions")
            # No model segment in the path -- rawPredict/generateContent
            # publishers carry it there, this endpoint must not.
            assert "/models/" not in url

    def test_maas_is_not_asked_for_from_the_global_endpoint(self):
        """Meta lists nothing from `global` (observed live); us-central1 is
        where the MaaS models are served."""
        url = V.endpoint_for("llama-3.3-70b-instruct-maas", "town-311", "global")
        assert "/locations/global/" not in url
        assert host_of(url).startswith("us-central1-")
        # But a town that configured a region keeps it.
        url = V.endpoint_for("mistral-small-2503", "town-311", "europe-west4")
        assert host_of(url).startswith("europe-west4-")

    def test_every_request_goes_to_google(self):
        """The host is asserted rather than searched for. A model id is
        town-supplied, and it is interpolated into this URL."""
        for model in ("gemini-3.5-flash", "claude-sonnet-4",
                      "llama-3.3-70b-instruct-maas", "mistral-small-2503"):
            for location in ("", "global", "europe-west4"):
                host = host_of(V.endpoint_for(model, "p", location))
                assert VERTEX_HOST.match(host), host

    def test_a_configured_region_is_honoured(self):
        """PR #433 hardcoded us-central1 and dropped VERTEX_AI_LOCATION, which
        is the wrong direction for a product sold on compliance boundaries."""
        assert host_of(V.endpoint_for("gemini-3.5-flash", "p", "europe-west4")).startswith("europe-west4-")
        assert host_of(V.endpoint_for("claude-sonnet-4", "p", "us-east5")).startswith("us-east5-")

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

    def test_maas_gets_the_openai_shape_with_a_qualified_model_field(self):
        """The endpoint URL names no model, so the body must -- and Vertex
        resolves the publisher from it, so the bare id alone is a 404."""
        body = V.build_payload("llama-3.3-70b-instruct-maas", "describe this")
        assert body["model"] == "meta/llama-3.3-70b-instruct-maas"
        assert body["messages"] == [{"role": "user", "content": "describe this"}]
        assert body["max_tokens"] > 0
        assert "contents" not in body and "anthropic_version" not in body
        # An already-qualified id is not qualified twice.
        body = V.build_payload("mistralai/mistral-small-2503", "x")
        assert body["model"] == "mistralai/mistral-small-2503"

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
        m = V.build_payload("llama-3.3-70b-instruct-maas", "x", img)
        part = m["messages"][0]["content"][0]
        assert part == {"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,AAA"}}

    def test_the_prompt_comes_last_so_images_precede_it(self):
        img = [{"mime_type": "image/png", "data": "B"}]
        for model in ("gemini-3.5-flash", "claude-sonnet-4",
                      "llama-3.3-70b-instruct-maas"):
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

    def test_maas_string_content_is_the_answer(self):
        result = {"choices": [{"message": {"role": "assistant",
                                           "content": '{"priority_score": 5}'}}]}
        assert V.extract_text("llama-3.3-70b-instruct-maas", result) == '{"priority_score": 5}'

    def test_maas_list_content_is_joined(self):
        """OpenAI's spec allows content as typed parts; a served model choosing
        that form must not read as an empty answer."""
        result = {"choices": [{"message": {"content": [
            {"type": "text", "text": '{"a":'},
            {"type": "image_url", "image_url": {"url": "data:x"}},
            {"type": "text", "text": " 1}"},
        ]}}]}
        assert V.extract_text("mistral-small-2503", result) == '{"a": 1}'

    def test_an_empty_response_is_empty_rather_than_an_error(self):
        for model in ("gemini-3.5-flash", "claude-sonnet-4",
                      "llama-3.3-70b-instruct-maas"):
            assert V.extract_text(model, {}) == ""
        # Defensive against half-shaped responses too, not just empty ones.
        assert V.extract_text("llama-3.3-70b-instruct-maas",
                              {"choices": [{}]}) == ""
        assert V.extract_text("llama-3.3-70b-instruct-maas",
                              {"choices": [{"message": {"content": None}}]}) == ""


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
        for unsupported in ('"cohere"', '"ai21"', '"writer"', '"xai"'):
            assert unsupported not in src, f"{unsupported} is offered without a handler"

    def test_vertex_skips_meta_cards_with_no_serving_endpoint(self):
        """Meta's publisher listing is mostly self-deploy Model Garden cards
        (faster-r-cnn, roberta, bare llama2/3/4, llama-guard) with nothing
        behind them for this caller; only `-maas` ids answer the MaaS
        endpoint, so only those may reach the picker."""
        src = _source("app/services/ai/model_discovery.py")
        assert '-maas' in src
        assert '"-self-deploy"' in src and '"ocr"' in src

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
