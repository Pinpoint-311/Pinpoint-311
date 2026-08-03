"""The answers to a town's own follow-up questions are part of the record.

A service can carry `custom_questions` in its routing config -- "Is it a stop
sign?", "Which corner?" -- and the answers land in `service_requests.custom_fields`.
That much worked: the resident form renders them, intake stores them, the AI
prompt includes them under "Resident Survey Responses", and the printed work
order has an "Additional Information" block.

Two places did not know the column existed, and both of them are the kind of
place where not knowing is a compliance problem rather than a missing feature:

* **Retention.** The scrub catalog listed name, email, phone, description,
  staff notes, photos and AI analysis. Not this. So a question like "What is the
  best number to reach you on?" kept its answer forever, on a record whose every
  other identifying field had already been cleared -- and the town believed it
  had honoured its own retention schedule.

* **OPRA export.** A public-records response omitted the answers entirely. The
  town was replying to a records request with an incomplete record and no
  indication anything was missing.
"""

import pytest

pytest.importorskip("cryptography")

from app.services import opra_export as ox
from app.services import retention_scrub as rs


class _Record:
    """Only the attributes the two modules touch."""

    def __init__(self):
        self.id = 7
        self.first_name = "Ada"
        self.last_name = "Lovelace"
        self.email = "ada@example.org"
        self.phone = "+15550000000"
        self.description = "Sign is bent"
        self.staff_notes = "spoke to the caller"
        self.media_urls = ["data:image/png;base64,AAA"]
        self.ai_analysis = {"summary": "bent sign"}
        self.address = "1 Main St"
        self.lat = 40.7
        self.long = -74.2
        self.custom_fields = {
            "Is it a stop sign?": "Yes",
            "Best number to reach you": "555-0100",
            "Which corners?": ["North", "South-east"],
        }


# --- retention --------------------------------------------------------------

def test_custom_answers_can_be_scrubbed_at_all():
    assert "custom_fields" in rs.FIELD_IDS, (
        "a field retention cannot name is a field retention can never clear"
    )


def test_custom_answers_are_scrubbed_by_default():
    """They are resident-written free text, exactly like the description, which
    is also a default. A town that never opens the settings screen should not be
    the one town still holding this."""
    assert "custom_fields" in rs.DEFAULT_FIELDS


def test_scrubbing_actually_empties_them():
    record = _Record()
    cleared = rs.apply_scrub(record, rs.DEFAULT_FIELDS)
    assert "custom_fields" in cleared
    assert record.custom_fields == {}


def test_scrubbing_leaves_them_alone_when_not_selected():
    """`apply_scrub` clears only what was asked for -- over-clearing is how a
    town loses the public-records index it is obliged to keep."""
    record = _Record()
    cleared = rs.apply_scrub(record, ["description"])
    assert "custom_fields" not in cleared
    assert record.custom_fields["Is it a stop sign?"] == "Yes"


def test_the_settings_screen_offers_them():
    ids = [f["id"] for f in rs.describe_selection(rs.DEFAULT_FIELDS)]
    assert "custom_fields" in ids


# --- OPRA export ------------------------------------------------------------

def test_a_records_request_includes_the_answers():
    assert "custom_fields" in ox.DEFAULT_FIELDS, (
        "omitting them makes the export an incomplete answer, silently"
    )


def test_answers_are_rendered_as_text_not_a_python_dict():
    """This lands in a CSV cell that goes to a member of the public. A dict repr
    with braces and quotes in it is not an answer to a records request."""
    rendered = ox._value(_Record(), "custom_fields")
    assert "{" not in rendered and "'" not in rendered
    assert "Is it a stop sign?: Yes" in rendered
    # A checkbox question stores a list; it has to read as a list of words.
    assert "North, South-east" in rendered


def test_no_answers_reads_as_empty_rather_than_an_empty_object():
    class Blank(_Record):
        def __init__(self):
            super().__init__()
            self.custom_fields = {}

    assert ox._value(Blank(), "custom_fields") is None


def test_the_field_warns_that_it_can_name_people():
    """The description carries this warning because residents put names in it.
    The same is true here, and a custodian choosing fields needs to know."""
    spec = ox._BY_ID["custom_fields"]
    assert "note" in spec and spec["note"]
