"""Staff assignment: who a request goes to, and what changing that does.

An audit of the assignment controls found:

  1. Changing a request's department kept the previous assignee. The staff
     picker is filtered to the new department, so the old person vanished from
     view but was still sent, and the server stored a Roads request assigned
     to a Parks clerk. The server now refuses (400) any department/assignee
     change that leaves an assignee outside the request's department.
  2. PUT /requests/{id}/status accepted unknown and deactivated users,
     researcher accounts, and department ids that do not exist (that last one
     a foreign-key 500). It now answers 400, with the same checks manual
     intake already used.
  3. Unassigning stored '' rather than NULL.
  4. Reassignment notified nobody. It now tells the new assignee, or the new
     department's staff, through each person's Notification Settings.
  5. Routing on create used staff_ids[0] blindly and filed reports into a
     retired department.
  6. Unassigning was not audited, and neither was the initial routing.
  7. A category's department could not be cleared.
"""

import types

import pytest

# Submodule guards, per tests/test_migrate.py: CI installs only a handful of
# packages, and a guard on a bare namespace name passes silently.
pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("fastapi.routing")
pytest.importorskip("pydantic")

from fastapi import HTTPException  # noqa: E402

from app.api import open311  # noqa: E402
from app.models import Department, ServiceDefinition, ServiceRequest, User  # noqa: E402
from app.services.notification_rules import (  # noqa: E402
    pick_assignment_recipients,
    should_notify_staff,
)


# ---------------------------------------------------------------------------
# a fake session that answers by what is asked, not by call order
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._rows[0]

    def scalar(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _param_values(stmt):
    values = []
    for value in stmt.compile().params.values():
        if isinstance(value, (list, tuple)):
            values.extend(value)
        else:
            values.append(value)
    return values


class _DB:
    """Rows for the four things the assignment code asks about: the request,
    departments (by id), users (by username or id) and memberships."""

    def __init__(self, *, request=None, departments=(), users=(), memberships=()):
        self.request = request
        self.departments = list(departments)
        self.users = list(users)
        self.memberships = set(memberships)  # {(user_id, department_id)}
        self.added = []

    async def execute(self, stmt):
        desc = stmt.column_descriptions[0]
        entity = desc.get("entity")
        params = _param_values(stmt)
        if entity is ServiceRequest and desc.get("name") == "ServiceRequest":
            return _Result([self.request] if self.request else [])
        if entity is Department and desc.get("name") == "Department":
            return _Result([d for d in self.departments if d.id in params])
        if entity is User and desc.get("name") == "User":
            return _Result([u for u in self.users if u.username in params or u.id in params])
        if entity is None and desc.get("name") == "user_id":
            user_id, dept_id = params
            return _Result([user_id] if (user_id, dept_id) in self.memberships else [])
        return _Result([])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj, attrs=None):
        pass


def _row(**kw):
    defaults = dict(
        id=1, service_request_id="REQ-1", service_code="pothole", status="open",
        assigned_department_id=None, assigned_department=None, assigned_to=None,
        flagged=False, legal_hold=False, manual_priority_score=None, ai_analysis=None,
        deleted_at=None, updated_datetime=None, requested_datetime=None,
        closed_datetime=None,
    )
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


def _dept(id, name, is_active=True):
    return types.SimpleNamespace(id=id, name=name, is_active=is_active, routing_email=None)


def _user(id, username, role="staff", is_active=True):
    return types.SimpleNamespace(id=id, username=username, role=role, is_active=is_active)


ROADS, PARKS = _dept(1, "Roads"), _dept(2, "Parks")
RETIRED = _dept(3, "Old Works", is_active=False)
ANN = _user(10, "roads.ann")       # Roads
BOB = _user(11, "parks.bob")       # Parks
CY = _user(12, "both.cy")          # Roads and Parks
RESEARCHER = _user(13, "res.rita", role="researcher")
GONE = _user(14, "gone.gus", is_active=False)
ADMIN = _user(99, "the.admin", role="admin")
MEMBERS = {(10, 1), (11, 2), (12, 1), (12, 2), (13, 2), (14, 2)}


class _Update:
    """A ServiceRequestUpdate stand-in: only what was explicitly sent."""

    def __init__(self, **fields):
        self._fields = fields

    def model_dump(self, exclude_unset=True):
        return dict(self._fields)


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(open311, "enqueue", lambda task, *a, **k: calls.append((task, a, k)) or True)
    return calls


def _db(row):
    return _DB(request=row, departments=[ROADS, PARKS, RETIRED],
               users=[ANN, BOB, CY, RESEARCHER, GONE, ADMIN], memberships=MEMBERS)


async def _put(db, actor=ADMIN, **fields):
    return await open311.update_request_status(
        request_id="REQ-1", update_data=_Update(**fields), db=db, current_user=actor)


def _assignment_tasks(calls):
    from app.tasks.service_requests import notify_staff_of_assignment
    return [c for c in calls if c[0] is notify_staff_of_assignment]


# ---------------------------------------------------------------------------
# 1. the assignee must belong to the request's department
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_moving_department_with_the_old_assignee_is_refused(sent):
    """The reproduction: Roads -> Parks, Ann (Roads only) left in place."""
    row = _row(assigned_department_id=1, assigned_to="roads.ann")
    with pytest.raises(HTTPException) as exc:
        await _put(_db(row), assigned_department_id=2)
    assert exc.value.status_code == 400
    assert "roads.ann" in exc.value.detail and "Parks" in exc.value.detail
    assert (row.assigned_department_id, row.assigned_to) == (1, "roads.ann")


@pytest.mark.asyncio
async def test_moving_department_and_sending_the_old_assignee_is_refused(sent):
    """What the dashboard used to send: both fields, the assignee unchanged."""
    row = _row(assigned_department_id=1, assigned_to="roads.ann")
    with pytest.raises(HTTPException) as exc:
        await _put(_db(row), assigned_department_id=2, assigned_to="roads.ann")
    assert exc.value.status_code == 400
    assert row.assigned_department_id == 1


@pytest.mark.asyncio
async def test_moving_department_with_a_member_of_it_is_accepted(sent):
    row = _row(assigned_department_id=1, assigned_to="roads.ann")
    await _put(_db(row), assigned_department_id=2, assigned_to="parks.bob")
    assert (row.assigned_department_id, row.assigned_to) == (2, "parks.bob")


@pytest.mark.asyncio
async def test_moving_department_keeps_an_assignee_who_is_in_both(sent):
    row = _row(assigned_department_id=1, assigned_to="both.cy")
    await _put(_db(row), assigned_department_id=2)
    assert (row.assigned_department_id, row.assigned_to) == (2, "both.cy")


@pytest.mark.asyncio
async def test_moving_department_and_unassigning_is_accepted(sent):
    row = _row(assigned_department_id=1, assigned_to="roads.ann")
    await _put(_db(row), assigned_department_id=2, assigned_to=None)
    assert (row.assigned_department_id, row.assigned_to) == (2, None)


@pytest.mark.asyncio
async def test_assigning_someone_outside_the_current_department_is_refused(sent):
    row = _row(assigned_department_id=1)
    with pytest.raises(HTTPException) as exc:
        await _put(_db(row), assigned_to="parks.bob")
    assert exc.value.status_code == 400
    assert row.assigned_to is None


@pytest.mark.asyncio
async def test_without_a_department_anyone_active_may_be_assigned(sent):
    row = _row()
    await _put(_db(row), assigned_to="parks.bob")
    assert row.assigned_to == "parks.bob"


@pytest.mark.asyncio
async def test_resending_an_unchanged_pair_is_not_rechecked(sent):
    """A pair stored before these rules (Ann on a Parks request) is not
    something a status change or a re-save should suddenly refuse."""
    row = _row(assigned_department_id=2, assigned_to="roads.ann")
    await _put(_db(row), assigned_department_id=2, assigned_to="roads.ann", status=None)
    assert (row.assigned_department_id, row.assigned_to) == (2, "roads.ann")


# ---------------------------------------------------------------------------
# 2. the choices themselves are validated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("username", ["nobody", "res.rita", "gone.gus"])
async def test_an_assignee_who_cannot_work_the_request_is_a_400(sent, username):
    row = _row()
    with pytest.raises(HTTPException) as exc:
        await _put(_db(row), assigned_to=username)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Assign the request to an active staff member."
    assert row.assigned_to is None


@pytest.mark.asyncio
@pytest.mark.parametrize("dept_id", [404, 3])
async def test_a_missing_or_retired_department_is_a_400_not_a_500(sent, dept_id):
    row = _row(assigned_department_id=1)
    with pytest.raises(HTTPException) as exc:
        await _put(_db(row), assigned_department_id=dept_id)
    assert exc.value.status_code == 400
    assert row.assigned_department_id == 1


@pytest.mark.asyncio
async def test_an_admin_can_be_assigned(sent):
    row = _row()
    await _put(_db(row), actor=ANN, assigned_to="the.admin")
    assert row.assigned_to == "the.admin"


# ---------------------------------------------------------------------------
# 3. clearing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "   ", None])
async def test_unassigning_stores_null(sent, value):
    row = _row(assigned_to="roads.ann")
    await _put(_db(row), assigned_to=value)
    assert row.assigned_to is None


@pytest.mark.asyncio
async def test_a_department_can_be_cleared_with_its_assignee_left_in_place(sent):
    """No department means anyone may hold it, so the assignee stays."""
    row = _row(assigned_department_id=1, assigned_to="roads.ann", assigned_department=ROADS)
    await _put(_db(row), assigned_department_id=None, assigned_to="roads.ann")
    assert (row.assigned_department_id, row.assigned_to) == (None, "roads.ann")
    assert row.assigned_department is None


# ---------------------------------------------------------------------------
# 4. reassignment notifies the new owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_new_assignee_is_notified_and_the_actor_is_named(sent):
    row = _row(assigned_department_id=1)
    await _put(_db(row), assigned_to="both.cy")
    tasks = _assignment_tasks(sent)
    assert len(tasks) == 1
    assert tasks[0][1] == (1,)
    assert tasks[0][2] == {"actor": "the.admin"}


@pytest.mark.asyncio
async def test_a_new_department_with_nobody_named_is_notified(sent):
    row = _row(assigned_department_id=1)
    await _put(_db(row), assigned_department_id=2)
    assert len(_assignment_tasks(sent)) == 1


@pytest.mark.asyncio
async def test_unassigning_notifies_nobody(sent):
    row = _row(assigned_department_id=1, assigned_to="roads.ann")
    await _put(_db(row), assigned_to=None)
    assert _assignment_tasks(sent) == []


@pytest.mark.asyncio
async def test_a_status_change_alone_is_not_a_reassignment(sent):
    row = _row(assigned_department_id=1, assigned_to="roads.ann")
    await _put(_db(row), assigned_department_id=1, assigned_to="roads.ann")
    assert _assignment_tasks(sent) == []


@pytest.mark.asyncio
async def test_residents_are_not_told_about_reassignment(sent):
    from app.tasks.service_requests import send_branded_notification
    row = _row(assigned_department_id=1)
    await _put(_db(row), assigned_department_id=2, assigned_to="parks.bob")
    assert not [c for c in sent if c[0] is send_branded_notification]


def test_recipients_are_the_assignee_else_the_department():
    assert pick_assignment_recipients(ANN, [BOB, CY]) == [ANN]
    assert pick_assignment_recipients(None, [BOB, CY]) == [BOB, CY]
    # No admin fallback: whoever reassigned it is already looking at it.
    assert pick_assignment_recipients(None, []) == []


def test_assignment_follows_the_new_request_toggles():
    assert should_notify_staff({}, "assignments", is_assigned_to_me=True) == (True, False)
    assert should_notify_staff({"email_new_requests": False}, "assignments",
                               is_assigned_to_me=True) == (False, False)
    assert should_notify_staff({"sms_new_requests": True}, "assignments",
                               is_assigned_to_me=True, sms_enabled_globally=True) == (True, True)


def test_assignment_respects_assigned_only_and_skips_the_actor():
    prefs = {"email_assigned_only": True}
    assert should_notify_staff(prefs, "assignments", is_assigned_to_me=False) == (False, False)
    assert should_notify_staff(prefs, "assignments", is_assigned_to_me=True) == (True, False)
    assert should_notify_staff({}, "assignments", is_assigned_to_me=True, is_actor=True) == (False, False)


def test_the_assignment_worker_notifies_the_right_people(monkeypatch):
    """The task end to end against a fake session: department staff when
    nobody is named, the actor skipped, preferences applied."""
    pytest.importorskip("celery.app")
    import app.tasks.service_requests as tasks
    from app.services import capability_switches

    row = _row(assigned_department_id=2, service_name="Pothole", address="1 Main St")
    staff = [
        types.SimpleNamespace(id=11, username="parks.bob", email="bob@town.test", phone=None,
                              notification_preferences={}),
        types.SimpleNamespace(id=12, username="both.cy", email="cy@town.test", phone=None,
                              notification_preferences={"email_new_requests": False}),
        types.SimpleNamespace(id=99, username="the.admin", email="admin@town.test", phone=None,
                              notification_preferences={}),
    ]

    class _TaskDB(_DB):
        async def execute(self, stmt):
            desc = stmt.column_descriptions[0]
            if desc.get("entity") is User and "user_departments" in str(stmt):
                return _Result(staff)
            return await super().execute(stmt)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    db = _TaskDB(request=row, departments=[PARKS])
    emails = []

    async def _noop(*a, **k):
        return None

    async def _sms_off(name):
        return False

    async def _portal(db):
        return "https://town.test"

    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(tasks, "configure_notifications", _noop)
    monkeypatch.setattr(tasks, "_portal_url", _portal)
    monkeypatch.setattr(capability_switches, "enabled", _sms_off)
    monkeypatch.setattr(tasks, "run_async", lambda coro: __import__("asyncio").run(coro))
    monkeypatch.setattr(tasks.notification_service, "send_email",
                        lambda to, subject, **k: emails.append((to, subject)))

    out = tasks.notify_staff_of_assignment(1, actor="the.admin")

    assert out["status"] == "sent", out
    assert [to for to, _ in emails] == ["bob@town.test"]
    assert emails[0][1].startswith("Assigned to Parks")


# ---------------------------------------------------------------------------
# 5. routing on create
# ---------------------------------------------------------------------------


def _service(dept_id=1, staff_ids=None):
    config = {"route_to": "specific_staff", "staff_ids": staff_ids} if staff_ids is not None else None
    return types.SimpleNamespace(assigned_department_id=dept_id, routing_config=config)


def _routing_db():
    return _DB(departments=[ROADS, PARKS, RETIRED],
               users=[ANN, BOB, CY, RESEARCHER, GONE, ADMIN], memberships=MEMBERS)


@pytest.mark.asyncio
async def test_routing_without_staff_uses_the_category_department():
    assert await open311._resolve_assignment(_routing_db(), _service(1)) == (
        1, None, "category_department")


@pytest.mark.asyncio
async def test_routing_to_a_retired_department_falls_back_to_triage():
    assert await open311._resolve_assignment(_routing_db(), _service(3)) == (None, None, "none")
    assert await open311._resolve_assignment(_routing_db(), _service(404)) == (None, None, "none")


@pytest.mark.asyncio
async def test_routing_picks_the_first_person_who_can_work_it():
    """Deactivated, researcher and not-in-the-department are all skipped, in
    the saved order; Cy (Parks member) is the first who qualifies."""
    service = _service(2, staff_ids=[GONE.id, RESEARCHER.id, ANN.id, CY.id, BOB.id])
    assert await open311._resolve_assignment(_routing_db(), service) == (
        2, "both.cy", "routing_rule_staff")


@pytest.mark.asyncio
async def test_routing_keeps_the_first_pick_when_it_is_fine():
    service = _service(1, staff_ids=[ANN.id, CY.id])
    assert (await open311._resolve_assignment(_routing_db(), service))[1] == "roads.ann"


@pytest.mark.asyncio
async def test_routing_without_a_department_needs_no_membership():
    service = _service(None, staff_ids=[BOB.id])
    assert await open311._resolve_assignment(_routing_db(), service) == (
        None, "parks.bob", "routing_rule_staff")


@pytest.mark.asyncio
async def test_routing_with_nobody_eligible_leaves_it_with_the_department():
    service = _service(1, staff_ids=[GONE.id, BOB.id])
    assert await open311._resolve_assignment(_routing_db(), service) == (
        1, None, "category_department")


# ---------------------------------------------------------------------------
# 6. the audit trail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unassigning_is_audited(sent):
    row = _row(assigned_to="roads.ann")
    db = _db(row)
    await _put(db, assigned_to="")
    entries = [e for e in db.added if e.action == "staff_assigned"]
    assert len(entries) == 1
    assert (entries[0].old_value, entries[0].new_value) == ("roads.ann", None)


@pytest.mark.asyncio
async def test_an_unchanged_assignee_is_not_audited(sent):
    row = _row(assigned_to="roads.ann")
    db = _db(row)
    await _put(db, assigned_to="roads.ann")
    assert not [e for e in db.added if e.action == "staff_assigned"]


def test_the_routing_record_stays_off_the_public_audit_log():
    entry = types.SimpleNamespace(action="submitted", extra_data={
        "routing": open311._routing_audit(1, "roads.ann", "routing_rule_staff")})
    assert open311._public_audit_extra(entry) is None


def test_the_resident_path_records_the_routing():
    """The resident intake is too entangled to drive here (PostGIS, GIS layers, the
    photo pipeline); the wiring is checked on its source instead."""
    import inspect
    source = inspect.getsource(open311._intake_resident_report)
    resolve = source.index("await _resolve_assignment(db, service)")
    assert '"routing": _routing_audit(' in source[resolve:]
    assert "audit_extra=audit_extra" in source[resolve:]


# ---------------------------------------------------------------------------
# 7. a category's department can be cleared
# ---------------------------------------------------------------------------


def _service_row(**kw):
    defaults = dict(
        id=5, service_code="pothole", service_name="Pothole", description=None, icon=None,
        is_active=True, routing_mode="township", routing_config={}, assigned_department_id=1,
        display_order=0, sla_hours=None, location_mode="optional", hidden_from_public=False,
    )
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


class _ServiceDB(_DB):
    def __init__(self, service, departments=()):
        super().__init__(departments=departments)
        self.service = service

    async def execute(self, stmt):
        desc = stmt.column_descriptions[0]
        if desc.get("entity") is ServiceDefinition:
            return _Result([self.service])
        return await super().execute(stmt)


@pytest.fixture
def no_admin_audit(monkeypatch):
    from app.api import services

    async def _record(*a, **k):
        return None

    monkeypatch.setattr(services, "record_admin_action", _record)


@pytest.mark.asyncio
async def test_an_explicit_null_clears_the_category_department(no_admin_audit):
    from app.api import services
    from app.schemas import ServiceUpdate
    service = _service_row()
    await services.update_service(service_id=5, service_data=ServiceUpdate(assigned_department_id=None),
                                  db=_ServiceDB(service), _=ADMIN)
    assert service.assigned_department_id is None


@pytest.mark.asyncio
async def test_leaving_the_department_out_leaves_it_alone(no_admin_audit):
    from app.api import services
    from app.schemas import ServiceUpdate
    service = _service_row()
    await services.update_service(service_id=5, service_data=ServiceUpdate(icon="road"),
                                  db=_ServiceDB(service), _=ADMIN)
    assert service.assigned_department_id == 1


@pytest.mark.asyncio
async def test_a_category_department_that_does_not_exist_is_a_400(no_admin_audit):
    from app.api import services
    from app.schemas import ServiceUpdate
    service = _service_row()
    with pytest.raises(HTTPException) as exc:
        await services.update_service(service_id=5,
                                      service_data=ServiceUpdate(assigned_department_id=404),
                                      db=_ServiceDB(service, departments=[ROADS]), _=ADMIN)
    assert exc.value.status_code == 400
    assert service.assigned_department_id == 1


@pytest.mark.asyncio
async def test_a_category_can_be_moved_to_another_department(no_admin_audit):
    from app.api import services
    from app.schemas import ServiceUpdate
    service = _service_row()
    await services.update_service(service_id=5, service_data=ServiceUpdate(assigned_department_id=2),
                                  db=_ServiceDB(service, departments=[ROADS, PARKS]), _=ADMIN)
    assert service.assigned_department_id == 2
