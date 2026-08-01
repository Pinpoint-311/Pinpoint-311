"""Vertex serves more than Gemini, and each publisher speaks differently.

Model Garden offers Anthropic, Meta, Mistral and others alongside Google's own
models, and a town on Vertex should be able to pick them. They are not
interchangeable at the wire, though: Gemini takes `:generateContent` with
`contents`/`parts`, Anthropic takes `:rawPredict` with an Anthropic-shaped body
and its own `anthropic_version`, and the responses come back in different
shapes too.

The rule this module exists to enforce: **only offer what we can call.**

Listing every publisher in the picker while the caller only speaks Gemini gives
a clerk a model they can select, save, and watch fail at triage time with a 404
-- the same silent-failure shape this console keeps being fixed for. So
discovery asks here which publishers are supported, and adding one means adding
a handler rather than adding a string to a list.

Pure: builds URLs and payloads and parses responses. No network, no
credentials, so all of it runs in CI.
"""

from typing import Any, Dict, List, Optional, Tuple

GOOGLE = "google"
ANTHROPIC = "anthropic"

# Publishers with a request/response handler below. Meta, Mistral, AI21, Cohere
# and xAI are real on Vertex and deliberately absent: they are served through
# the OpenAI-compatible MaaS endpoint, which is a third shape, and listing them
# before that shape is implemented and tested would be offering models that
# cannot be called.
SUPPORTED_PUBLISHERS: Tuple[str, ...] = (GOOGLE, ANTHROPIC)

# How a model id announces its publisher.
#
# Vertex does not return the publisher alongside the id in a form that survives
# being stored as a single `AI_MODEL` string, so it is inferred from the id --
# `gemini-3.5-flash` is Google's, `claude-sonnet-4@20250514` is Anthropic's.
# Unknown prefixes fall back to Google, which is where every id came from
# before this existed.
_PREFIXES = {
    "gemini": GOOGLE,
    "gemma": GOOGLE,
    "medlm": GOOGLE,
    "claude": ANTHROPIC,
}


def publisher_for(model_id: Optional[str]) -> str:
    name = (model_id or "").strip().lower().lstrip("/")
    # An explicitly qualified id wins over the prefix guess.
    if "/" in name:
        head = name.split("/", 1)[0]
        if head in SUPPORTED_PUBLISHERS:
            return head
    for prefix, publisher in _PREFIXES.items():
        if name.startswith(prefix):
            return publisher
    return GOOGLE


def bare_model_id(model_id: str) -> str:
    """`anthropic/claude-x` -> `claude-x`. The URL carries the publisher."""
    return model_id.split("/", 1)[1] if "/" in model_id else model_id


def is_supported(model_id: Optional[str]) -> bool:
    return publisher_for(model_id) in SUPPORTED_PUBLISHERS


def endpoint_for(model_id: str, project: str, location: str = "global") -> str:
    """Where to POST.

    Anthropic models are not served from the `global` endpoint, so a request
    built for `global` fails with a 404 that reads like a wrong model name. The
    location falls back to a real region for those.
    """
    publisher = publisher_for(model_id)
    model = bare_model_id(model_id)
    if publisher == ANTHROPIC:
        region = location if location and location != "global" else "us-east5"
        host = f"{region}-aiplatform.googleapis.com"
        return (f"https://{host}/v1/projects/{project}/locations/{region}"
                f"/publishers/anthropic/models/{model}:rawPredict")
    host = "aiplatform.googleapis.com" if location in ("", "global", None) else f"{location}-aiplatform.googleapis.com"
    loc = location or "global"
    return (f"https://{host}/v1/projects/{project}/locations/{loc}"
            f"/publishers/google/models/{model}:generateContent")


def _image_parts_google(images: Optional[List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    return [{"inline_data": {"mime_type": i["mime_type"], "data": i["data"]}} for i in images or []]


def _image_parts_anthropic(images: Optional[List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    return [{"type": "image", "source": {"type": "base64",
                                         "media_type": i["mime_type"], "data": i["data"]}}
            for i in images or []]


def build_payload(model_id: str, prompt: str,
                  images: Optional[List[Dict[str, str]]] = None,
                  max_tokens: int = 4096) -> Dict[str, Any]:
    """The body each publisher expects. Same prompt, different envelope."""
    if publisher_for(model_id) == ANTHROPIC:
        content: List[Dict[str, Any]] = _image_parts_anthropic(images)
        content.append({"type": "text", "text": prompt})
        return {
            # Required by Vertex's Anthropic endpoint, and not the model
            # version -- it is the shape of the request.
            "anthropic_version": "vertex-2023-10-16",
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
    parts: List[Dict[str, Any]] = _image_parts_google(images)
    parts.append({"text": prompt})
    return {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.8,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"includeThoughts": True, "thinkingLevel": "HIGH"},
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"} for c in (
                "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT",
            )
        ],
    }


def extract_text(model_id: str, result: Dict[str, Any]) -> str:
    """Pull the answer out, whatever shape it arrived in."""
    if publisher_for(model_id) == ANTHROPIC:
        return "".join(
            block.get("text", "")
            for block in (result.get("content") or [])
            if block.get("type") == "text"
        )
    text = ""
    for candidate in (result.get("candidates") or [])[:1]:
        for part in candidate.get("content", {}).get("parts", []):
            # Skip "thought" parts -- only the answer carries the JSON.
            if "text" in part and not part.get("thought"):
                text += part["text"]
    return text
