"""What a retention run removes, and what it is honest to call that.

Two things were wrong with the old behaviour beyond the AI leak.

The list was fixed in code. A town's retention obligations are set by its own
counsel and its state's records law, and this decided for them: names, email,
phone, description, staff notes and photos, always, with no say. A town that
must keep descriptions for a public-records index had no way to say so, and one
that must also remove resident comments had no way to ask.

And it was called anonymisation. Anonymising means removing what ties data to a
person. Blanking the description of a pothole report is not that -- it is
redaction, and the two are not interchangeable words when the difference is
what a town tells a judge. The mode is `redact` now; `anonymize` is still
accepted on the way in, because it is written in databases that already exist.

Pure, and free of SQLAlchemy, so CI runs it. The comment tables are handled by
the caller, which needs a session; everything decidable without one is here.
"""

from typing import Any, Dict, Iterable, List, Optional, Set

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

REDACT = "redact"
PURGE = "purge"

# Hard deletion is gone, and this is why.
#
# `delete` called `db.delete(record)` while `request_audit_logs` and
# `request_comments` hold NOT NULL foreign keys back to it with no cascade, so
# SQLAlchemy tried to disown the children and the flush failed -- on every
# record, because submitting one writes an audit entry. Each failure was caught
# per record and the run reported success with nothing archived. A town on a
# delete policy was told retention was running and nothing was ever removed.
#
# Making it succeed meant deleting the audit rows, and those are a hash chain
# the compliance page advertises as tamper-evident. Removing rows from the
# middle makes the verify endpoint report tampering -- correctly -- for a
# deletion that was entirely legitimate.
#
# So the strongest mode clears every field instead. The row survives as a shell
# that still counts in statistics, the personal data is gone, and the audit
# chain stays whole and honest.
MODES = (REDACT, PURGE)

# What towns already have stored. Read, never written.
LEGACY_MODES = {"anonymize": REDACT, "delete": PURGE}


def normalise_mode(mode: Optional[str]) -> str:
    """Accept what is in the database, return what things are now called."""
    if not mode:
        return REDACT
    mode = str(mode).strip().lower()
    return LEGACY_MODES.get(mode, mode)


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------
#
# Nothing is pre-ticked, and that is the whole point of the list.
#
# Seven of these used to arrive selected, because they were what the old
# hard-coded list removed. Inherited that way they were never anybody's
# decision -- and the decision they stood in for is which of a resident's
# details this town destroys, permanently, on a schedule. A default that
# destroys is not a convenience.
#
# The town ticks what its own records schedule says to remove. Until it ticks
# something, retention does not run at all; see retention_config.

SCRUB_FIELDS: List[Dict[str, Any]] = [
    {
        "id": "name",
        "label": "Reporter's name",
        "detail": "First and last name are replaced with [ARCHIVED].",
    },
    {
        "id": "email",
        "label": "Reporter's email address",
        "detail": "Replaced with a placeholder that cannot receive mail.",
    },
    {
        "id": "phone",
        "label": "Reporter's phone number",
        "detail": "Removed.",
    },
    {
        "id": "description",
        "label": "What the resident wrote",
        "detail": "The free-text description. Residents often put names, phone "
                  "numbers and neighbours' details in here.",
    },
    {
        "id": "custom_fields",
        "label": "Answers to the town's own questions",
        "detail": "Whatever residents typed into the follow-up questions this "
                  "town added. Free text, so it holds the same names, phone "
                  "numbers and neighbours' details the description does -- and "
                  "it was invisible to retention entirely until recently, so on "
                  "older records it outlived every other field.",
    },
    {
        "id": "staff_notes",
        "label": "Internal staff notes",
        "detail": "Notes staff added to the request.",
    },
    {
        "id": "media",
        "label": "Photos",
        "detail": "Photo links are cleared. The files themselves are removed by "
                  "the storage cleanup that follows.",
    },
    {
        "id": "ai_analysis",
        "label": "AI analysis and summary",
        "detail": "The model's writing about the report, which quotes it. The "
                  "category and priority score are kept so the record still counts.",
    },
    {
        "id": "comments",
        "label": "Comments on the request",
        "detail": "Both resident and staff comments.",
    },
    {
        "id": "address",
        "label": "Street address",
        "detail": "The address text. The map pin is a separate choice below.",
    },
    {
        "id": "coordinates",
        "label": "Map location",
        "detail": "Removes the pin entirely. The request disappears from maps "
                  "and from anything counted by area.",
    },
]

FIELD_IDS: Set[str] = {f["id"] for f in SCRUB_FIELDS}
FIELD_IDS_ORDERED: List[str] = [f["id"] for f in SCRUB_FIELDS]

# Keys in `ai_analysis` that hold no resident text.
#
# An allow-list rather than a list of things to strip, because the failure
# directions are not symmetric: a new key nobody remembers to add here is
# dropped from an archived record, which costs a statistic. A new key nobody
# remembers to add to a strip-list is retained forever, which is the thing the
# retention policy exists to prevent.
AI_ANALYSIS_KEEP = frozenset({
    "priority_score",
    "quantitative_metrics",
    "recommended_response_time",
})


def normalise_fields(fields: Optional[Iterable[str]]) -> List[str]:
    """Validate a stored or submitted selection.

    `None` means "never configured" and returns nothing, because there is
    nothing to return: the list of things a run destroys is the town's to write
    and there is no version of it we can supply. It used to fall back to a set
    of seven, which is how towns ended up with a destruction policy nobody
    chose. Callers read an empty result as "not configured yet" and decline to
    run -- see retention_config -- rather than as "redact nothing".
    """
    if fields is None:
        return []
    return [f for f in dict.fromkeys(fields) if f in FIELD_IDS]


def scrub_ai_analysis(record: Any) -> None:
    """Take the model's writing about a report out with the report.

    The summary is the description in different words, and where a resident put
    their name or a phone number in the description the model repeated it.
    `priority_justification` and `qualitative_analysis` quote the report;
    `_error` carries whatever the provider said, which has included the prompt.
    """
    analysis = getattr(record, "ai_analysis", None)
    if isinstance(analysis, dict):
        record.ai_analysis = {k: v for k, v in analysis.items() if k in AI_ANALYSIS_KEEP}
    elif analysis is not None:
        # Not a dict, so nothing inside it can be judged safe.
        record.ai_analysis = None
    # The legacy name is still listed so this keeps working against an ORM
    # object from a deployment that has not run the rename migration yet.
    for attr in ("ai_summary", "vertex_ai_summary"):
        if hasattr(record, attr):
            setattr(record, attr, None)


def fields_for_mode(mode: Optional[str], fields: Optional[Iterable[str]] = None) -> List[str]:
    """Purge means everything. Redact means what the town chose.

    One place to ask, so a caller cannot apply a purge with a redact-sized list
    and report it as a purge.
    """
    if normalise_mode(mode) == PURGE:
        return list(FIELD_IDS_ORDERED)
    return normalise_fields(fields)


def apply_scrub(record: Any, fields: Optional[Iterable[str]] = None) -> List[str]:
    """Clear the chosen fields on one record. Returns what was actually cleared.

    Only the fields asked for. The temptation is to remove "a bit more, to be
    safe", and that is how a town loses the public-records index it is legally
    obliged to keep.
    """
    chosen = set(normalise_fields(fields))
    done: List[str] = []

    if "name" in chosen:
        record.first_name = "[ARCHIVED]"
        record.last_name = "[ARCHIVED]"
        done.append("name")
    if "email" in chosen:
        record.email = f"archived-{getattr(record, 'id', 0)}@retention.local"
        done.append("email")
    if "phone" in chosen:
        record.phone = None
        done.append("phone")
    if "description" in chosen:
        record.description = "[Content archived per retention policy]"
        done.append("description")
    if "custom_fields" in chosen:
        # Emptied rather than set to None: the column is JSON and downstream
        # readers (the work order, the Open311 payload) do `if custom_fields`,
        # which an empty dict answers the same way a null does -- while keeping
        # the column's type honest for anything that reads it as a mapping.
        record.custom_fields = {}
        done.append("custom_fields")
    if "staff_notes" in chosen:
        record.staff_notes = None
        done.append("staff_notes")
    if "media" in chosen:
        record.media_urls = []
        done.append("media")
    if "ai_analysis" in chosen:
        scrub_ai_analysis(record)
        done.append("ai_analysis")
    if "address" in chosen:
        record.address = None
        done.append("address")
    if "coordinates" in chosen:
        record.lat = None
        record.long = None
        # PostGIS geometry, kept in step with the columns beside it.
        if hasattr(record, "location"):
            record.location = None
        done.append("coordinates")

    # `comments` is deliberately absent: they live in another table and need a
    # session. The caller handles it, and `describe_selection` still lists it so
    # the admin sees one coherent choice.
    return done


def describe_selection(fields: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """The catalog with the current choice marked, for the settings screen.

    A town that has chosen nothing gets every box unticked, which is the
    accurate picture of a policy that has not been written yet.
    """
    chosen = set(normalise_fields(fields))
    return [{**f, "selected": f["id"] in chosen} for f in SCRUB_FIELDS]
