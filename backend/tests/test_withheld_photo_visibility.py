"""A withheld photo has to be findable by someone.

The withholding itself was already right: a photo the blur could not clear is
kept out of `media_urls` entirely, so no public surface can render it by
forgetting a filter, and the report still goes through. What was missing was
everyone who needed to know it had happened.

  * Staff had one surface -- an amber panel inside a report's detail view --
    and no badge, count or filter anywhere. A held photo on a report nobody
    opened was never reviewed. On a town whose cloud detector has no usable
    credentials that is not a rare case; it is the default outcome.

  * The resident had none at all. Their photo was attached, then absent from
    the tracker, with nothing anywhere saying why.

Both now read one number off the report. These tests pin that the number is
real (counted from the held photos, not stored separately and left to drift),
that it reaches the two responses that need it, and -- the part that matters
most -- that the *photos* still do not, because they are unredacted by
definition and that is the whole reason they are being held.
"""

import pytest

# resolve, and the response models, reach SQLAlchemy and Pydantic. CI installs
# neither, so skip on a submodule rather than the package.
pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("fastapi.routing")

from app.models import ServiceRequest
from app.schemas import Open311CreatedRequestResponse, ServiceRequestResponse


HELD_BYTES = "data:image/jpeg;base64,SECRETFACEBYTES"


def _held(n):
    return [{"media": HELD_BYTES, "reason": "provider-error"} for _ in range(n)]


# ------------------------------------------------------------------ the count

def test_the_count_is_derived_from_the_held_photos():
    """Not a column of its own. A second copy of the same fact drifts the first
    time anything mutates one list without the other -- and the thing that
    mutates it is the staff review endpoint, which pops entries one at a
    time."""
    sr = ServiceRequest()
    sr.media_pending_review = _held(2)
    assert sr.photos_pending_review == 2

    sr.media_pending_review.pop()
    assert sr.photos_pending_review == 1


def test_a_report_with_nothing_held_counts_zero_not_none():
    """The column defaults to [] but is nullable, and rows written before the
    migration have NULL in it. Every caller here does arithmetic or a `> 0`
    comparison on this value."""
    sr = ServiceRequest()
    assert sr.photos_pending_review == 0

    sr.media_pending_review = None
    assert sr.photos_pending_review == 0

    sr.media_pending_review = []
    assert sr.photos_pending_review == 0


# ------------------------------------------------------- what staff are handed

def test_the_staff_list_carries_the_count_and_not_the_photos():
    """This is the model behind the list the dashboard counts its queue badge
    from, and it is served for every report on the page at once. The held
    photos are megabytes of base64 each and unredacted besides; they belong on
    the staff-only *detail* model, which is the one surface that shows them to
    a person who is about to decide."""
    sr = ServiceRequest(
        id=1, service_request_id="REQ-1", service_code="POTHOLE",
        service_name="Pothole", description="d", status="open", priority=5,
        source="web",
    )
    sr.media_pending_review = _held(2)

    payload = ServiceRequestResponse.model_validate(sr).model_dump()

    assert payload["photos_pending_review"] == 2
    assert HELD_BYTES not in repr(payload)


# ---------------------------------------------------- what the resident is told

def test_the_submit_acknowledgement_says_a_photo_was_withheld():
    """The moment the resident can still be reached.

    Their thumbnail's status was decided at pick time and the submit is where
    the real answer is reached -- a photo the pick-time screen could not clear
    is usually cleared by the submit-time pass, and one that looked fine can
    still be withheld there. Without this the success screen thanked someone
    whose photo had just been held back and never mentioned it, on this screen
    or on the tracker afterwards."""
    sr = ServiceRequest(
        service_request_id="REQ-1", service_code="POTHOLE", service_name="Pothole",
        description="d", status="open",
    )
    sr.media_pending_review = _held(1)

    payload = Open311CreatedRequestResponse.model_validate(sr).model_dump()

    assert payload["photos_pending_review"] == 1
    assert HELD_BYTES not in repr(payload)


def test_the_acknowledgement_is_quiet_when_nothing_was_withheld():
    """The notice is worth showing precisely because it is unusual. A count
    that was always truthy would put an amber panel on every submission and
    stop meaning anything."""
    sr = ServiceRequest(
        service_request_id="REQ-1", service_code="POTHOLE", service_name="Pothole",
        description="d", status="open",
    )
    payload = Open311CreatedRequestResponse.model_validate(sr).model_dump()
    assert payload["photos_pending_review"] == 0


# ------------------------------------------------------------- the public route

@pytest.mark.asyncio
async def test_the_public_tracker_is_told_how_many_and_never_which():
    """The tracker is unauthenticated -- the whole internet reads this dict.

    The count is what turns "my photo vanished" into "my photo is waiting",
    and it is not sensitive. The held bytes are the reason the photo is being
    held in the first place: nobody has confirmed there is not a face in it.
    They must not appear in this response under any key, including by
    somebody later adding `media_pending_review` beside `media_urls` for
    symmetry.
    """
    from app.api import open311

    sr = ServiceRequest(
        service_request_id="REQ-1", service_code="POTHOLE", service_name="Pothole",
        description="d", status="open", address="1 Main St", lat=1.0, long=2.0,
    )
    sr.media_urls = []
    sr.media_pending_review = _held(2)
    sr.requested_datetime = None
    sr.updated_datetime = None
    sr.closed_substatus = None
    sr.completion_message = None
    sr.completion_photo_url = None
    sr.assigned_department = None

    class _Result:
        def scalar_one_or_none(self):
            return sr

    class _DB:
        async def execute(self, *a, **kw):
            return _Result()

    payload = await open311.get_public_request_detail("REQ-1", db=_DB())

    assert payload["photos_pending_review"] == 2
    assert payload["media_urls"] == []
    assert HELD_BYTES not in repr(payload)
