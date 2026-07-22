"""Content moderation for public inputs (resident descriptions & comments).

Deterministic and always-on: a wordlist scanner that needs no network and no
AI, so moderation works even when every optional provider is down. It does NOT
hard-block submissions — a 311 report full of angry (even profane) language is
still a legitimate report a town must receive. Instead it *flags* content for
staff review and classifies severity, so:

  * "severe" (explicit sexual content, slurs) → the request/comment is flagged
    and can be withheld from the public feed pending review;
  * "mild" (common profanity) → flagged for staff awareness only.

Image moderation is handled separately by the AI photo assessment
(content_flags / blocking_severity in analyze_request) when an AI provider is
configured; this module covers text, which must always be screened.
"""

import re
from dataclasses import dataclass, field
from typing import List

# Severe: explicit sexual terms and hate slurs — content that should be withheld
# from a public municipal feed pending review. Kept deliberately compact and
# unambiguous to minimize false positives.
_SEVERE = {
    "cunt", "nigger", "nigga", "faggot", "fag", "chink", "spic", "kike",
    "retard", "cocksucker", "motherfucker", "whore", "slut", "rapist",
    "pedophile", "child porn", "cp", "porn", "pornography", "blowjob",
    "handjob", "cumshot", "dickhead",
}
# Mild: common profanity — flag for staff awareness, don't withhold.
_MILD = {
    "fuck", "fucking", "fucker", "shit", "bullshit", "shitty", "ass",
    "asshole", "bastard", "bitch", "damn", "goddamn", "crap", "piss",
    "dick", "cock", "pussy", "prick", "bollocks", "wanker", "twat",
}

# Multi-word phrases we still want to catch (checked on the normalized string).
_SEVERE_PHRASES = {"child porn"}

# Leetspeak / obfuscation normalization so "sh1t" / "f u c k" / "a$$" still hit.
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def _collapse(text: str, n: int) -> str:
    # collapse runs of 3+ identical letters down to n copies
    return re.sub(r"(.)\1{2,}", r"\1" * n, text)


def _tokens(normalized: str) -> List[str]:
    # split on non-letters, and also a spaced-out form ("f u c k" -> "fuck")
    words = re.findall(r"[a-z]+", normalized)
    despaced = re.sub(r"\b(?:[a-z]\s){2,}[a-z]\b", lambda m: m.group(0).replace(" ", ""), normalized)
    words += re.findall(r"[a-z]+", despaced)
    return words


@dataclass
class ModerationResult:
    flagged: bool = False
    severity: str = "none"            # none | mild | severe
    categories: List[str] = field(default_factory=list)  # e.g. ["profanity", "explicit"]
    terms: List[str] = field(default_factory=list)        # matched terms (for the staff note)

    @property
    def should_withhold(self) -> bool:
        """Severe content is withheld from the public feed pending staff review."""
        return self.severity == "severe"

    def reason(self) -> str:
        if not self.flagged:
            return ""
        kind = "explicit/abusive language" if self.severity == "severe" else "profanity"
        shown = ", ".join(sorted(set(self.terms))[:5])
        return f"Auto-flagged: {kind}" + (f" ({shown})" if shown else "")


def scan_text(text: str) -> ModerationResult:
    """Screen a free-text public input. Returns a ModerationResult; never raises."""
    if not text or not text.strip():
        return ModerationResult()
    try:
        base = text.lower().translate(_LEET)
        # Two collapse forms so stretched profanity ("fuuuuck") matches while
        # legit double letters ("ass", "class") are preserved: 3+ runs -> 2 and 3+ -> 1.
        words = set(_tokens(_collapse(base, 2))) | set(_tokens(_collapse(base, 1)))
        severe_hits = sorted((words & _SEVERE) | {p for p in _SEVERE_PHRASES if p in base})
        mild_hits = sorted(words & _MILD)
        if severe_hits:
            cats = ["explicit"]
            if mild_hits:
                cats.append("profanity")
            return ModerationResult(True, "severe", cats, severe_hits + mild_hits)
        if mild_hits:
            return ModerationResult(True, "mild", ["profanity"], mild_hits)
        return ModerationResult()
    except Exception:
        # Moderation must never break intake — fail open (unflagged) on error.
        return ModerationResult()


def flags_from_ai_assessment(ai_analysis: dict) -> ModerationResult:
    """Fold the AI photo/text assessment (when an AI provider ran) into the same
    moderation shape, so images and AI-detected text abuse flag consistently.
    Returns an unflagged result when AI didn't run or found nothing."""
    if not isinstance(ai_analysis, dict):
        return ModerationResult()
    photo = ai_analysis.get("photo_assessment") or {}
    content_flags = [str(f).lower() for f in (ai_analysis.get("content_flags") or [])]
    bad = {"inappropriate_content", "malicious_intent", "obscene_language"}
    hit_flags = [f for f in content_flags if f in bad]
    severe = photo.get("blocking_severity") == "full_block" or "inappropriate_content" in hit_flags
    if severe:
        return ModerationResult(True, "severe", ["ai_image_or_text"], hit_flags or ["photo_full_block"])
    if hit_flags:
        return ModerationResult(True, "mild", ["ai_image_or_text"], hit_flags)
    return ModerationResult()
