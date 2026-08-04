"""Show the records before clearing them, and compute the list the same way.

"Run retention now" clears fields on resident records and cannot be undone.
The only thing shown before pressing it was a count -- and a count cannot say
that the oldest eligible record is four years past its date because the policy
has never actually run, or that a report somebody assumed was exempt is in the
list because nobody set the legal hold.

The risk in adding a preview is building it out of a second query that
*resembles* the first. That is worse than no preview: it invites somebody to
confirm against a list that is not the list. So the cutoff lives in one pure
function and both sides call it.

Which turned up a real disagreement already in the code. `get_records_for_archival`
computed its cutoff as

    retention_days = override_days if override_days else policy_days

taking the override whatever it was, while `calculate_retention_date` honoured
it only when it was *longer* than a state "minimum" the product had invented.
An override of 30 days therefore selected seven years of records for scrubbing
in one function and thirty days in the other. Nothing would have said so: the
run reports how many records it archived, and that number is equally plausible
either way.

Both inputs are gone with the state table. There is one number now -- the
period the municipality configured -- so the arithmetic those tests policed no
longer exists to get wrong. What is still worth policing is the thing that
motivated it: the preview and the sweep must compute their list the same way,
from the same function, or the confirmation is against a list that is not the
list.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.retention_window import (
    as_utc, describe_record, retention_cutoff, summarise,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
# A period a town might well set. Nothing in the product supplies it.
SEVEN_YEARS = 2555


class Record:
    def __init__(self, closed, rid="REQ-1", name="Pothole", address="1 Main St"):
        self.closed_datetime = closed
        self.service_request_id = rid
        self.service_name = name
        self.address = address


# ---- one period, no arithmetic ----

def test_the_cutoff_is_the_period_the_town_set():
    assert retention_cutoff(SEVEN_YEARS, NOW) == NOW - timedelta(days=SEVEN_YEARS)
    assert retention_cutoff(30, NOW) == NOW - timedelta(days=30)


def test_there_is_no_second_period_to_reconcile():
    """`effective_retention_days` combined a state minimum with a town
    override, and the two call sites combined them differently. Both inputs
    were the product's own invention; removing them removes the class of bug
    rather than fixing one instance of it."""
    from app.services import retention_window

    assert not hasattr(retention_window, "effective_retention_days")


def test_the_eligibility_query_computes_its_cutoff_in_one_place():
    """So the query cannot select a record the preview says is not due yet."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/services/retention_service.py").read_text()
    assert "override_days if override_days else" not in source, (
        "the eligibility cutoff is being computed separately again"
    )
    assert "timedelta(days=" not in source, (
        "a second cutoff calculation has grown back outside retention_window"
    )
    assert source.count("retention_cutoff(") >= 2


# ---- what a row says ----

def test_a_row_carries_the_age_and_how_far_past_due_it_is():
    """"Over by 1 day" and "over by four years" are the same row to a count and
    completely different to a person: the second says the policy has never
    actually run and this press will catch up on a decade at once."""
    closed = NOW - timedelta(days=SEVEN_YEARS + 400)
    row = describe_record(Record(closed), cutoff=retention_cutoff(SEVEN_YEARS, NOW), now=NOW)

    assert row["age_days"] == SEVEN_YEARS + 400
    assert row["days_past_retention"] == 400
    assert row["service_request_id"] == "REQ-1"


def test_age_is_measured_from_closing_not_submission():
    """Retention runs from when the matter concluded. A report open for two
    years is not two years overdue for archival."""
    closed = NOW - timedelta(days=100)
    row = describe_record(Record(closed), cutoff=NOW - timedelta(days=90), now=NOW)
    assert row["age_days"] == 100
    assert row["days_past_retention"] == 10


def test_a_naive_timestamp_does_not_raise():
    """Same failure that took the statistics page down: an aware `now` minus a
    naive column value."""
    row = describe_record(Record(datetime(2020, 1, 1)), cutoff=NOW - timedelta(days=90), now=NOW)
    assert row["age_days"] > 2000


def test_a_record_with_no_closing_date_is_described_rather_than_crashing():
    row = describe_record(Record(None), cutoff=NOW, now=NOW)
    assert row["age_days"] is None and row["days_past_retention"] is None


def test_as_utc_normalises_up_rather_than_stripping():
    eastern = datetime(2026, 8, 2, 8, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert as_utc(eastern) == NOW
    assert as_utc(None) is None


# ---- the headline ----

def test_the_summary_says_when_the_list_is_only_part_of_it():
    """Fifty rows out of four thousand, presented as if fifty were the answer,
    is the quiet undercount this screen exists to prevent."""
    rows = [describe_record(Record(NOW - timedelta(days=3000 + i)), cutoff=NOW - timedelta(days=SEVEN_YEARS), now=NOW)
            for i in range(50)]
    s = summarise(rows, total=4000, retention_days=SEVEN_YEARS, cutoff=NOW - timedelta(days=SEVEN_YEARS))

    assert s["total"] == 4000
    assert s["showing"] == 50
    assert s["truncated"] is True


def test_the_summary_is_not_marked_truncated_when_it_is_complete():
    rows = [describe_record(Record(NOW - timedelta(days=3000)), cutoff=NOW - timedelta(days=SEVEN_YEARS), now=NOW)]
    s = summarise(rows, total=1, retention_days=SEVEN_YEARS, cutoff=NOW - timedelta(days=SEVEN_YEARS))
    assert s["truncated"] is False


def test_the_summary_reports_the_span_of_ages():
    rows = [
        describe_record(Record(NOW - timedelta(days=3000)), cutoff=NOW, now=NOW),
        describe_record(Record(NOW - timedelta(days=2600)), cutoff=NOW, now=NOW),
    ]
    s = summarise(rows, total=2, retention_days=SEVEN_YEARS, cutoff=NOW)
    assert s["oldest_age_days"] == 3000
    assert s["newest_age_days"] == 2600


def test_an_empty_list_summarises_without_raising():
    s = summarise([], total=0, retention_days=SEVEN_YEARS, cutoff=NOW)
    assert s["total"] == 0 and s["oldest_age_days"] is None


# ---- the endpoint ----

def test_the_preview_uses_the_same_selection_as_the_run():
    """The whole point. A preview built from a second query that resembles the
    first invites somebody to confirm against a list that is not the list."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    endpoint = source[source.index('@router.get("/retention/preview")'):]
    endpoint = endpoint[:endpoint.index("\n@router.", 10)]

    # The *call*, not the import. An earlier version of this assertion looked
    # for the name anywhere in the block and passed with the call replaced by
    # an empty list, because the import line still mentioned it.
    assert "await get_records_for_archival(db, retention_days" in endpoint, (
        "the preview is not calling the function the sweep calls"
    )


def test_the_preview_respects_an_instance_wide_legal_hold():
    """Listing records that "will be archived next run" while a hold means
    nothing can be archived at all is the sort of contradiction that gets a
    screen distrusted."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    endpoint = source[source.index('@router.get("/retention/preview")'):]
    endpoint = endpoint[:endpoint.index("\n@router.", 10)]

    # The guard itself. Looking for the words "legal_hold" and "records: []"
    # anywhere in the block passed with the condition replaced by `if False`,
    # since both strings survive that.
    assert 'getattr(settings, "legal_hold", False)' in endpoint, (
        "the preview no longer checks the instance-wide legal hold"
    )
    hold_branch = endpoint[endpoint.index('getattr(settings, "legal_hold", False)'):]
    assert '"records": []' in hold_branch[:900], (
        "the legal-hold branch does not return an empty list"
    )


def test_the_preview_is_administrators_only():
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "preview_retention_run":
            defaults = ast.dump(ast.Module(body=[ast.Expr(d) for d in node.args.defaults], type_ignores=[]))
            assert "get_current_admin" in defaults
            return
    pytest.fail("no preview_retention_run endpoint")


def test_there_is_only_one_preview_endpoint():
    """I added a second route on the same path before noticing the first, and
    FastAPI would have served the original -- so the new code would never have
    run and the page would have shown the old shape. Two decorators with the
    same path is silent."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    assert source.count('@router.get("/retention/preview")') == 1
