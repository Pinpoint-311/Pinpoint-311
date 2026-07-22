"""Content moderation of public inputs.

Text screening uses the open-source better-profanity library for the broad
profanity list, plus a small severe gate (slurs/explicit) that decides what is
*blocked* at submission vs merely flagged. Severe/block behavior is
library-independent and always tested; mild-profanity detection is guarded on
better-profanity being installed (it is in CI/prod via requirements.txt).
"""
import importlib

import pytest

cm = importlib.import_module("app.services.content_moderation")


# ---- severe gate: explicit/abusive -> blocked (library-independent) ----

def test_clean_text_passes():
    r = cm.scan_text("There is a large pothole on Main Street near the school.")
    assert r.flagged is False
    assert r.should_block is False


def test_empty_is_safe():
    assert cm.scan_text("").should_block is False
    assert cm.scan_text("   ").flagged is False
    assert cm.scan_text(None).flagged is False  # type: ignore[arg-type]


def test_explicit_slur_is_severe_and_blocked():
    r = cm.scan_text("you are a stupid cunt")
    assert r.severity == "severe"
    assert r.should_block is True
    assert "explicit" in r.categories


def test_severe_phrase_blocked():
    assert cm.scan_text("this is child porn").should_block is True


def test_severe_leetspeak_and_spacing_blocked():
    assert cm.scan_text("selling p0rn here").should_block is True     # leet 0->o
    assert cm.scan_text("p o r n site").should_block is True          # spaced out


def test_scunthorpe_and_legit_words_not_blocked():
    for clean in ["I live in Scunthorpe", "assessment of the class schedule",
                  "grass and shrubs on the assassin classic route"]:
        assert cm.scan_text(clean).should_block is False, clean


# ---- mild profanity: flagged, NOT blocked (needs better-profanity) ----

def test_mild_profanity_flagged_not_blocked():
    pytest.importorskip("better_profanity")
    r = cm.scan_text("this damn pothole is bullshit")
    assert r.flagged is True
    assert r.severity == "mild"
    assert r.should_block is False   # legitimate report stays submittable


# ---- AI image/text assessment fold-in (image moderation path) ----

def test_ai_photo_full_block_is_severe():
    r = cm.flags_from_ai_assessment({"photo_assessment": {"blocking_severity": "full_block"}})
    assert r.flagged is True and r.severity == "severe"


def test_ai_inappropriate_flag_is_severe():
    r = cm.flags_from_ai_assessment({"content_flags": ["inappropriate_content"]})
    assert r.flagged is True and r.severity == "severe"


def test_ai_clean_is_unflagged():
    assert cm.flags_from_ai_assessment({}).flagged is False
    assert cm.flags_from_ai_assessment({"content_flags": ["none"]}).flagged is False
    assert cm.flags_from_ai_assessment(None).flagged is False  # type: ignore[arg-type]
