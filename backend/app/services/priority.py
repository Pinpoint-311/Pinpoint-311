"""One definition of a report's priority, used everywhere it leaves the app.

The staff screens and the printed work order show the staff-set priority, else
the AI's suggested score, else 5. The connector payload and the research export
read ServiceRequest.priority instead -- a column nothing writes, so it was 5 on
every report and a vendor's work order disagreed with the sheet the crew held.
"""
from typing import Any

DEFAULT_PRIORITY = 5


def effective_priority(sr: Any) -> float:
    manual = getattr(sr, "manual_priority_score", None)
    if manual is not None:
        return manual
    ai = getattr(sr, "ai_analysis", None) or {}
    score = ai.get("priority_score") if isinstance(ai, dict) else None
    if isinstance(score, (int, float)):
        return score
    return DEFAULT_PRIORITY


def priority_fields(sr: Any) -> dict:
    """The priority as one value plus where it came from, for anything that
    describes a report to a reader (the analytics advisor's context).

    `ai_suggested_priority` is included only when staff overrode the AI, so a
    reader is never handed two unlabelled numbers for the same report.
    """
    manual = getattr(sr, "manual_priority_score", None)
    ai = getattr(sr, "ai_analysis", None) or {}
    ai_score = ai.get("priority_score") if isinstance(ai, dict) else None
    if not isinstance(ai_score, (int, float)):
        ai_score = None
    out = {"priority": effective_priority(sr)}
    if manual is not None:
        out["priority_set_by"] = "staff"
        if ai_score is not None and ai_score != manual:
            out["ai_suggested_priority"] = ai_score
    elif ai_score is not None:
        out["priority_set_by"] = "ai"
    else:
        out["priority_set_by"] = "default"
    return out
