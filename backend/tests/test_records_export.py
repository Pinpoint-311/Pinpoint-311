"""A public-records response should contain what was asked for.

The export offered a date range and a fixed set of ten columns. So a request
for "pothole complaints on Main Street in 2024" was answered with every report
the town has ever taken, and a request that should have excluded internal staff
notes had no way to exclude them.

Over-disclosure is the failure that matters here. A resident's phone number
released in answer to a request that did not cover it cannot be recalled, and
the person whose number it was never knew it was in scope. Under-disclosure
gets a follow-up email; over-disclosure gets a letter from a lawyer and is
somebody's actual privacy.

So the reporter fields are opt-in by name, the file records which fields were
left out, and every export is written to the audit trail -- not only the ones
carrying PII, because "which records left this building, when, and who took
them" is the first question an audit of a records process asks.
"""

from datetime import datetime, timezone

import pytest

from app.services.opra_export import (
    DEFAULT_FIELDS, FIELD_IDS, SENSITIVE_FIELDS, UnknownField,
    build_row, describe_fields, headers, normalise_fields, parse_boundary,
    preamble, sensitive_selected,
)


class Dept:
    name = "Public Works"


class Record:
    def __init__(self, **kw):
        self.service_request_id = "REQ-1"
        self.service_name = "Pothole"
        self.status = "closed"
        self.requested_datetime = datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc)
        self.closed_datetime = datetime(2024, 3, 4, 15, 0, tzinfo=timezone.utc)
        self.address = "1 Main St"
        self.lat, self.long = 40.3, -74.6
        self.description = "Big hole"
        self.completion_message = "Filled"
        self.closed_substatus = None
        self.assigned_department = Dept()
        self.source = "portal"
        self.staff_notes = "Crew went twice"
        self.assigned_to = "jsmith"
        self.first_name, self.last_name = "Ada", "Lovelace"
        self.email, self.phone = "ada@example.org", "555-0100"
        self.archived_at = None
        for k, v in kw.items():
            setattr(self, k, v)


# ---- the default is the safe one ----

def test_the_reporter_is_not_in_the_default_selection():
    """Nobody has to remember to turn PII off. They have to decide to turn it
    on, which is the direction that fails safely."""
    assert not (set(DEFAULT_FIELDS) & SENSITIVE_FIELDS)


def test_internal_notes_are_not_a_default():
    """Usually exempt. Including them by accident is a disclosure a custodian
    cannot walk back."""
    assert "staff_notes" not in DEFAULT_FIELDS


def test_the_usual_columns_are_still_there():
    for field in ("service_request_id", "service_name", "status",
                  "requested_datetime", "address", "description"):
        assert field in DEFAULT_FIELDS


# ---- choosing ----

def test_an_unknown_field_is_refused_rather_than_dropped():
    """Silently ignoring a typo produces an export missing a column the
    custodian believes is in it, and a records response is not a place to
    guess."""
    with pytest.raises(UnknownField):
        normalise_fields(["service_name", "reporter_ssn"])


def test_the_selection_comes_back_in_catalog_order():
    """So the header row is stable no matter what order the checkboxes were
    ticked in, and two exports of the same request are comparable."""
    a = normalise_fields(["description", "service_request_id", "status"])
    b = normalise_fields(["status", "description", "service_request_id"])
    assert a == b == ["service_request_id", "status", "description"]


def test_omitting_the_parameter_gives_the_default_set():
    assert normalise_fields(None) == list(DEFAULT_FIELDS)


def test_an_explicitly_empty_selection_stays_empty():
    """Turned into an error by the endpoint rather than silently becoming the
    defaults -- a caller that asked for nothing has made a mistake, and
    answering with the usual columns hides it."""
    assert normalise_fields([]) == []


def test_the_sensitive_ones_are_reported_by_name():
    chosen = normalise_fields(["service_name", "email", "phone"])
    assert sensitive_selected(chosen) == ["email", "phone"]


def test_the_catalog_marks_what_identifies_somebody():
    described = {f["id"]: f for f in describe_fields()}
    assert described["email"]["sensitive"] is True
    assert described["service_name"]["sensitive"] is False
    # And warns about the two that carry personal detail without being "PII".
    assert "note" in described["description"], (
        "the free-text field can name people even with the PII fields off"
    )
    assert "note" in described["staff_notes"]


# ---- dates ----

def test_a_bare_date_is_read_as_utc_not_as_whatever_the_server_thinks():
    """`datetime.fromisoformat("2024-01-01")` is naive, and a naive value
    compared against a timestamptz column is interpreted in the database
    session's timezone -- so the same export returns different records
    depending on a server setting nobody looked at. Here that means a records
    response missing a day at either end."""
    assert parse_boundary("2024-01-01").tzinfo is not None
    assert parse_boundary("2024-01-01") == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_an_end_date_covers_the_whole_of_that_day():
    """"1 January to 31 January" from a custodian includes the 31st. Treating
    it as midnight silently drops a day of records."""
    end = parse_boundary("2024-01-31", end=True)
    assert end.hour == 23 and end.minute == 59 and end.second == 59


def test_an_explicit_time_is_taken_literally():
    end = parse_boundary("2024-01-31T09:30:00", end=True)
    assert end.hour == 9 and end.minute == 30


def test_an_offset_in_the_input_is_preserved_as_an_instant():
    parsed = parse_boundary("2024-01-01T00:00:00-05:00")
    assert parsed == datetime(2024, 1, 1, 5, 0, tzinfo=timezone.utc)


def test_no_date_means_no_bound():
    assert parse_boundary(None) is None and parse_boundary("") is None


# ---- rows ----

def test_a_row_matches_its_header_position_for_position():
    fields = normalise_fields(["service_request_id", "address", "description"])
    assert headers(fields) == ["Request ID", "Address", "What was reported"]
    assert build_row(Record(), fields) == ["REQ-1", "1 Main St", "Big hole"]


def test_a_field_that_was_not_chosen_is_not_in_the_row():
    fields = normalise_fields(["service_request_id"])
    row = build_row(Record(), fields)
    assert row == ["REQ-1"]
    assert "ada@example.org" not in row and "Crew went twice" not in row


def test_the_department_name_is_resolved_rather_than_printed_as_an_object():
    fields = normalise_fields(["assigned_department"])
    assert build_row(Record(), fields) == ["Public Works"]


def test_a_record_with_no_department_does_not_crash():
    fields = normalise_fields(["assigned_department"])
    assert build_row(Record(assigned_department=None), fields) == [None]


def test_timestamps_are_written_as_iso_with_an_offset():
    fields = normalise_fields(["requested_datetime"])
    assert build_row(Record(), fields)[0] == "2024-03-01T09:00:00+00:00"


def test_a_naive_timestamp_is_still_written_with_an_offset():
    """A file handed to a requester should not contain a time with no timezone;
    they cannot tell what it means."""
    fields = normalise_fields(["requested_datetime"])
    record = Record(requested_datetime=datetime(2024, 3, 1, 9, 0))
    assert build_row(record, fields)[0].endswith("+00:00")


# ---- the file says what it is ----

def test_the_preamble_names_what_was_left_out():
    """A custodian producing this months later, to a requester saying it is
    incomplete, needs the file itself to say what was excluded."""
    text = "\n".join(preamble(
        law="OPRA (N.J.S.A. 47:1A-1)", state_name="New Jersey", state_code="NJ",
        total=12, exported_by="clerk", fields=normalise_fields(["service_request_id"]),
        filters={"start_date": "2024-01-01"},
        generated=datetime(2026, 8, 2, tzinfo=timezone.utc),
    ))
    assert "Fields included: Request ID" in text
    assert "Reporter email" in text.split("Fields omitted:")[1]


def test_the_preamble_says_when_nothing_was_filtered():
    """"Every record the town holds" should not be the thing nobody realises
    they produced."""
    text = "\n".join(preamble(
        law="OPRA", state_name="New Jersey", state_code="NJ", total=9000,
        exported_by="clerk", fields=list(DEFAULT_FIELDS), filters={},
        generated=datetime(2026, 8, 2, tzinfo=timezone.utc),
    ))
    assert "this is every non-deleted record" in text


def test_the_preamble_records_the_filters_that_were_used():
    text = "\n".join(preamble(
        law="OPRA", state_name="New Jersey", state_code="NJ", total=3,
        exported_by="clerk", fields=list(DEFAULT_FIELDS),
        filters={"start_date": "2024-01-01", "statuses": ["closed"],
                 "service_codes": ["POTHOLE"]},
        generated=datetime(2026, 8, 2, tzinfo=timezone.utc),
    ))
    assert "Filter start date: 2024-01-01" in text
    assert "Filter statuses: closed" in text
    assert "Filter service codes: POTHOLE" in text


# ---- the endpoint ----

def _endpoint() -> str:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    block = source[source.index('@router.get("/retention/export")'):]
    return block[:block.index("\n@router.")]


def test_every_export_is_audited_not_only_the_ones_with_pii():
    endpoint = _endpoint()
    assert "record_admin_action(" in endpoint
    assert '"public_records_export"' in endpoint
    assert '"sensitive_fields": sensitive' in endpoint


def test_the_export_is_administrators_only():
    endpoint = _endpoint()
    assert "current_user: User = Depends(get_current_admin)" in endpoint


def test_the_export_no_longer_hardcodes_its_columns():
    endpoint = _endpoint()
    assert "build_row(record, chosen)" in endpoint
    assert "r.service_request_id,\n" not in endpoint


def test_an_archived_record_says_so_rather_than_being_blank():
    """Retention clears the contents but the record still exists and still
    counts. A row of blanks reads as a broken export."""
    endpoint = _endpoint()
    assert "[Content cleared per retention policy]" in endpoint
