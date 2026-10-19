"""New staff accounts get an invite email.

An account nobody is told about is an account nobody uses. Creating a user now
queues an invite (asynchronously -- creation never waits on SMTP and never
fails because of it), "Resend invite" queues another, and the outcome lands in
the admin audit log as staff_invite_sent / staff_invite_failed with only the
account id and the address's domain.

The sign-in link is built from public_origin() and nothing else. With no
public address the message goes without a link rather than with a guessed one;
localhost in a staff member's inbox is a link that goes nowhere.

No real mail is sent anywhere in here: the transport is a stub.
"""

import inspect
import logging
import os
import tempfile

import pytest

from app.services import email_templates as T

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("aiosqlite")
pytest.importorskip("fastapi.routing")
models = pytest.importorskip("app.models")
schemas = pytest.importorskip("app.schemas")
users_api = pytest.importorskip("app.api.users")
staff_invite = pytest.importorskip("app.services.staff_invite")
auth_core = pytest.importorskip("app.core.auth")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

User = models.User
AuditLog = models.AuditLog

ORIGIN = "https://311.example-township.gov"


def _invite(**kw):
    args = dict(
        township_name="Example Township",
        logo_url="https://cdn.example.gov/logo.png",
        primary_color="#1d4ed8",
        invitee_email="jordan@example.gov",
        invitee_name="Jordan Lee",
        role="staff",
        department_names=["Public Works", "Parks"],
        invited_by="Sam Rivera",
        provider_name="Microsoft Entra ID",
        origin=ORIGIN,
    )
    args.update(kw)
    return T.build_staff_invite_email(**args)


# ---------------------------------------------------------------------------
# the message
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role,words,label", [
    ("admin", "an administrator", "Administrator"),
    ("staff", "a staff member", "Staff"),
    ("researcher", "a researcher", "Researcher"),
])
def test_the_role_is_in_plain_words(role, words, label):
    msg = _invite(role=role)
    for part in (msg["html"], msg["text"]):
        assert f"Sam Rivera added you as {words}." in part
        assert label in part
    assert "admin added you" not in msg["text"]


def test_it_names_the_town_the_departments_and_the_provider():
    msg = _invite()
    assert "Example Township" in msg["subject"]
    for part in (msg["html"], msg["text"]):
        assert "Public Works, Parks" in part
        assert "your Microsoft Entra ID account" in part
        assert "jordan@example.gov" in part
    # Branding from SystemSettings reaches the masthead, with alt text.
    assert 'src="https://cdn.example.gov/logo.png"' in msg["html"]
    assert 'alt="Example Township"' in msg["html"]


def test_no_departments_means_no_department_row():
    msg = _invite(department_names=[])
    assert "Department" not in msg["text"]


def test_the_sign_in_link_is_the_public_origin_login_page():
    msg = _invite()
    assert f'href="{ORIGIN}/login"' in msg["html"]
    assert f"{ORIGIN}/login" in msg["text"]
    assert "Sign in" in msg["html"]


@pytest.mark.parametrize("origin", [ORIGIN, None])
def test_there_is_no_localhost_anywhere(origin):
    msg = _invite(origin=origin)
    for part in (msg["subject"], msg["html"], msg["text"]):
        assert "localhost" not in part
        assert "127.0.0.1" not in part


@pytest.mark.parametrize("origin", [None, "", "javascript:alert(1)"])
def test_with_no_public_origin_there_is_no_link(origin):
    msg = _invite(origin=origin)
    assert "/login" not in msg["html"]
    assert "/login" not in msg["text"]
    assert "javascript:" not in msg["html"]
    assert "sign in at your township's 311 site" in msg["text"].replace("&#x27;", "'")


def test_no_inviter_or_provider_still_reads():
    msg = _invite(invited_by=None, provider_name=None, invitee_name=None)
    assert "An administrator added you as a staff member." in msg["text"]
    assert "your work account" in msg["text"]


def test_there_is_a_text_alternative():
    msg = _invite()
    assert msg["text"].strip()
    assert "<" not in msg["text"]


# ---------------------------------------------------------------------------
# database fixtures
# ---------------------------------------------------------------------------

TABLES = [
    User.__table__,
    models.Department.__table__,
    models.user_departments,
    models.SystemSettings.__table__,
    AuditLog.__table__,
    getattr(models, "AuditAnchor", None) and models.AuditAnchor.__table__,
]
TABLES = [t for t in TABLES if t is not None]


@pytest.fixture
async def maker():
    with tempfile.TemporaryDirectory() as d:
        engine = create_async_engine(f"sqlite+aiosqlite:///{os.path.join(d, 't.db')}", poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: models.Base.metadata.create_all(c, tables=TABLES))
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await engine.dispose()


class FakeTask:
    """Stands in for the Celery task. Records the call, or refuses it."""

    name = "app.tasks.staff_invites.send_staff_invite"

    def __init__(self, raises=None):
        self.raises = raises
        self.calls = []

    def delay(self, *args, **kwargs):
        if self.raises:
            raise self.raises
        self.calls.append(args)
        return "task-id"


@pytest.fixture
def task(monkeypatch):
    t = FakeTask()
    monkeypatch.setattr(staff_invite, "_task", lambda: t)
    return t


@pytest.fixture
def email_on(monkeypatch):
    async def on():
        return True
    monkeypatch.setattr(staff_invite, "_email_enabled", on)


@pytest.fixture
def email_off(monkeypatch):
    async def off():
        return False
    monkeypatch.setattr(staff_invite, "_email_enabled", off)


async def _admin(maker):
    async with maker() as db:
        a = User(username="boss", email="boss@example.gov", full_name="Sam Rivera",
                 role="admin", is_active=True)
        db.add(a)
        await db.commit()
        return a


async def _create(maker, admin, **kw):
    body = dict(username="jordan", email="jordan@example.gov", full_name="Jordan Lee", role="staff")
    body.update(kw)
    async with maker() as db:
        return await users_api.create_user(schemas.UserCreate(**body), db=db, _=admin)


async def _events(maker, prefix="staff_invite"):
    async with maker() as db:
        rows = (await db.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
        return [r for r in rows if r.event_type.startswith(prefix)]


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------


def test_send_invite_defaults_to_true():
    body = schemas.UserCreate(username="jordan", email="jordan@example.gov")
    assert body.send_invite is True


async def test_creating_a_user_queues_the_invite(maker, task, email_on):
    admin = await _admin(maker)
    created = await _create(maker, admin)
    assert created.invite == "queued"
    assert task.calls == [(created.id, admin.id)]


async def test_send_invite_false_queues_nothing(maker, task, email_on):
    admin = await _admin(maker)
    created = await _create(maker, admin, send_invite=False)
    assert created.invite == "not_requested"
    assert task.calls == []


async def test_email_off_queues_nothing_and_says_so(maker, task, email_off):
    admin = await _admin(maker)
    created = await _create(maker, admin)
    assert created.invite == "skipped_email_off"
    assert task.calls == []


@pytest.mark.parametrize("failure", [ConnectionRefusedError("redis down"), RuntimeError("kombu")])
async def test_creation_succeeds_when_queuing_raises(maker, monkeypatch, email_on, failure):
    monkeypatch.setattr(staff_invite, "_task", lambda: FakeTask(raises=failure))
    admin = await _admin(maker)
    created = await _create(maker, admin)
    assert created.invite == "queue_failed"
    async with maker() as db:
        assert (await db.execute(select(User).where(User.username == "jordan"))).scalar_one()
    [event] = await _events(maker)
    assert event.event_type == "staff_invite_failed" and event.success is False
    assert event.details == {"user_id": created.id, "email_domain": "example.gov"}


async def test_creation_succeeds_when_the_capability_check_itself_raises(maker, task, monkeypatch):
    async def boom():
        raise RuntimeError("secret store unreachable")
    monkeypatch.setattr(staff_invite, "_email_enabled", boom)
    admin = await _admin(maker)
    created = await _create(maker, admin)
    assert created.invite == "queue_failed"
    assert created.id


# ---------------------------------------------------------------------------
# POST /users/{id}/invite
# ---------------------------------------------------------------------------


def _route(path, method):
    for r in users_api.router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", ()):
            return r
    pytest.fail(f"no {method} {path}")


def test_resend_is_admin_only_and_rate_limited():
    route = _route("/{user_id}/invite", "POST")
    deps = [d.call for d in route.dependant.dependencies]
    assert auth_core.get_current_admin in deps
    assert auth_core.get_current_staff not in deps
    # The limiter wraps the function the router registered (see gis.py on order).
    assert hasattr(route.endpoint, "__wrapped__")
    src = inspect.getsource(users_api)
    block = src.split('@router.post("/{user_id}/invite"')[1].split("async def resend_invite")[0]
    assert "@limiter.limit(" in block


async def _resend(maker, admin, user_id):
    fn = inspect.unwrap(users_api.resend_invite)
    async with maker() as db:
        return await fn(request=None, user_id=user_id, db=db, current_user=admin)


async def test_resend_queues_and_is_audited(maker, task, email_on):
    admin = await _admin(maker)
    created = await _create(maker, admin, send_invite=False)
    out = await _resend(maker, admin, created.id)
    assert out.invite == "queued"
    assert task.calls == [(created.id, admin.id)]
    [event] = await _events(maker, "staff_invite_requested")
    assert event.username == "boss"
    assert event.details["user_id"] == created.id
    assert event.details["email_domain"] == "example.gov"
    assert "jordan@example.gov" not in str(event.details)


async def test_resend_with_email_off_is_skipped(maker, task, email_off):
    admin = await _admin(maker)
    created = await _create(maker, admin, send_invite=False)
    assert (await _resend(maker, admin, created.id)).invite == "skipped_email_off"
    assert task.calls == []


async def test_resend_refuses_missing_and_deactivated_accounts(maker, task, email_on):
    admin = await _admin(maker)
    with pytest.raises(HTTPException) as caught:
        await _resend(maker, admin, 9999)
    assert caught.value.status_code == 404

    created = await _create(maker, admin, send_invite=False)
    async with maker() as db:
        u = (await db.execute(select(User).where(User.id == created.id))).scalar_one()
        u.is_active = False
        await db.commit()
    with pytest.raises(HTTPException) as caught:
        await _resend(maker, admin, created.id)
    assert caught.value.status_code == 400
    assert task.calls == []


# ---------------------------------------------------------------------------
# the worker side
# ---------------------------------------------------------------------------


class Transport:
    def __init__(self, result=True, raises=None):
        self.result, self.raises, self.sent = result, raises, []

    def __call__(self, **kw):
        if self.raises:
            raise self.raises
        self.sent.append(kw)
        return self.result


@pytest.fixture
def worker_env(monkeypatch, email_on):
    async def origin(db):
        return ORIGIN

    async def provider():
        return "Okta"
    monkeypatch.setattr(staff_invite, "_origin", origin)
    monkeypatch.setattr(staff_invite, "_provider_name", provider)


async def _seed_settings(maker):
    async with maker() as db:
        db.add(models.SystemSettings(township_name="Example Township", primary_color="#1d4ed8"))
        await db.commit()


async def test_delivery_sends_stamps_and_audits(maker, worker_env, task):
    await _seed_settings(maker)
    admin = await _admin(maker)
    created = await _create(maker, admin, role="admin")
    transport = Transport()
    async with maker() as db:
        out = await staff_invite.deliver_invite(db, created.id, admin.id, transport)
    assert out["status"] == "sent"
    [mail] = transport.sent
    assert mail["to"] == "jordan@example.gov"
    assert "Sam Rivera added you as an administrator." in mail["body_text"]
    assert f"{ORIGIN}/login" in mail["body_html"]
    assert "your Okta account" in mail["body_text"]
    async with maker() as db:
        u = (await db.execute(select(User).where(User.id == created.id))).scalar_one()
        assert u.invited_at is not None
    [event] = await _events(maker, "staff_invite_sent")
    assert event.details == {"user_id": created.id, "email_domain": "example.gov"}
    assert event.username == "boss"


async def test_delivery_without_an_origin_sends_no_link_and_warns(maker, monkeypatch, email_on, task, caplog):
    async def no_origin(db):
        return None
    monkeypatch.setattr(staff_invite, "_origin", no_origin)
    await _seed_settings(maker)
    admin = await _admin(maker)
    created = await _create(maker, admin)
    transport = Transport()
    with caplog.at_level(logging.WARNING, logger="app.services.staff_invite"):
        async with maker() as db:
            await staff_invite.deliver_invite(db, created.id, admin.id, transport)
    [mail] = transport.sent
    assert "/login" not in mail["body_html"]
    assert "localhost" not in mail["body_html"] + mail["body_text"]
    assert any("without a sign-in link" in r.message for r in caplog.records)


@pytest.mark.parametrize("transport", [Transport(result=False), Transport(raises=OSError("smtp down"))])
async def test_a_failed_send_is_audited_as_failed(maker, worker_env, task, transport):
    await _seed_settings(maker)
    admin = await _admin(maker)
    created = await _create(maker, admin)
    async with maker() as db:
        out = await staff_invite.deliver_invite(db, created.id, admin.id, transport)
    assert out == {"status": "failed", "reason": "delivery_failed"}
    [event] = await _events(maker, "staff_invite_failed")
    assert event.success is False and event.failure_reason == "delivery_failed"
    assert event.details == {"user_id": created.id, "email_domain": "example.gov"}
    async with maker() as db:
        u = (await db.execute(select(User).where(User.id == created.id))).scalar_one()
        assert u.invited_at is None


async def test_email_switched_off_before_the_worker_ran_sends_nothing(maker, monkeypatch, worker_env, task):
    await _seed_settings(maker)
    admin = await _admin(maker)
    created = await _create(maker, admin)

    async def off():
        return False
    monkeypatch.setattr(staff_invite, "_email_enabled", off)
    transport = Transport()
    async with maker() as db:
        out = await staff_invite.deliver_invite(db, created.id, admin.id, transport)
    assert out["reason"] == "email_turned_off"
    assert transport.sent == []


def test_the_task_is_registered_with_the_worker():
    src = (staff_invite.__file__.rsplit("/app/", 1)[0] + "/app/core/celery_app.py")
    assert "app.tasks.staff_invites" in open(src).read()


def test_the_migration_adds_invited_at():
    from pathlib import Path
    root = Path(staff_invite.__file__).resolve().parents[2]
    [mig] = list((root / "alembic/versions").glob("e3a5c7d9f1b2_*.py"))
    text = mig.read_text()
    assert 'op.add_column("users", sa.Column("invited_at"' in text
    assert 'op.drop_column("users", "invited_at")' in text
