"""Four things an anonymous caller could see, or cause, and no longer can.

  * STAFF NAMES. `GET /public/requests/{id}/comments` returned `username` and
    `user_id` straight off the row, so anyone opening a report on the tracker
    learned which named employee replied -- and across a town's reports, the
    whole roster and each person's internal id. The public audit log 150 lines
    away in the same module already redacts its actor to "Staff".

  * HIDDEN MAP LAYERS. `GET /api/map-layers/{id}` had no guard at all, while
    `GET /` filters on `show_on_resident_portal` and `GET /all` requires an
    admin. Layer ids are sequential integers, so every staff-only overlay and
    unpublished draft a town had drawn could be walked one id at a time.

  * "KEEP THIS UNLISTED", FAILING OPEN. `resolve_is_public` caught every
    exception and returned True, so a transient settings read error published a
    report the resident had asked to keep unlisted -- description, address and
    photos, onto the public map -- leaving a logger.warning behind.

  * A PERMANENT LEGAL HOLD, PLACED BY A STRANGER. There is no per-record legal
    hold column; the hold WAS `ServiceRequest.flagged`, the same column content
    moderation writes. Retention skips flagged rows forever and reports them to
    the admin as "under legal hold". `add_public_comment` is unauthenticated by
    design and set it, so mild profanity in a comment on somebody else's report
    exempted that reporter's name, email, phone and address from the town's
    retention policy permanently -- for any report on the public map, one
    comment at a time.
"""

from datetime import datetime, timezone

import pytest

# Submodule guard, per tests/test_migrate.py.
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi.routing")

from sqlalchemy import create_engine, select, text

from app.api import map_layers, open311
from app.models import ServiceRequest
from app.schemas import PublicRequestCommentResponse


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _AnyRow:
    """A row stand-in with the one attribute the lookups dereference."""

    id = 1
    service_request_id = "REQ-1"


def _handler(fn):
    """The handler body without slowapi's decorator wrapper.

    The decorator wants a real starlette Request; the rate limits themselves
    are covered in tests/test_rate_limits_actually_apply.py.
    """
    return getattr(fn, "__wrapped__", fn)


class _Db:
    def __init__(self, answers=None, explode=False):
        self.answers = list(answers or [])
        self.added = []
        self.explode = explode

    async def execute(self, _statement):
        if self.explode:
            raise RuntimeError("settings read hiccuped")
        return _Result(self.answers.pop(0) if self.answers else [])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj, attrs=None):
        # A real session assigns the primary key on flush; nothing here does,
        # and the response model requires one.
        if getattr(obj, "id", "unset") is None:
            obj.id = 99


# ---------------------------------------------------------------------------
# staff names on the public tracker
# ---------------------------------------------------------------------------


class _Comment:
    def __init__(self, id, username, user_id, visibility="external"):
        self.id = id
        self.service_request_id = 1
        self.username = username
        self.user_id = user_id
        self.content = "We have scheduled this for Tuesday."
        self.visibility = visibility
        self.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.updated_at = None


def _staff_comment():
    return _Comment(1, "jane.mcallister", 42)


def _resident_comment():
    return _Comment(2, "Resident", None)


@pytest.mark.asyncio
async def test_the_public_comments_endpoint_does_not_name_staff():
    """The confirmed-live leak."""
    db = _Db([[_AnyRow()], [_staff_comment()]])
    published = await open311.get_public_comments(request_id="REQ-1", db=db)
    assert [c.username for c in published] == ["Staff"]


@pytest.mark.asyncio
async def test_the_public_comments_endpoint_does_not_expose_a_staff_user_id():
    """The internal id is what makes "Staff" re-identifiable across reports."""
    db = _Db([[_AnyRow()], [_staff_comment()]])
    published = await open311.get_public_comments(request_id="REQ-1", db=db)
    payload = published[0].model_dump()
    assert "user_id" not in payload
    assert "jane.mcallister" not in str(payload)


@pytest.mark.asyncio
async def test_a_residents_own_comment_still_reads_as_a_resident():
    """Redaction must not turn the resident's own words into "Staff"."""
    db = _Db([[_AnyRow()], [_resident_comment()]])
    published = await open311.get_public_comments(request_id="REQ-1", db=db)
    assert published[0].username == "Resident"


@pytest.mark.asyncio
async def test_the_comment_text_still_reaches_the_resident():
    """The endpoint has a job; redacting the body would be a different bug."""
    db = _Db([[_AnyRow()], [_staff_comment()]])
    published = await open311.get_public_comments(request_id="REQ-1", db=db)
    assert published[0].content == "We have scheduled this for Tuesday."


def test_a_staffer_named_resident_cannot_pass_as_one():
    """Redaction keys on user_id, not on the stored name.

    A row written by a signed-in user is a staff row whatever it is labelled,
    and the label is user-controlled in a way the id is not.
    """
    impostor = _Comment(3, "Resident", 42)
    assert PublicRequestCommentResponse.redacted(impostor).username == "Staff"


def test_the_staff_view_still_names_the_author():
    """Staff must still see who said what; this was never the problem."""
    from app.schemas import RequestCommentResponse

    assert "username" in RequestCommentResponse.model_fields
    assert "user_id" in RequestCommentResponse.model_fields


def test_the_public_comment_schema_has_no_user_id_field_at_all():
    """Not filtered at the call site -- absent from the shape.

    A field that exists can be populated by the next person to touch the
    endpoint; a field that does not exist cannot.
    """
    assert "user_id" not in PublicRequestCommentResponse.model_fields


# ---------------------------------------------------------------------------
# hidden map layers
# ---------------------------------------------------------------------------


class _Layer:
    def __init__(self, id=1, is_active=True, show_on_resident_portal=True):
        self.id = id
        self.name = "Draft redistricting overlay"
        self.is_active = is_active
        self.show_on_resident_portal = show_on_resident_portal


class _Admin:
    role = "admin"


class _Staff:
    role = "staff"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "layer",
    [
        _Layer(show_on_resident_portal=False),
        _Layer(is_active=False),
        _Layer(is_active=False, show_on_resident_portal=False),
    ],
)
async def test_an_anonymous_caller_cannot_read_a_hidden_layer(layer):
    """The reproduction: walk the integer ids and read what was not published."""
    with pytest.raises(Exception) as exc:
        await map_layers.get_layer(
            layer_id=layer.id, db=_Db([[layer]]), current_user=None
        )
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_a_hidden_layer_answers_404_not_403():
    """Confirming it exists is most of what the caller wanted."""
    with pytest.raises(Exception) as exc:
        await map_layers.get_layer(
            layer_id=9,
            db=_Db([[_Layer(show_on_resident_portal=False)]]),
            current_user=_Staff(),
        )
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_a_published_layer_is_still_public():
    """The resident portal fetches layers by id; breaking that breaks the map."""
    layer = _Layer()
    assert (
        await map_layers.get_layer(layer_id=1, db=_Db([[layer]]), current_user=None)
        is layer
    )


@pytest.mark.asyncio
async def test_an_admin_can_still_read_a_hidden_layer():
    """The admin console edits unpublished layers by id."""
    layer = _Layer(show_on_resident_portal=False)
    assert (
        await map_layers.get_layer(layer_id=1, db=_Db([[layer]]), current_user=_Admin())
        is layer
    )


@pytest.mark.asyncio
async def test_an_unreadable_token_is_treated_as_anonymous():
    """A broken credential must not be MORE privileged than none, or a 500."""

    class _Request:
        headers = {"authorization": "Bearer not-a-real-token"}

    user = await map_layers.get_current_user_optional(request=_Request(), db=_Db([[]]))
    assert user is None


# ---------------------------------------------------------------------------
# "keep this unlisted" must fail closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_settings_failure_keeps_an_unlisted_report_unlisted():
    """The reproduction: the read fails and the resident's answer is honoured.

    Publishing is not undoable -- once listed it can be read, scraped and
    cached -- while an unlisted report is one admin action away from correct.
    """
    assert await open311.resolve_is_public(_Db(explode=True), False) is False


@pytest.mark.asyncio
async def test_a_settings_failure_does_not_hide_a_report_nobody_asked_to_hide():
    """Failing closed must not blank the public map.

    Only a resident who asked for unlisted reaches the fallible read at all.
    """
    assert await open311.resolve_is_public(_Db(explode=True), True) is True
    assert await open311.resolve_is_public(_Db(explode=True), None) is True


@pytest.mark.asyncio
async def test_the_module_switch_still_governs_the_normal_path():
    """With the module off, a resident cannot opt out. Unchanged behaviour."""

    class _Off:
        modules = {"unlisted_reports": False}

    class _On:
        modules = {"unlisted_reports": True}

    assert await open311.resolve_is_public(_Db([[_Off()]]), False) is True
    assert await open311.resolve_is_public(_Db([[_On()]]), False) is False


# ---------------------------------------------------------------------------
# an anonymous comment cannot place a legal hold
# ---------------------------------------------------------------------------


class _Request:
    def __init__(self):
        self.client = type("C", (), {"host": "172.19.0.5"})()
        self.headers = {"x-forwarded-for": "203.0.113.7"}


class _Sr:
    def __init__(self):
        self.id = 1
        self.service_request_id = "REQ-1"
        self.flagged = False
        self.legal_hold = False
        self.flag_reason = None


class _Verdict:
    should_block = False
    flagged = True

    def reason(self):
        return "Auto-flagged: profanity"


@pytest.mark.asyncio
async def test_a_rude_public_comment_does_not_place_a_legal_hold(monkeypatch):
    """The reproduction, on the exact endpoint reachable without credentials."""
    sr = _Sr()
    db = _Db([[sr]])

    async def screen(_text):
        return _Verdict()

    monkeypatch.setattr("app.services.content_moderation.screen_text", screen)
    monkeypatch.setattr(open311, "enqueue", lambda *a, **k: True)

    await _handler(open311.add_public_comment)(
        request=_Request(), request_id="REQ-1", content="you lot are useless", db=db
    )

    assert sr.flagged is True, "moderation must still flag it for staff"
    assert sr.legal_hold is False, "an anonymous comment placed a legal hold"


@pytest.mark.asyncio
async def test_the_admin_toggle_is_what_places_a_legal_hold(monkeypatch):
    """The hold still has to be placeable, by the one role allowed to place it."""
    monkeypatch.setattr(open311, "enqueue", lambda *a, **k: True)

    class _Row:
        id = 1
        service_request_id = "REQ-1"
        status = "open"
        flagged = False
        legal_hold = False
        assigned_department_id = None
        assigned_department = None
        assigned_to = None
        updated_datetime = None

    class _Update:
        def __init__(self, **f):
            self._f = f

        def model_dump(self, exclude_unset=True):
            return dict(self._f)

    class _Admin2:
        id = 2
        role = "admin"
        username = "the.admin"

    row = _Row()
    db = _Db([[row]])
    await open311.update_request_status(
        request_id="REQ-1",
        update_data=_Update(flagged=True),
        db=db,
        current_user=_Admin2(),
    )
    assert row.legal_hold is True
    assert [e.action for e in db.added if e.action == "legal_hold"] == ["legal_hold"]


@pytest.mark.asyncio
async def test_a_non_admin_still_cannot_touch_the_hold():
    class _Update:
        def model_dump(self, exclude_unset=True):
            return {"legal_hold": True}

    class _Staff2:
        id = 3
        role = "staff"
        username = "clerk"

    with pytest.raises(Exception) as exc:
        await open311.update_request_status(
            request_id="REQ-1",
            update_data=_Update(),
            db=_Db([[(1,)], [_AnyRow()]]),
            current_user=_Staff2(),
        )
    assert getattr(exc.value, "status_code", None) == 403


# ---------------------------------------------------------------------------
# and retention reads the hold, not the moderation flag
# ---------------------------------------------------------------------------

_RETENTION_SCHEMA = """
CREATE TABLE service_requests (
    id INTEGER PRIMARY KEY,
    status VARCHAR(20),
    closed_datetime DATETIME,
    archived_at DATETIME,
    deleted_at DATETIME,
    flagged BOOLEAN NOT NULL DEFAULT 0,
    legal_hold BOOLEAN NOT NULL DEFAULT 0
)
"""


def _eligible(rows):
    """Ids a retention run would act on, decided by a real database.

    The eligibility clause is imported from the service rather than retyped, so
    a revert there changes what this executes.
    """
    from datetime import timedelta

    from app.services.retention_service import get_records_for_archival  # noqa: F401
    from app.services.retention_window import retention_cutoff

    cutoff = retention_cutoff(30)
    old = cutoff - timedelta(days=365)

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(_RETENTION_SCHEMA))
        for row in rows:
            full = {
                "id": None, "status": "closed", "closed_datetime": old,
                "archived_at": None, "deleted_at": None, "flagged": False,
                "legal_hold": False, **row,
            }
            conn.execute(
                text(
                    "INSERT INTO service_requests "
                    "(id, status, closed_datetime, archived_at, deleted_at, "
                    "flagged, legal_hold) VALUES (:id, :status, :closed_datetime, "
                    ":archived_at, :deleted_at, :flagged, :legal_hold)"
                ),
                full,
            )

    with engine.connect() as conn:
        query = select(ServiceRequest.id).where(*_eligibility_clauses(cutoff))
        return {row[0] for row in conn.execute(query).all()}


def _eligibility_clauses(cutoff):
    """The clauses `get_records_for_archival` builds, captured from the service.

    Taken by running the real function against a recording session, so this
    cannot drift from what retention actually asks for.
    """
    import asyncio

    from app.services.retention_service import get_records_for_archival

    captured = {}

    class _Recorder:
        async def execute(self, statement):
            captured["where"] = statement.whereclause

            class _R:
                def scalars(self_inner):
                    return self_inner

                def all(self_inner):
                    return []

            return _R()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        get_records_for_archival(_Recorder(), 30)
    )
    return (captured["where"],)


def test_a_moderation_flag_no_longer_exempts_a_record_from_retention():
    """The whole point: the stranger's comment must not stop the scrub.

    Before this split, id 2 below was excluded from every retention run
    forever, so a resident's name, email, phone and address stayed on file
    indefinitely because somebody swore at them.
    """
    eligible = _eligible([
        {"id": 1},
        {"id": 2, "flagged": True},
        {"id": 3, "legal_hold": True},
    ])
    assert 2 in eligible


def test_a_real_legal_hold_still_stops_the_scrub():
    """The protection that must keep working: a held record is never touched."""
    eligible = _eligible([{"id": 1}, {"id": 3, "legal_hold": True}])
    assert 3 not in eligible
    assert 1 in eligible


def test_retention_never_reads_the_moderation_flag_again():
    """Four call sites read `flagged` as the hold; none may remain.

    Structural because the risk is a MISSED site rather than a wrong rule --
    one leftover `flagged == False` and the anonymous hold is back on whichever
    path it guards.
    """
    import inspect

    from app.services import retention_service

    offenders = [
        line.strip()
        for line in inspect.getsource(retention_service).splitlines()
        if "ServiceRequest.flagged" in line or "record.flagged" in line
    ]
    assert offenders == [], offenders


def test_the_admin_hold_list_reads_the_hold_column():
    import inspect

    from app.api import system

    source = inspect.getsource(system.get_legal_hold_requests)
    assert "ServiceRequest.legal_hold" in source
    assert "ServiceRequest.flagged" not in source


def test_the_two_meanings_are_two_columns():
    """The root cause, asserted on the model."""
    columns = ServiceRequest.__table__.columns
    assert "flagged" in columns
    assert "legal_hold" in columns
