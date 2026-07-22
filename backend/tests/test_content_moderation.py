"""Content moderation of public inputs — deterministic text scanner.

Verifies the always-on scanner that screens resident descriptions and comments
without needing AI or the network: clean text passes, profanity flags mild,
explicit/abusive flags severe (and is withheld from the public feed), and
obfuscation (leetspeak / spacing / stretching) is still caught. It must never
raise and never hard-block.
"""
import importlib

cm = importlib.import_module("app.services.content_moderation")


def test_clean_text_is_not_flagged():
    r = cm.scan_text("There is a large pothole on Main Street near the school.")
    assert r.flagged is False
    assert r.severity == "none"
    assert r.should_withhold is False
    assert r.reason() == ""


def test_empty_and_whitespace_safe():
    assert cm.scan_text("").flagged is False
    assert cm.scan_text("   \n ").flagged is False
    assert cm.scan_text(None).flagged is False  # type: ignore[arg-type]


def test_mild_profanity_flags_but_does_not_withhold():
    r = cm.scan_text("This damn pothole is shit and nobody fixes it")
    assert r.flagged is True
    assert r.severity == "mild"
    assert r.should_withhold is False       # legitimate (if crude) report — stays public
    assert "profanity" in r.categories
    assert r.reason().startswith("Auto-flagged: profanity")


def test_explicit_content_is_severe_and_withheld():
    r = cm.scan_text("you are a stupid cunt and I hope you suffer")
    assert r.flagged is True
    assert r.severity == "severe"
    assert r.should_withhold is True        # withheld from public feed pending review
    assert "explicit" in r.categories


def test_leetspeak_and_spacing_obfuscation_caught():
    assert cm.scan_text("what the f u c k").flagged is True
    assert cm.scan_text("this is sh1t").flagged is True
    assert cm.scan_text("total a$$hole behavior").flagged is True
    assert cm.scan_text("fuuuuck this").flagged is True


def test_scunthorpe_not_over_flagged():
    # word-boundary matching: legitimate words containing a substring don't trip
    for clean in ["I live in Scunthorpe", "assessment of the class schedule",
                  "the assassin classic", "grass and shrubs"]:
        assert cm.scan_text(clean).flagged is False, clean


# ---- AI assessment fold-in (image/text moderation via the vision model) ----

def test_ai_photo_full_block_is_severe():
    r = cm.flags_from_ai_assessment({"photo_assessment": {"blocking_severity": "full_block"}})
    assert r.flagged is True and r.severity == "severe"


def test_ai_content_flags_inappropriate_is_severe():
    r = cm.flags_from_ai_assessment({"content_flags": ["inappropriate_content"]})
    assert r.flagged is True and r.severity == "severe"


def test_ai_no_assessment_is_clean():
    assert cm.flags_from_ai_assessment({}).flagged is False
    assert cm.flags_from_ai_assessment({"content_flags": ["none"]}).flagged is False
    assert cm.flags_from_ai_assessment(None).flagged is False  # type: ignore[arg-type]
