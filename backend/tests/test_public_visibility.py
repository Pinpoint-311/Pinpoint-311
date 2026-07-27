"""Tests for resident-chosen public-feed visibility ("unlisted" reports).

The contract:
  * unlisted reports are excluded from every PUBLIC listing/API,
  * they remain reachable by their direct tracking link,
  * they are always fully visible to town staff,
  * existing reports stay public (no silent retroactive hiding).

The listing filter is the load-bearing part — if it is ever dropped, every report
a resident asked to keep unlisted is silently republished. These tests pin it.
"""

import pytest

pytest.importorskip("sqlalchemy")
open311 = pytest.importorskip("app.api.open311")

from sqlalchemy import select

from app.models import ServiceRequest


def _public_sql() -> str:
    q = select(ServiceRequest).where(*open311.public_visibility_filters())
    return str(q.compile(compile_kwargs={"literal_binds": True})).lower()


# ---- the listing filter ----------------------------------------------------

def test_public_listing_filters_out_unlisted():
    assert "is_public" in _public_sql()


def test_public_listing_still_excludes_deleted():
    assert "deleted_at" in _public_sql()


def test_public_listing_requires_is_public_true():
    sql = _public_sql()
    # Must assert TRUE specifically — `IS NOT NULL` or similar would let
    # unlisted rows straight back into the feed.
    assert "is_public is true" in sql or "is_public = true" in sql or "is_public = 1" in sql


# ---- model defaults --------------------------------------------------------

def test_new_requests_default_to_public():
    """Opting out must be a deliberate choice, not the default."""
    assert ServiceRequest.__table__.c.is_public.default.arg is True


def test_is_public_is_not_nullable():
    """NULL would be ambiguous — every row must be definitively public or not."""
    assert ServiceRequest.__table__.c.is_public.nullable is False


def test_existing_rows_backfill_to_public():
    """The server_default keeps pre-existing reports visible after migration
    instead of silently hiding the town's entire history."""
    assert "true" in str(ServiceRequest.__table__.c.is_public.server_default.arg).lower()


def test_is_public_is_indexed():
    """The public feed filters on this column on every uncached request."""
    assert ServiceRequest.__table__.c.is_public.index is True


# ---- schema plumbing -------------------------------------------------------

def test_create_schemas_accept_the_choice_and_default_public():
    from app.schemas import ServiceRequestCreate, ManualIntakeCreate

    resident = ServiceRequestCreate(
        service_code="pothole", description="A large pothole here", email="a@b.com"
    )
    assert resident.is_public is True
    assert ServiceRequestCreate(
        service_code="pothole", description="A large pothole here",
        email="a@b.com", is_public=False,
    ).is_public is False

    # Staff taking a report by phone can honor the same request.
    assert ManualIntakeCreate(service_code="pothole", description="pothole").is_public is True
    assert ManualIntakeCreate(
        service_code="pothole", description="pothole", is_public=False
    ).is_public is False


def test_response_schema_exposes_visibility_to_staff():
    """Staff need to see that a report is unlisted so they don't discuss it
    publicly; a legacy row with NULL reads as public."""
    from app.schemas import ServiceRequestResponse

    assert "is_public" in ServiceRequestResponse.model_fields
