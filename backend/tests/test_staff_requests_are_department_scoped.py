"""A staffer may only reach the reports their department is working.

`GET /requests.json` has scoped its LIST by department for a while. None of the
by-id endpoints did. Every request id is printed on the public map, so a Parks
staffer could read one off the map and:

    GET /api/requests/REQ-20260601-AB12CD34.json

and receive the reporter's first name, last name, email, phone, the staff notes
and the moderation flag reason for a Police complaint -- then PUT its status,
DELETE it, and comment on it. The list endpoint was a curtain in front of an
open door, and the same door stood open in comments.py and integrations.py.

Two rules are pinned here, because they were tangled together:

  * DEPARTMENT SCOPE, now shared by the list and every by-id endpoint
    (app/api/scoping.py) rather than written out once and forgotten elsewhere.

  * WHICH ENDPOINTS SEE DELETED ROWS. `direct_link_filters()` -- written for the
    public tracker, where a deleted report must 404 -- had been folded into six
    staff endpoints. `restore_request` looked up its row with
    `deleted_at IS NULL`, so it 404'd unconditionally: a soft-deleted report
    could never be restored, the `if not request.deleted_at` check below it was
    unreachable, and the audit entry naming who deleted it could not be read
    either. Regression from 64209c7.

The scope rule itself is exercised against a real SQLite database doing the
comparison, rather than this file agreeing with itself about SQL. The query
composition inside `scoped_request` is asserted on the statement the handler
actually builds -- that IS the thing that was wrong, and it is what a revert
would change.
"""

from datetime import datetime, timezone

import pytest

# Submodule guard, per tests/test_migrate.py: CI installs only cryptography,
# httpx, pytest, pytest-asyncio and alembic, and a bare guard on a name that
# resolves as a namespace package passes silently and skips the whole file.
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi.routing")

from sqlalchemy import create_engine, select, text

from app.api import comments as comments_api
from app.api import integrations as integrations_api
from app.api import open311
from app.api.scoping import department_scope_filters, scoped_request
from app.models import ServiceRequest


# ---------------------------------------------------------------------------
# a real database, with only the columns the scope rule touches
# ---------------------------------------------------------------------------
#
# Not ServiceRequest.__table__.create(): the table carries a PostGIS geometry
# column SQLite cannot make. The rule compiles to a SELECT over exactly these
# four columns, so this is the whole surface under test. Same approach as
# tests/test_public_archival.py.

_SCHEMA = """
CREATE TABLE service_requests (
    id INTEGER PRIMARY KEY,
    service_request_id VARCHAR(50),
    assigned_department_id INTEGER,
    assigned_to VARCHAR(100),
    deleted_at DATETIME
);
CREATE TABLE user_departments (
    user_id INTEGER,
    department_id INTEGER
);
"""

PARKS, POLICE = 1, 2


class _User:
    def __init__(self, id, username, role="staff"):
        self.id = id
        self.username = username
        self.role = role


PARKS_STAFF = _User(10, "parks.clerk")
ADMIN = _User(11, "the.admin", role="admin")


ROWS = [
    {"id": 1, "service_request_id": "REQ-PARKS", "assigned_department_id": PARKS},
    {"id": 2, "service_request_id": "REQ-POLICE", "assigned_department_id": POLICE},
    {"id": 3, "service_request_id": "REQ-UNROUTED", "assigned_department_id": None},
    {
        "id": 4,
        "service_request_id": "REQ-MINE",
        "assigned_department_id": POLICE,
        "assigned_to": "parks.clerk",
    },
    {
        "id": 5,
        "service_request_id": "REQ-POLICE-DELETED",
        "assigned_department_id": POLICE,
        "deleted_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    },
]


def _engine(memberships):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for statement in _SCHEMA.strip().split(";"):
            if statement.strip():
                conn.execute(text(statement))
        for row in ROWS:
            full = {
                "id": None, "service_request_id": None,
                "assigned_department_id": None, "assigned_to": None,
                "deleted_at": None, **row,
            }
            conn.execute(
                text(
                    "INSERT INTO service_requests "
                    "(id, service_request_id, assigned_department_id, assigned_to, deleted_at) "
                    "VALUES (:id, :service_request_id, :assigned_department_id, "
                    ":assigned_to, :deleted_at)"
                ),
                full,
            )
        for user_id, dept_id in memberships:
            conn.execute(
                text(
                    "INSERT INTO user_departments (user_id, department_id) "
                    "VALUES (:u, :d)"
                ),
                {"u": user_id, "d": dept_id},
            )
    return engine


class _SyncSession:
    """An AsyncSession-shaped wrapper over a real synchronous connection."""

    def __init__(self, conn):
        self._conn = conn

    async def execute(self, statement):
        return self._conn.execute(statement)


async def _visible(memberships, user):
    engine = _engine(memberships)
    with engine.connect() as conn:
        db = _SyncSession(conn)
        query = select(ServiceRequest.service_request_id).where(
            ServiceRequest.deleted_at.is_(None)
        )
        for clause in await department_scope_filters(db, user):
            query = query.where(clause)
        return {row[0] for row in conn.execute(query).all()}


# ---------------------------------------------------------------------------
# the scope rule, decided by a database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_staffer_cannot_see_another_departments_report():
    """The disclosure at the heart of the finding."""
    visible = await _visible([(PARKS_STAFF.id, PARKS)], PARKS_STAFF)
    assert "REQ-POLICE" not in visible


@pytest.mark.asyncio
async def test_a_staffer_sees_their_own_departments_work():
    """A scope that hides the staffer's own queue would be a different bug."""
    visible = await _visible([(PARKS_STAFF.id, PARKS)], PARKS_STAFF)
    assert "REQ-PARKS" in visible


@pytest.mark.asyncio
async def test_unrouted_reports_stay_visible_to_everyone():
    """Nobody has routed it yet, so it is everyone's to triage.

    The list endpoint has always allowed this and the by-id rule must match it
    exactly -- tightening here would silently break triage.
    """
    visible = await _visible([(PARKS_STAFF.id, PARKS)], PARKS_STAFF)
    assert "REQ-UNROUTED" in visible


@pytest.mark.asyncio
async def test_a_report_assigned_to_you_by_name_stays_visible():
    """Even when it belongs to another department: somebody asked you to work it."""
    visible = await _visible([(PARKS_STAFF.id, PARKS)], PARKS_STAFF)
    assert "REQ-MINE" in visible


@pytest.mark.asyncio
async def test_a_staffer_in_no_department_sees_only_triage_and_their_own():
    visible = await _visible([], PARKS_STAFF)
    assert visible == {"REQ-UNROUTED", "REQ-MINE"}


@pytest.mark.asyncio
async def test_an_admin_sees_everything():
    """Admins are exempt, matching the list endpoint's rule."""
    visible = await _visible([], ADMIN)
    assert visible == {"REQ-PARKS", "REQ-POLICE", "REQ-UNROUTED", "REQ-MINE"}


@pytest.mark.asyncio
async def test_the_admin_exemption_is_the_only_exemption():
    """A role that is not "admin" gets scoped, whatever it is called."""
    visible = await _visible([], _User(12, "someone", role="supervisor"))
    assert "REQ-POLICE" not in visible


# ---------------------------------------------------------------------------
# what the by-id endpoints actually query
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._rows[0] if self._rows else None


class _Recorder:
    """Captures the statements a handler builds, and answers with fixed rows."""

    def __init__(self, answers=None):
        self.statements = []
        self.answers = list(answers or [])
        self.added = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.answers.pop(0) if self.answers else [])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj, attrs=None):
        pass


def _sql(statement):
    """The WHERE clause only — the SELECT list names every column regardless."""
    return " ".join(str(statement.whereclause).split())


@pytest.mark.asyncio
async def test_scoped_request_scopes_by_department():
    db = _Recorder([[(PARKS,)], []])
    await scoped_request(db, PARKS_STAFF, service_request_id="REQ-POLICE")
    lookup = _sql(db.statements[-1])
    assert "assigned_department_id" in lookup
    assert "assigned_to" in lookup


@pytest.mark.asyncio
async def test_scoped_request_asks_for_no_scope_when_the_caller_is_an_admin():
    db = _Recorder([[]])
    await scoped_request(db, ADMIN, service_request_id="REQ-POLICE")
    assert "assigned_department_id" not in _sql(db.statements[-1])


@pytest.mark.asyncio
async def test_by_default_a_deleted_report_is_out_of_reach():
    db = _Recorder([[]])
    await scoped_request(db, ADMIN, service_request_id="REQ-X")
    assert "deleted_at IS NULL" in _sql(db.statements[-1])


@pytest.mark.asyncio
async def test_include_deleted_drops_that_clause():
    db = _Recorder([[]])
    await scoped_request(db, ADMIN, service_request_id="REQ-X", include_deleted=True)
    assert "deleted_at IS NULL" not in _sql(db.statements[-1])


# ---------------------------------------------------------------------------
# finding 6: the endpoints that must see a deleted row, and the ones that must not
# ---------------------------------------------------------------------------


class _Row:
    """A ServiceRequest stand-in carrying only what these handlers touch."""

    def __init__(self, **kw):
        self.id = 1
        self.service_request_id = "REQ-1"
        self.deleted_at = None
        self.deleted_by = None
        self.delete_justification = None
        self.updated_datetime = None
        self.ai_analysis = None
        self.manual_priority_score = None
        self.public_archived = False
        self.assigned_department_id = None
        self.assigned_department = None
        self.flagged = False
        self.legal_hold = False
        self.status = "open"
        self.assigned_to = None
        for key, value in kw.items():
            setattr(self, key, value)


DELETED = dict(
    deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    deleted_by="the.clerk",
    delete_justification="wrong report",
)


@pytest.mark.asyncio
async def test_a_soft_deleted_report_can_be_restored():
    """The reproduction. Before the fix this raised 404, always.

    A clerk who deleted the wrong report had no way to put it back and no way
    to read the entry recording that they had.
    """
    db = _Recorder([[_Row(**DELETED)]])
    result = await open311.restore_request(
        request_id="REQ-1", db=db, current_user=ADMIN
    )
    assert result["message"] == "Request restored"


@pytest.mark.asyncio
async def test_restore_actually_clears_the_deletion_and_leaves_a_trail():
    row = _Row(**DELETED)
    db = _Recorder([[row]])
    await open311.restore_request(request_id="REQ-1", db=db, current_user=ADMIN)
    assert row.deleted_at is None
    assert row.deleted_by is None
    assert row.delete_justification is None
    assert [entry.action for entry in db.added] == ["restored"]


@pytest.mark.asyncio
async def test_restore_looks_for_deleted_rows():
    """The bug was in the lookup, not in the body below it."""
    db = _Recorder([[_Row(**DELETED)]])
    await open311.restore_request(request_id="REQ-1", db=db, current_user=ADMIN)
    assert "deleted_at IS NULL" not in _sql(db.statements[0])


@pytest.mark.asyncio
async def test_restoring_something_that_is_not_deleted_is_still_refused():
    db = _Recorder([[_Row()]])
    with pytest.raises(Exception) as exc:
        await open311.restore_request(request_id="REQ-1", db=db, current_user=ADMIN)
    assert getattr(exc.value, "status_code", None) == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda db: open311.get_audit_log(request_id="REQ-1", db=db, current_user=ADMIN),
        lambda db: open311.verify_audit_log(request_id="REQ-1", db=db, current_user=ADMIN),
    ],
)
async def test_the_audit_trail_of_a_deleted_report_is_readable(call):
    """"Who deleted this, and why" is the question most likely to be asked.

    Both readers answered 404 the moment the delete landed.
    """
    db = _Recorder([[_Row(**DELETED)], []])
    await call(db)
    assert "deleted_at IS NULL" not in _sql(db.statements[0])


@pytest.mark.asyncio
async def test_deleting_an_already_deleted_report_says_so():
    """404 there reads as "no such report", which is a different problem."""
    db = _Recorder([[_Row(**DELETED)]])

    class _Justification:
        justification = "a good enough reason"

    with pytest.raises(Exception) as exc:
        await open311.delete_request(
            request_id="REQ-1", delete_data=_Justification(), db=db, current_user=ADMIN
        )
    assert getattr(exc.value, "status_code", None) == 400


@pytest.mark.asyncio
async def test_the_public_tracker_still_hides_deleted_reports():
    """The rule `direct_link_filters` was written for, unchanged.

    Loosening the staff side must not loosen the resident-facing side.
    """
    assert "deleted_at IS NULL" in _sql(
        select(ServiceRequest.id).where(*open311.direct_link_filters())
    )


# ---------------------------------------------------------------------------
# every staff by-id endpoint goes through the shared rule
# ---------------------------------------------------------------------------


BY_ID_STAFF_ENDPOINTS = [
    (open311, "get_request"),
    (open311, "update_request_status"),
    (open311, "set_public_archived"),
    (open311, "delete_request"),
    (open311, "restore_request"),
    (open311, "accept_ai_priority"),
    (open311, "get_audit_log"),
    (open311, "verify_audit_log"),
    (comments_api, "get_comments"),
    (comments_api, "create_comment"),
    (integrations_api, "refresh_request_work_order"),
    (integrations_api, "get_request_links"),
]


@pytest.mark.parametrize("module,name", BY_ID_STAFF_ENDPOINTS)
def test_every_by_id_staff_endpoint_uses_the_shared_scope(module, name):
    """No endpoint may fetch a request for a staff user on its own terms.

    Structural on purpose: the finding was not that one endpoint had the wrong
    rule, it was that twelve endpoints each had NO rule while the list had one.
    A thirteenth added tomorrow with its own `select(ServiceRequest).where(id)`
    is the same bug returning, and only a check shaped like this catches it.
    """
    import ast
    import inspect

    source = inspect.getsource(getattr(module, name))
    tree = ast.parse(inspect.cleandoc(source.split("\n", 0)[0]) if False else _dedent(source))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "scoped_request" in called, f"{name} fetches its request unscoped"


def _dedent(source: str) -> str:
    import textwrap

    return textwrap.dedent(source)


@pytest.mark.parametrize("module,name", BY_ID_STAFF_ENDPOINTS)
def test_no_by_id_staff_endpoint_takes_an_anonymous_staff_dependency(module, name):
    """A handler that binds the user to `_` cannot scope by them.

    Four of these did exactly that, which is why the scope could not have been
    applied even if someone had remembered to.
    """
    import inspect

    parameters = inspect.signature(getattr(module, name)).parameters
    assert "current_user" in parameters, f"{name} discards who is calling"


# ---------------------------------------------------------------------------
# finding 12: a report can be un-routed again
# ---------------------------------------------------------------------------


class _Update:
    """A ServiceRequestUpdate stand-in: only what was explicitly sent."""

    def __init__(self, **fields):
        self._fields = fields

    def model_dump(self, exclude_unset=True):
        return dict(self._fields)


@pytest.mark.asyncio
async def test_a_department_can_be_cleared(monkeypatch):
    """Selecting "Department..." used to return 200 and change nothing.

    Every null was skipped, so a misrouted report could never be un-routed and
    no audit entry was written -- the staffer watched the dropdown snap back
    with no error to report.
    """
    monkeypatch.setattr(open311, "enqueue", lambda *a, **k: True)
    row = _Row(assigned_department_id=7)
    db = _Recorder([[row]])
    await open311.update_request_status(
        request_id="REQ-1",
        update_data=_Update(assigned_department_id=None),
        db=db,
        current_user=ADMIN,
    )
    assert row.assigned_department_id is None


@pytest.mark.asyncio
async def test_clearing_a_department_is_written_to_the_audit_trail(monkeypatch):
    monkeypatch.setattr(open311, "enqueue", lambda *a, **k: True)

    class _Dept:
        name = "Parks"

    row = _Row(assigned_department_id=7, assigned_department=_Dept())
    db = _Recorder([[row]])
    await open311.update_request_status(
        request_id="REQ-1",
        update_data=_Update(assigned_department_id=None),
        db=db,
        current_user=ADMIN,
    )
    entries = [e for e in db.added if e.action == "department_assigned"]
    assert entries, "un-routing left no trace"
    assert entries[0].old_value == "Parks"
    assert entries[0].new_value is None


@pytest.mark.asyncio
async def test_an_assignee_can_be_cleared(monkeypatch):
    monkeypatch.setattr(open311, "enqueue", lambda *a, **k: True)
    row = _Row(assigned_to="someone")
    db = _Recorder([[row]])
    await open311.update_request_status(
        request_id="REQ-1",
        update_data=_Update(assigned_to=None),
        db=db,
        current_user=ADMIN,
    )
    assert row.assigned_to is None


@pytest.mark.asyncio
async def test_a_null_status_is_still_ignored(monkeypatch):
    """Only assignments treat null as a value.

    A null status is a malformed update, not an instruction to unset the
    status, and applying it would leave a report with no state at all.
    """
    monkeypatch.setattr(open311, "enqueue", lambda *a, **k: True)
    row = _Row(status="in_progress")
    db = _Recorder([[row]])
    await open311.update_request_status(
        request_id="REQ-1",
        update_data=_Update(status=None),
        db=db,
        current_user=ADMIN,
    )
    assert row.status == "in_progress"
