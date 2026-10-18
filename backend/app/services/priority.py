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
