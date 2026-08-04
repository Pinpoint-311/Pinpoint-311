"""What goes into a public-records response, chosen deliberately.

A records custodian answering a request under whatever law their state has is
doing something specific: releasing the records that were asked for, and not
the ones that were not. The export gave them one fixed set of ten columns and a
date range. So a request for "pothole complaints on Main Street in 2024" was
answered with every report the town has ever taken, and a request that should
have excluded staff notes could not exclude them.

It also printed a statute at the top of every file. The name came from a table
of public-records laws the product had assembled for all 51 US jurisdictions
and never verified, defaulting to "Federal FOIA" for anything unlisted — a
legal claim, on a document that leaves the building and gets filed by whoever
requested it. This module no longer names a law, because the town knows which
one it is answering under and we do not.

Over-disclosure is the failure mode that matters here. A custodian who releases
a resident's phone number in response to a request that did not ask for it
cannot take it back, and the person whose number it was never knew it was in
scope. So:

  * every field is opt-in by name, and the default set is the one a records
    request normally covers
  * the fields carrying personal information are marked, counted, and refused
    to anyone who is not an administrator
  * what was exported, by whom, and with which fields is written to the audit
    trail every time -- not only when PII is included

Pure: the catalog and the row builder take records and return rows, so the
selection rules are testable without a database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------
#
# `sensitive` means "identifies the person who reported it". Those are the
# fields a custodian usually redacts, so releasing them has to be a decision
# somebody made rather than a default they inherited.

FIELDS: List[Dict[str, Any]] = [
    {"id": "service_request_id", "label": "Request ID", "attr": "service_request_id",
     "default": True, "sensitive": False},
    {"id": "service_name", "label": "Service type", "attr": "service_name",
     "default": True, "sensitive": False},
    {"id": "status", "label": "Status", "attr": "status",
     "default": True, "sensitive": False},
    {"id": "requested_datetime", "label": "Submitted", "attr": "requested_datetime",
     "default": True, "sensitive": False},
    {"id": "closed_datetime", "label": "Closed", "attr": "closed_datetime",
     "default": True, "sensitive": False},
    {"id": "address", "label": "Address", "attr": "address",
     "default": True, "sensitive": False,
     "note": "The location reported. On a residential street this can identify a household."},
    {"id": "lat", "label": "Latitude", "attr": "lat", "default": False, "sensitive": False},
    {"id": "long", "label": "Longitude", "attr": "long", "default": False, "sensitive": False},
    {"id": "description", "label": "What was reported", "attr": "description",
     "default": True, "sensitive": False,
     "note": "Written by the resident, so it can name people even when the PII fields are off."},
    {"id": "custom_fields", "label": "Answers to the town's own questions", "attr": "custom_fields",
     "default": True, "sensitive": False,
     "note": "Written by the resident, like the description, so it can name people even "
             "when the PII fields are off. Omitting it made the export an incomplete "
             "answer to a records request."},
    {"id": "completion_message", "label": "Resolution", "attr": "completion_message",
     "default": True, "sensitive": False},
    {"id": "closed_substatus", "label": "Closure reason", "attr": "closed_substatus",
     "default": False, "sensitive": False},
    {"id": "assigned_department", "label": "Department", "attr": "_department",
     "default": False, "sensitive": False},
    {"id": "source", "label": "How it arrived", "attr": "source",
     "default": False, "sensitive": False},
    # Internal. Frequently exempt, and never a default.
    {"id": "staff_notes", "label": "Internal staff notes", "attr": "staff_notes",
     "default": False, "sensitive": False,
     "note": "Internal working notes. Usually exempt — include only if the request covers them."},
    {"id": "assigned_to", "label": "Assigned staff member", "attr": "assigned_to",
     "default": False, "sensitive": False},
    # Identifies the reporter.
    {"id": "first_name", "label": "Reporter first name", "attr": "first_name",
     "default": False, "sensitive": True},
    {"id": "last_name", "label": "Reporter last name", "attr": "last_name",
     "default": False, "sensitive": True},
    {"id": "email", "label": "Reporter email", "attr": "email",
     "default": False, "sensitive": True},
    {"id": "phone", "label": "Reporter phone", "attr": "phone",
     "default": False, "sensitive": True},
]

FIELD_IDS = [f["id"] for f in FIELDS]
DEFAULT_FIELDS = [f["id"] for f in FIELDS if f["default"]]
SENSITIVE_FIELDS = {f["id"] for f in FIELDS if f["sensitive"]}
_BY_ID = {f["id"]: f for f in FIELDS}


class UnknownField(ValueError):
    """A field id that is not in the catalog."""


def normalise_fields(requested: Optional[Sequence[str]]) -> List[str]:
    """Validate a selection and return it in catalog order.

    Unknown ids are refused rather than dropped. Silently ignoring one means a
    custodian who mistypes gets an export missing a column they believe is in
    it, and a public-records response is not a place to guess.

    An empty list is honoured as "no fields", which is a caller error the
    endpoint reports, rather than being quietly turned into the defaults.
    """
    if requested is None:
        return list(DEFAULT_FIELDS)
    unknown = [f for f in requested if f not in _BY_ID]
    if unknown:
        raise UnknownField(f"Unknown field(s): {', '.join(sorted(unknown))}")
    chosen = set(requested)
    return [f for f in FIELD_IDS if f in chosen]


def sensitive_selected(fields: Sequence[str]) -> List[str]:
    """Which of the chosen fields identify the reporter."""
    return [f for f in fields if f in SENSITIVE_FIELDS]


def describe_fields(selected: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """The catalog, with what is currently chosen, for the picker."""
    chosen = set(DEFAULT_FIELDS if selected is None else selected)
    return [
        {
            "id": f["id"],
            "label": f["label"],
            "sensitive": f["sensitive"],
            "selected": f["id"] in chosen,
            **({"note": f["note"]} if f.get("note") else {}),
        }
        for f in FIELDS
    ]


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def parse_boundary(value: Optional[str], *, end: bool = False) -> Optional[datetime]:
    """A date from a form, as an aware UTC instant.

    `datetime.fromisoformat("2024-01-01")` is naive, and comparing a naive
    value against a `timestamptz` column makes PostgreSQL interpret it in the
    session's timezone -- so the same export returns different records
    depending on a server setting nobody looked at. That is the bug that took
    the statistics page down, in a place where the consequence is a records
    response missing a day at either end.

    A bare date as `end` means the whole of that day, because "1 Jan to 31 Jan"
    from a custodian includes the 31st.
    """
    if not value:
        return None
    text = value.strip()
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end and len(text) <= 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


def _value(record: Any, field_id: str) -> Any:
    spec = _BY_ID[field_id]
    if spec["attr"] == "_department":
        dept = getattr(record, "assigned_department", None)
        return getattr(dept, "name", None) if dept else None
    value = getattr(record, spec["attr"], None)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, dict):
        # The custom answers are a JSON object. A records request goes to a
        # member of the public, so this has to be a sentence rather than a
        # Python dict repr with braces and quotes in a spreadsheet cell.
        return "; ".join(f"{k}: {_flatten(v)}" for k, v in value.items()) or None
    if isinstance(value, list):
        return "; ".join(str(v) for v in value) or None
    return value


def _flatten(value: Any) -> str:
    """One answer as text. Checkbox questions store a list."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def build_row(record: Any, fields: Sequence[str]) -> List[Any]:
    """One CSV row, in the order the header was written."""
    return [_value(record, f) for f in fields]


def headers(fields: Sequence[str]) -> List[str]:
    return [_BY_ID[f]["label"] for f in fields]


def preamble(*, total: int, exported_by: str, fields: Sequence[str],
             filters: Dict[str, Any], generated: datetime) -> List[str]:
    """The comment block at the top of the file.

    It records the shape of the request as well as the answer. A custodian
    producing this months later, to a requester who says it is incomplete,
    needs the file itself to say what was asked for -- which dates, which
    statuses, which fields, and which fields were deliberately left out.

    What it does not say is which statute the request was made under. It used
    to, from a table we had guessed at, so a town in Texas released files
    headed "OPRA EXPORT / State: New Jersey (NJ)". Every fact printed here is
    one this system actually knows.
    """
    included = ", ".join(_BY_ID[f]["label"] for f in fields)
    omitted = ", ".join(_BY_ID[f]["label"] for f in FIELD_IDS if f not in set(fields))
    lines = [
        "# RECORDS EXPORT",
        f"# Generated: {generated.isoformat()}",
        f"# Exported by: {exported_by}",
        f"# Total records: {total}",
        "#",
        f"# Fields included: {included}",
        f"# Fields omitted: {omitted or '(none)'}",
    ]
    for key in ("start_date", "end_date", "statuses", "service_codes", "request_ids"):
        value = filters.get(key)
        if value:
            shown = ", ".join(map(str, value)) if isinstance(value, (list, tuple)) else value
            lines.append(f"# Filter {key.replace('_', ' ')}: {shown}")
    if not any(filters.get(k) for k in ("start_date", "end_date", "statuses",
                                        "service_codes", "request_ids")):
        # Said explicitly. "Every record the town holds" should not be the
        # thing nobody realises they produced.
        lines.append("# Filter: none — this is every non-deleted record")
    lines.append("#")
    return lines
