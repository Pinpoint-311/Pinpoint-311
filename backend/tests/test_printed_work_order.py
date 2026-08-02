"""The sheet a crew carries into the street.

Two things were wrong with what it printed.

Only internal comments appeared. That reads as a privacy decision and is the
opposite of one: the resident's own words are the field notes -- "it's the
second driveway", "the smell comes back after rain" -- and somebody standing at
the kerb had every staff comment and none of them.

And separating them into two blocks loses what makes them readable. "Is this
the one by the school?" in one list and "yes, the second driveway" in another
is a conversation with the replies filed away from the questions.

Checked from the backend suite for the reason the other frontend contract
tests are: it is the suite that runs on every change.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRINT = ROOT / "frontend/src/components/PrintWorkOrder.tsx"


@pytest.fixture(scope="module")
def source() -> str:
    if not PRINT.exists():
        pytest.skip("frontend not present in this checkout")
    return PRINT.read_text()


def test_the_resident_is_not_filtered_out(source):
    """The regression. `comments.filter(c => c.visibility === 'internal')` as
    the only source is what dropped them."""
    assert "comments?.filter(c => c.visibility === 'internal')" not in source, (
        "the printout is back to internal comments only"
    )
    assert "const conversation = [...(comments || [])]" in source


def test_it_prints_as_one_thread_in_order(source):
    """Sorted by time, not grouped by author. A reply has to sit under the
    thing it replies to."""
    block = source[source.index("const conversation = "):]
    block = block[:block.index("` : '';")]
    assert "sort(" in block and "created_at" in block
    assert "at - bt" in block, "the thread is not in ascending time order"


def test_internal_notes_stay_marked(source):
    """Interleaving them is only safe if the difference is visible. This sheet
    gets read aloud to a resident at the door."""
    assert "comment-internal" in source
    assert "Internal — not shown to the resident" in source


def test_a_missing_timestamp_does_not_reorder_the_thread(source):
    """`Date.parse(undefined)` is NaN, and NaN in a comparator scrambles the
    order silently rather than failing."""
    block = source[source.index("const conversation = "):]
    block = block[:block.index("});", block.index("sort("))]
    assert "c.created_at ?" in block or "a.created_at ?" in block, (
        "an absent created_at is not guarded before Date.parse"
    )


def test_the_closing_date_is_printed(source):
    """The sheet showed submitted and updated but not when the job actually
    ended, which is the date a closed work order is about."""
    assert "request.closed_datetime" in source


def test_a_legal_hold_says_why(source):
    """"Under legal hold" with no reason leaves whoever picks this up unable to
    tell whether it still applies."""
    assert "request.flag_reason" in source


def test_the_matched_asset_is_printed_once(source):
    """It is the most actionable line for a crew -- "catch basin CB-142" is
    what they are being sent to and the address is only how to get there.

    Pinned at exactly one because I started adding a second section before
    noticing the existing one, which is richer.
    """
    assert source.count("const assetHtml") == 1
    assert source.count("${assetHtml}") == 1
    assert "matchedAsset.asset_id" in source
