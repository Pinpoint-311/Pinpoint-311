"""Content moderation for public inputs (resident descriptions & comments).

Text screening uses the open-source **better-profanity** library (MIT) for the
broad profanity wordlist + obfuscation handling, rather than a hand-maintained
list. On top of it we keep a small, explicit "severe" gate (slurs + sexual
content) that decides what is *blocked* at submission vs merely flagged:

  * severe (explicit/abusive)  -> submission is BLOCKED (HTTP 400);
  * mild profanity             -> allowed, but the request is flagged for staff.

This split (chosen deliberately) blocks abusive/explicit material while still
accepting legitimate — if crude — 311 reports, which a public service must.

Image moderation is handled by the AI photo assessment
(flags_from_ai_assessment, folded in during analyze_request) when an AI
provider is configured. Text is always screened, with or without AI.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)

# Load better-profanity once. If it isn't installed we degrade to the severe
# gate only (still blocks the worst content) rather than crashing intake.
try:
    from better_profanity import profanity as _bp
    _bp.load_censor_words()
    _BP_AVAILABLE = True
except Exception:  # pragma: no cover - only when the dep is missing
    _bp = None
    _BP_AVAILABLE = False
    logger.warning("[Moderation] better-profanity unavailable; using severe-gate only")

# Compact, unambiguous "severe" set — the block gate. These are slurs and
# sexually explicit terms that should never post to a public municipal feed.
# Deliberately small and auditable; better-profanity handles the broad list.
_SEVERE = {
    "cunt", "nigger", "nigga", "faggot", "fag", "chink", "spic", "kike",
    "cocksucker", "motherfucker", "whore", "rapist", "pedophile",
    "porn", "pornography", "blowjob", "handjob", "cumshot", "childporn",
}
_SEVERE_PHRASES = {"child porn"}

_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def _collapse(text: str, n: int) -> str:
    return re.sub(r"(.)\1{2,}", r"\1" * n, text)


def _tokens(s: str) -> set:
    words = set(re.findall(r"[a-z]+", s))
    despaced = re.sub(r"\b(?:[a-z]\s){2,}[a-z]\b", lambda m: m.group(0).replace(" ", ""), s)
    words |= set(re.findall(r"[a-z]+", despaced))
    return words


@dataclass
class ModerationResult:
    flagged: bool = False
    severity: str = "none"            # none | mild | severe
    categories: List[str] = field(default_factory=list)
    terms: List[str] = field(default_factory=list)

    @property
    def should_block(self) -> bool:
        """Severe content is rejected at submission (HTTP 400)."""
        return self.severity == "severe"

    @property
    def should_withhold(self) -> bool:
        return self.severity == "severe"

    def reason(self) -> str:
        if not self.flagged:
            return ""
        kind = "explicit/abusive language" if self.severity == "severe" else "profanity"
        shown = ", ".join(sorted(set(self.terms))[:5])
        return f"Auto-flagged: {kind}" + (f" ({shown})" if shown else "")


def scan_text(text: str) -> ModerationResult:
    """Screen a free-text public input. Never raises (fails open)."""
    if not text or not text.strip():
        return ModerationResult()
    try:
        base = text.lower().translate(_LEET)
        # two collapse forms so stretched profanity matches while legit double
        # letters ("ass", "class") survive
        words = _tokens(_collapse(base, 2)) | _tokens(_collapse(base, 1))
        severe_hits = sorted((words & _SEVERE) | {p for p in _SEVERE_PHRASES if p in base})
        if severe_hits:
            return ModerationResult(True, "severe", ["explicit"], severe_hits)
        if _BP_AVAILABLE and _bp is not None and _bp.contains_profanity(text):
            return ModerationResult(True, "mild", ["profanity"], [])
        return ModerationResult()
    except Exception:
        logger.warning("[Moderation] text scan error", exc_info=True)
        return ModerationResult()


_SEVERITY_RANK = {"none": 0, "mild": 1, "severe": 2}


def _stronger(a: ModerationResult, b: ModerationResult) -> ModerationResult:
    """Return the higher-severity of two results (merging their term lists)."""
    if _SEVERITY_RANK[b.severity] > _SEVERITY_RANK[a.severity]:
        hi, lo = b, a
    else:
        hi, lo = a, b
    if not hi.flagged:
        return ModerationResult()
    return ModerationResult(True, hi.severity,
                            sorted(set(hi.categories) | set(lo.categories)),
                            sorted(set(hi.terms) | set(lo.terms)))


async def screen_text(text: str) -> ModerationResult:
    """Always-on better-profanity scan, plus the cloud text moderator layered on
    top when configured (catches contextual toxicity/threats a wordlist misses).
    Returns the stronger verdict; cloud failures fall back to the local scan."""
    base = scan_text(text)
    try:
        from app.services import cloud_moderation
        cloud = await cloud_moderation.moderate_text(text)
    except Exception:
        cloud = None
    return _stronger(base, cloud) if cloud else base


async def screen_images(media: list) -> ModerationResult:
    """Cloud image moderation (when configured). Unflagged result otherwise —
    externally-hosted images and the no-cloud case fall back to the AI vision
    assessment applied later in analyze_request."""
    if not media:
        return ModerationResult()
    try:
        from app.services import cloud_moderation
        return await cloud_moderation.moderate_images(media)
    except Exception:
        return ModerationResult()


def flags_from_ai_assessment(ai_analysis: dict) -> ModerationResult:
    """Fold the AI photo/text assessment into the same moderation shape so
    images (and AI-detected text abuse) flag consistently. Unflagged when AI
    didn't run or found nothing."""
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
