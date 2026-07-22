"""Cloud moderation: severity mappers (pure) + local/cloud merge.

The network/boto calls are not exercised (no live cloud); we test the pure
response->severity mappers for each provider and that the combined screen_text
layers the cloud verdict on top of better-profanity, taking the stronger one.
"""
import importlib

import pytest

cmod = importlib.import_module("app.services.cloud_moderation")
cm = importlib.import_module("app.services.content_moderation")


# ------------------------------ Azure ------------------------------

def test_azure_severe_and_mild():
    severe = cmod.azure_severity([{"category": "Sexual", "severity": 6}])
    assert severe.severity == "severe" and severe.should_block

    mild = cmod.azure_severity([{"category": "Hate", "severity": 2}])
    assert mild.severity == "mild" and not mild.should_block

    clean = cmod.azure_severity([{"category": "Violence", "severity": 0}])
    assert clean.flagged is False


# ------------------------------ Google -----------------------------

def test_google_safesearch_levels():
    assert cmod.google_safesearch_severity({"adult": "VERY_LIKELY"}).should_block is True
    assert cmod.google_safesearch_severity({"adult": "POSSIBLE"}).severity == "mild"
    assert cmod.google_safesearch_severity({"adult": "VERY_UNLIKELY", "racy": "UNLIKELY"}).flagged is False


def test_google_text_confidence():
    assert cmod.google_text_severity([{"name": "Toxic", "confidence": 0.92}]).should_block is True
    assert cmod.google_text_severity([{"name": "Insult", "confidence": 0.6}]).severity == "mild"
    assert cmod.google_text_severity([{"name": "Health", "confidence": 0.99}]).flagged is False


# ------------------------------ AWS --------------------------------

def test_rekognition_confidence():
    assert cmod.rekognition_severity([{"Name": "Explicit Nudity", "Confidence": 95}]).should_block is True
    assert cmod.rekognition_severity([{"Name": "Violence", "Confidence": 60}]).severity == "mild"
    assert cmod.rekognition_severity([{"Name": "Suggestive", "Confidence": 95}]).flagged is False


def test_comprehend_toxicity_and_labels():
    assert cmod.comprehend_severity({"ResultList": [{"Toxicity": 0.9}]}).should_block is True
    assert cmod.comprehend_severity(
        {"ResultList": [{"Labels": [{"Name": "HATE_SPEECH", "Score": 0.6}]}]}).severity == "mild"
    assert cmod.comprehend_severity({"ResultList": [{"Toxicity": 0.1}]}).flagged is False


# ------------------------------ image byte decode ------------------

def test_to_bytes_handles_data_uri_and_skips_urls():
    import base64
    raw = base64.b64encode(b"hello").decode()
    assert cmod._to_bytes(f"data:image/png;base64,{raw}") == b"hello"
    assert cmod._to_bytes(raw) == b"hello"
    assert cmod._to_bytes("https://example.gov/pic.jpg") is None  # not fetched (SSRF)
    assert cmod._to_bytes("") is None


# ------------------------------ merge policy -----------------------

async def test_screen_text_layers_cloud_on_top(monkeypatch):
    # better-profanity may be absent here; cloud says severe -> combined severe.
    async def _cloud_severe(text):
        return cm.ModerationResult(True, "severe", ["cloud:azure"], ["Sexual"])
    monkeypatch.setattr("app.services.cloud_moderation.moderate_text", _cloud_severe)
    out = await cm.screen_text("borderline text")
    assert out.severity == "severe" and out.should_block is True


async def test_screen_text_falls_back_when_cloud_unconfigured(monkeypatch):
    async def _none(text):
        return None
    monkeypatch.setattr("app.services.cloud_moderation.moderate_text", _none)
    # severe local term still blocks without any cloud provider
    out = await cm.screen_text("you absolute cunt")
    assert out.should_block is True


async def test_screen_text_cloud_error_falls_back(monkeypatch):
    async def _boom(text):
        raise RuntimeError("content safety 500")
    monkeypatch.setattr("app.services.cloud_moderation.moderate_text", _boom)
    out = await cm.screen_text("a normal pothole report")   # clean, no exception
    assert out.flagged is False
