"""Retention reaches every copy of what it clears.

The field list was written before several features that keep a second copy of
a report's details somewhere else. Each of these outlived the field the town
had chosen to clear:

  * the Resident history fingerprints of the name and email -- staff could still
    find an "archived" request by searching the resident's email;
  * photos held back for review, which are the unredacted originals;
  * the closing message staff sent the resident, which was in no field at all;
  * the asset beside the pin, and the "nearby" facilities and similar reports in
    the triage context, which put a cleared location back on the map;
  * this report's description quoted in the triage context of later reports
    nearby, and cached translations of cleared text.

The pure parts run anywhere; the cross-record parts need PostGIS
(GIS_LAYERS_PG_URL, a throwaway database -- each test starts from an empty
schema).
"""
import os

import pytest

from app.services import retention_scrub as S


class Rec:
    def __init__(self, **kw):
        self.id = 7
        self.service_request_id = "REQ-1"
        self.first_name = "Maria"; self.last_name = "Lopez"
        self.email = "maria@example.com"; self.phone = "555-0143"
        self.resident_email_index = "e" * 64; self.resident_name_index = "n" * 64; self.pii_index_version = 1
        self.description = "Pothole outside 12 Elm St, call Maria on 555-0143"
        self.staff_notes = None; self.custom_fields = {}
        self.media_urls = ["/api/uploads/a.jpg"]
        self.media_pending_review = [{"media": "/api/uploads/raw-face.jpg", "reason": "faces"}]
        self.completion_photo_url = None
        self.completion_message = "Patched the hole outside 12 Elm St, thanks Maria"
        self.address = "12 Elm St"; self.lat = 40.8; self.long = -74.2; self.location = "POINT(...)"
        self.gis_context = [{"layer_id": 1, "feature_key": "12-4"}]
        self.matched_asset = {"asset_id": "HYD-12", "distance_meters": 4.2}
        self.ai_analysis = {
            "priority_score": 6,
            "context": {"critical_infrastructure": ["School: Elm Street Elementary (40m)"],
                        "is_school_zone": True, "similar_reports": [{"id": "REQ-0", "description": "x"}],
                        "weather_at_report": "rain"},
            "similar_reports": [{"id": "REQ-0", "description": "x"}],
        }
        self.ai_summary = None; self.vertex_ai_summary = None
        for k, v in kw.items():
            setattr(self, k, v)


def test_clearing_the_name_and_email_takes_the_fingerprints_with_them():
    r = Rec()
    S.apply_scrub(r, ["name"])
    assert r.resident_name_index is None and r.resident_email_index is not None
    assert r.pii_index_version == 1            # the email fingerprint still needs it
    S.apply_scrub(r, ["email"])
    assert r.resident_email_index is None and r.pii_index_version is None


def test_photos_held_for_review_are_cleared_and_their_files_named_for_deletion():
    r = Rec()
    assert "raw-face.jpg" in S.upload_filenames(r)
    S.apply_scrub(r, ["media"])
    assert r.media_pending_review == [] and r.media_urls == []


def test_the_closing_message_is_a_field_of_its_own():
    assert "closing_message" in S.FIELD_IDS
    r = Rec()
    assert S.apply_scrub(r, ["closing_message"]) == ["closing_message"]
    assert r.completion_message is None
    r = Rec()
    S.apply_scrub(r, [f for f in S.FIELD_IDS if f != "closing_message"])
    assert r.completion_message is not None     # only when chosen ...
    assert "closing_message" in S.fields_for_mode(S.PURGE)   # ... and always by a purge


def test_clearing_the_location_clears_everything_that_says_where():
    r = Rec()
    S.apply_scrub(r, ["coordinates"])
    assert r.matched_asset is None and r.gis_context is None
    blob = repr(r.ai_analysis)
    for leak in ("Elm Street Elementary", "is_school_zone", "similar_reports", "REQ-0"):
        assert leak not in blob, leak
    assert r.ai_analysis["priority_score"] == 6               # the AI analysis itself is a separate choice
    assert r.ai_analysis["context"]["weather_at_report"] == "rain"


def test_the_descriptions_say_nothing_about_this_codebase_history():
    for f in S.SCRUB_FIELDS:
        assert "until recently" not in f["detail"] and "--" not in f["detail"], f["id"]


# ------------------------------------------------------------- across records

PG_URL = os.environ.get("GIS_LAYERS_PG_URL")
pg = pytest.mark.skipif(not PG_URL, reason="needs a throwaway PostGIS (GIS_LAYERS_PG_URL)")


@pytest.fixture
async def pgdb():
    pytest.importorskip("geoalchemy2")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app import models

    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(models.Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pg
async def test_archiving_reaches_the_copies_in_other_records_and_the_translation_cache(pgdb):
    from sqlalchemy import select
    from app.models import RequestComment, ServiceRequest, Translation
    from app.services import retention_service

    words = "Pothole outside 12 Elm St, call Maria on 555-0143"
    old = ServiceRequest(service_request_id="REQ-OLD", service_code="pothole", service_name="Pothole",
                         description=words, status="closed",
                         completion_message="Patched it, thanks Maria")
    old.email = "maria@example.com"
    later = ServiceRequest(service_request_id="REQ-LATER", service_code="pothole", service_name="Pothole",
                           description="Another pothole", status="open",
                           ai_analysis={"context": {"similar_reports": [
                               {"id": "REQ-OLD", "description": words[:100], "similarity": 0.8,
                                "justification": "Same corner as Maria's report"}]},
                               "similar_reports": [{"id": "REQ-OLD", "description": words[:100]}]})
    later.email = "someone@example.com"
    pgdb.add_all([old, later])
    await pgdb.flush()
    pgdb.add(RequestComment(service_request_id=old.id, username="maria", content="It's still there, Maria"))
    pgdb.add_all([Translation(source_text=t, source_lang="en", target_lang="es", translated_text="(es) " + t)
                  for t in (words, "Patched it, thanks Maria", "It's still there, Maria", "Submit")])
    await pgdb.commit()

    result = await retention_service.archive_record(pgdb, old.id, "redact",
                                                    ["description", "comments", "closing_message"])
    assert result["status"] == "anonymized"

    later_row = (await pgdb.execute(select(ServiceRequest).where(ServiceRequest.service_request_id == "REQ-LATER"))).scalar_one()
    blob = repr(later_row.ai_analysis)
    assert "Maria" not in blob and "555-0143" not in blob
    assert later_row.description == "Another pothole"          # its own words are untouched

    left = sorted(t.source_text for t in (await pgdb.execute(select(Translation))).scalars())
    assert left == ["Submit"]                                     # UI text stays cached
