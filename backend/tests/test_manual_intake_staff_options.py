"""Staff intake: the choices a clerk can make, and the photos they attach.

The staff "log a request" form can now pick the department, the assignee and
the priority, leave an internal note, and switch the caller's confirmation off.
Each of those falls back to what a resident submission would get when left
out, and each one a clerk *does* send is checked before anything is written --
a typo in a username must be a 400 the clerk can fix, not a request routed to
nobody.

Photos go through the same pick-time screening as the resident form, so the
endpoint has to redeem handles the way create_request does. Two differences
are deliberate and pinned here:

  * Redaction always applies -- a photo from a phone call has bystanders in it
    as often as one from the portal, and it is published to the same places.
  * Image *moderation* never blocks staff intake. A handle the screen marked
    blocked holds no bytes, so it is named for the client to resend inline
    (where it is blurred like any other photo), not refused.
"""

import pytest

# CI installs only cryptography/httpx/pytest/pytest-asyncio/alembic, so an
# unguarded app import breaks collection there while passing locally.
pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("fastapi.routing")
pytest.importorskip("pydantic")
pytest.importorskip("email_validator")

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.api import open311  # noqa: E402
from app.models import Department, ServiceDefinition, User  # noqa: E402
from app.schemas import ManualIntakeCreate, RequestSource  # noqa: E402
from app.services import image_redaction, photo_handles  # noqa: E402


# ----------------------------------------------------------------- fakes

class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDB:
    """Answers the endpoint's lookups from in-memory rows.

    `select(Model).where(Model.col == value)` is matched on the model and the
    bound values, which is all the endpoint ever asks of these tables.
    """

    def __init__(self, *, services=(), departments=(), users=()):
        self.rows = {
            ServiceDefinition: list(services),
            Department: list(departments),
            User: list(users),
        }
        self.added = []
        self.commits = 0

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        params = stmt.compile().params
        for row in self.rows.get(entity, []):
            if entity is ServiceDefinition and row.service_code in params.values():
                return _Result(row)
            if entity is Department and row.id in params.values():
                return _Result(row)
            if entity is User and row.username in params.values():
                return _Result(row)
        return _Result(None)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj, *args, **kwargs):
        if getattr(obj, "id", None) is None:
            obj.id = 1


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _service(**kw):
    defaults = dict(service_code="pothole", service_name="Pothole", is_active=True,
                    location_mode="optional", routing_mode="township", routing_config=None,
                    assigned_department_id=1)
    defaults.update(kw)
    return _Row(**defaults)


def _department(id=2, is_active=True, name="Roads"):
    return _Row(id=id, is_active=is_active, name=name, routing_email=None)


def _user(username="jdoe", role="staff", is_active=True):
    return _Row(username=username, role=role, is_active=is_active, id=7)


def _intake(**kw):
    data = dict(service_code="pothole", description="Deep pothole by the library")
    data.update(kw)
    return ManualIntakeCreate(**data)


# --------------------------------------------------------------- the schema

def test_the_new_fields_default_to_what_a_resident_submission_gets():
    intake = _intake()
    assert intake.assigned_department_id is None
    assert intake.assigned_to is None
    assert intake.manual_priority_score is None
    assert intake.staff_notes is None
    assert intake.send_confirmation is True


@pytest.mark.parametrize("score", [0, 0.5, 10.5, 11, -3])
def test_priority_is_bounded_like_every_other_priority_edit(score):
    with pytest.raises(ValidationError):
        _intake(manual_priority_score=score)


@pytest.mark.parametrize("score", [1, 5.5, 10])
def test_priority_accepts_the_whole_scale(score):
    assert _intake(manual_priority_score=score).manual_priority_score == score


def test_other_is_a_channel_and_needs_no_migration():
    """`source` is a plain String(50) with no CHECK constraint, so a new enum
    value is a schema-only change."""
    assert _intake(source="other").source is RequestSource.other
    from app.models import ServiceRequest
    column = ServiceRequest.__table__.c.source
    assert column.type.length >= len("other")
    assert not any(getattr(c, "sqltext", None) is not None and "source" in str(c.sqltext)
                   for c in ServiceRequest.__table__.constraints)


# ----------------------------------------------------- the staff choices

@pytest.mark.asyncio
async def test_nothing_chosen_means_nothing_overridden():
    db = _FakeDB()
    assert await open311._validate_intake_staff_options(db, _intake()) == (None, None)


@pytest.mark.asyncio
async def test_a_real_department_and_staff_member_are_accepted():
    db = _FakeDB(departments=[_department(id=2)], users=[_user("jdoe")])
    out = await open311._validate_intake_staff_options(
        db, _intake(assigned_department_id=2, assigned_to=" jdoe "))
    assert out == (2, "jdoe")


@pytest.mark.asyncio
async def test_an_admin_can_be_assigned():
    db = _FakeDB(users=[_user("boss", role="admin")])
    assert await open311._validate_intake_staff_options(
        db, _intake(assigned_to="boss")) == (None, "boss")


@pytest.mark.asyncio
@pytest.mark.parametrize("dept", [None, _department(id=2, is_active=False)])
async def test_a_missing_or_retired_department_is_a_400(dept):
    db = _FakeDB(departments=[dept] if dept else [])
    with pytest.raises(HTTPException) as exc:
        await open311._validate_intake_staff_options(db, _intake(assigned_department_id=2))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("users", [
    [],                                         # typo / unknown
    [_user("jdoe", role="researcher")],         # not staff
    [_user("jdoe", is_active=False)],           # deactivated
])
async def test_an_assignee_who_cannot_work_the_request_is_a_400(users):
    db = _FakeDB(users=users)
    with pytest.raises(HTTPException) as exc:
        await open311._validate_intake_staff_options(db, _intake(assigned_to="jdoe"))
    assert exc.value.status_code == 400


# ------------------------------------------------------------- the photos

DATA_A = "data:image/jpeg;base64,AAAA"
DATA_B = "data:image/jpeg;base64,BBBB"


def _handles(monkeypatch, table):
    taken = []

    async def _take(db, token):
        taken.append(token)
        return table.get(token)

    monkeypatch.setattr(photo_handles, "_take", _take)
    return taken


def _redactor(monkeypatch, fn=None):
    calls = []

    async def redact_media(media):
        calls.append(list(media))
        if fn:
            return fn(media)
        return image_redaction.BatchResult(
            media=[f"blurred:{m}" for m in media], kept=list(range(len(media))))

    monkeypatch.setattr(image_redaction, "redact_media", redact_media)
    return calls


def _h(token):
    return photo_handles.HANDLE_PREFIX + token


@pytest.mark.asyncio
async def test_a_screened_handle_is_redeemed_and_inline_photos_are_redacted(monkeypatch):
    _handles(monkeypatch, {"t1": _Row(verdict="ready", media="screened-1", reason="",
                                      faces=1, plates=0)})
    calls = _redactor(monkeypatch)

    media, pending = await open311._redeem_intake_media(None, [DATA_A, _h("t1"), DATA_B])

    # The handle's bytes are used as-is (already blurred at pick time) and the
    # inline photos are redacted -- in the order they were attached.
    assert media == [f"blurred:{DATA_A}", "screened-1", f"blurred:{DATA_B}"]
    assert calls == [[DATA_A, DATA_B]]
    assert pending == []


@pytest.mark.asyncio
async def test_a_stale_handle_asks_the_client_to_resend(monkeypatch):
    _handles(monkeypatch, {})
    _redactor(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await open311._redeem_intake_media(None, [_h("gone")])
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "stale_photo_handles"
    assert exc.value.detail["handles"] == [_h("gone")]


@pytest.mark.asyncio
async def test_a_blocked_handle_is_resent_inline_not_refused(monkeypatch):
    """Staff intake never image-moderates. The blocked handle has no bytes, so
    the client is asked for that photo inline -- a 409 it recovers from on its
    own -- rather than the 400 a resident gets."""
    _handles(monkeypatch, {"bad": _Row(verdict="blocked", media=None, reason="explicit",
                                       faces=0, plates=0)})
    _redactor(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await open311._redeem_intake_media(None, [_h("bad")])
    assert exc.value.status_code == 409
    assert exc.value.detail["handles"] == [_h("bad")]


@pytest.mark.asyncio
async def test_redaction_still_runs_with_no_detector_and_keeps_every_photo(monkeypatch):
    """redact_media's no-provider path strips EXIF and returns every photo
    with `kept` left empty. Rebuilding the order must not read that as
    "keep none"."""
    _handles(monkeypatch, {})
    _redactor(monkeypatch, lambda media: image_redaction.BatchResult(
        media=[f"exif-stripped:{m}" for m in media]))
    media, _ = await open311._redeem_intake_media(None, [DATA_A, DATA_B])
    assert media == [f"exif-stripped:{DATA_A}", f"exif-stripped:{DATA_B}"]


@pytest.mark.asyncio
async def test_a_photo_the_redactor_could_not_clear_is_held_for_review(monkeypatch):
    _handles(monkeypatch, {})
    _redactor(monkeypatch, lambda media: image_redaction.BatchResult(
        media=[f"blurred:{media[1]}"], kept=[1],
        withheld=[{"media": media[0], "reason": "error"}]))
    media, pending = await open311._redeem_intake_media(None, [DATA_A, DATA_B])
    assert media == [f"blurred:{DATA_B}"]
    assert pending == [{"media": DATA_A, "reason": "error"}]


# -------------------------------------------------------------- end to end

class _Allowed:
    blocked = False


class _Blocked:
    blocked = True
    jurisdiction = "County DPW"
    message = "County roads go to the county."
    message_is_default = False
    contacts = []
    road_name = "County Rd 5"


@pytest.fixture
def pipeline(monkeypatch):
    """Stub everything past the endpoint's own decisions."""
    seen = {"finalize": [], "recorded": 0}

    from app.core import encryption
    monkeypatch.setattr(encryption, "encrypt_pii", lambda v: f"enc:{v}")

    async def evaluate(db, service, lat, lng):
        return seen.get("block", _Allowed())

    async def record(*a, **k):
        seen["recorded"] += 1

    monkeypatch.setattr(open311.road_blocking, "evaluate", evaluate)
    monkeypatch.setattr(open311.road_blocking, "record", record)

    async def resolve_is_public(db, requested):
        return requested is not False

    monkeypatch.setattr(open311, "resolve_is_public", resolve_is_public)

    async def resolve_assignment(db, service):
        return 1, "router"

    monkeypatch.setattr(open311, "_resolve_assignment", resolve_assignment)

    async def finalize(db, sr, dept_id, **kw):
        seen["finalize"].append({"dept_id": dept_id, **kw})

    monkeypatch.setattr(open311, "_finalize_new_request", finalize)
    _redactor(monkeypatch)
    return seen


def _clerk():
    return _Row(username="clerk", role="staff")


@pytest.mark.asyncio
async def test_staff_choices_are_applied_and_audited_without_the_note(pipeline):
    db = _FakeDB(services=[_service()], departments=[_department(id=2)],
                 users=[_user("jdoe")])
    sr = await open311.create_manual_intake(
        _intake(email="caller@example.gov", assigned_department_id=2, assigned_to="jdoe",
                manual_priority_score=8, staff_notes="Caller is the property owner",
                source="other"),
        db=db, current_user=_clerk())

    assert sr.assigned_department_id == 2
    assert sr.assigned_to == "jdoe"
    assert sr.manual_priority_score == 8
    assert sr.staff_notes == "Caller is the property owner"
    assert sr.source == "other"

    call = pipeline["finalize"][0]
    assert call["dept_id"] == 2
    assert call["notify_resident"] is True
    options = call["audit_extra"]["intake_options"]
    assert set(options["fields"]) == {
        "assigned_department_id", "assigned_to", "manual_priority_score", "staff_notes"}
    # Routing values are recorded; the note itself never is.
    assert options["assigned_to"] == "jdoe"
    assert "Caller is the property owner" not in repr(call["audit_extra"])


@pytest.mark.asyncio
async def test_blank_choices_keep_the_category_routing(pipeline):
    db = _FakeDB(services=[_service()])
    sr = await open311.create_manual_intake(_intake(), db=db, current_user=_clerk())
    assert (sr.assigned_department_id, sr.assigned_to) == (1, "router")
    assert sr.manual_priority_score is None
    call = pipeline["finalize"][0]
    assert call["audit_extra"] is None
    # No real email, no confirmation -- the placeholder is never emailed.
    assert call["notify_resident"] is False


@pytest.mark.asyncio
async def test_the_confirmation_can_be_switched_off(pipeline):
    db = _FakeDB(services=[_service()])
    await open311.create_manual_intake(
        _intake(email="caller@example.gov", send_confirmation=False),
        db=db, current_user=_clerk())
    call = pipeline["finalize"][0]
    assert call["notify_resident"] is False
    assert call["audit_extra"]["intake_options"]["fields"] == ["send_confirmation"]


@pytest.mark.asyncio
async def test_an_unknown_assignee_writes_nothing(pipeline):
    db = _FakeDB(services=[_service()])
    with pytest.raises(HTTPException) as exc:
        await open311.create_manual_intake(
            _intake(assigned_to="nobody"), db=db, current_user=_clerk())
    assert exc.value.status_code == 400
    assert db.added == []
    assert pipeline["finalize"] == []


@pytest.mark.asyncio
async def test_handles_are_redeemed_on_the_staff_path(pipeline, monkeypatch):
    taken = _handles(monkeypatch, {"t1": _Row(verdict="ready", media="screened-1",
                                              reason="", faces=0, plates=0)})
    db = _FakeDB(services=[_service()])
    sr = await open311.create_manual_intake(
        _intake(media_urls=[_h("t1"), DATA_A]), db=db, current_user=_clerk())
    assert taken == ["t1"]
    assert sr.media_urls == ["screened-1", f"blurred:{DATA_A}"]


@pytest.mark.asyncio
async def test_a_redirect_is_answered_before_any_handle_is_spent(pipeline, monkeypatch):
    """The usual reply to this 409 is the same submission with "Log it anyway"
    ticked; spending the single-use handles first would force every photo to
    be resent inline."""
    taken = _handles(monkeypatch, {})
    pipeline["block"] = _Blocked()
    db = _FakeDB(services=[_service()])
    with pytest.raises(HTTPException) as exc:
        await open311.create_manual_intake(
            _intake(media_urls=[_h("t1")], lat=40.0, long=-74.0),
            db=db, current_user=_clerk())
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "redirected"
    assert exc.value.detail["can_override"] is True
    assert taken == []
    assert pipeline["recorded"] == 1


@pytest.mark.asyncio
async def test_the_override_still_logs_it(pipeline):
    pipeline["block"] = _Blocked()
    db = _FakeDB(services=[_service()])
    sr = await open311.create_manual_intake(
        _intake(override_jurisdiction=True, lat=40.0, long=-74.0),
        db=db, current_user=_clerk())
    assert sr.service_request_id.startswith("REQ-")
    assert pipeline["recorded"] == 0
