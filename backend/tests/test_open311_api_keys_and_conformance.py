"""Open311 API keys and GeoReport v2 conformance.

What is pinned here:

  * keys: only a SHA-256 hash is stored, the plaintext is returned once, a
    revoked key stops working, and create/revoke/settings changes are audited.
  * POST requests.json: no key / bad key / revoked key are 403 in the spec's
    error shape, a good key files the report; anonymous submissions only when
    an admin allowed them; form-encoded and JSON bodies; `attribute[code]`
    mapped onto the category's custom questions; the answer is an array.
  * the first-party portal route refuses cross-origin and header-less callers.
  * GET requests.json / requests/{id}.json: public, spec fields only, no PII,
    the public listing rule, in_progress reported as open, the 90-day window.
  * XML: well formed, spec element names, untrusted text escaped.

POST and admin tests run the real router against an in-memory SQLite database
for the key and settings tables. The intake pipeline itself (moderation,
redaction, routing) is stubbed: it is shared with the portal and tested
elsewhere, and what matters here is what reaches it. The service_requests
table carries a PostGIS column SQLite cannot create, so the GET tests use a
session stand-in that answers each statement by what it selects.
"""

import types
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("aiosqlite")
pytest.importorskip("fastapi.routing")
httpx = pytest.importorskip("httpx")
open311 = pytest.importorskip("app.api.open311")
open311_admin = pytest.importorskip("app.api.open311_admin")
open311_keys = pytest.importorskip("app.services.open311_keys")
open311_format = pytest.importorskip("app.services.open311_format")
models = pytest.importorskip("app.models")

from fastapi import FastAPI  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.auth import get_current_admin  # noqa: E402
from app.db.session import get_db  # noqa: E402

BASE = "/api/open311/v2"

QUESTIONS = [
    {"id": "q-depth", "label": "How deep is it?", "type": "select",
     "options": ["Shallow", "Deep"], "required": True},
    {"id": "q-lanes", "label": "Which lanes?", "type": "checkbox",
     "options": ["Left", "Right"], "required": False},
    {"id": "q-note", "label": "Anything else?", "type": "text", "required": False},
]


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

def _app(session_factory=None, db_override=None, admin=None):
    app = FastAPI()
    app.state.limiter = open311.limiter
    app.include_router(open311.router, prefix=BASE)
    if db_override is not None:
        app.dependency_overrides[get_db] = db_override
    elif session_factory is not None:
        async def _db():
            async with session_factory() as s:
                yield s
        app.dependency_overrides[get_db] = _db
    if admin is not None:
        app.dependency_overrides[get_current_admin] = lambda: admin
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [models.Department.__table__, models.ServiceDefinition.__table__,
              models.service_departments, models.Open311ApiKey.__table__,
              models.Open311Settings.__table__]
    async with engine.begin() as conn:
        for t in tables:
            await conn.run_sync(t.create)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        s.add(models.ServiceDefinition(
            service_code="POTHOLE", service_name="Pothole", description="Road damage",
            is_active=True, location_mode="optional", hidden_from_public=False,
            routing_config={"custom_questions": QUESTIONS},
        ))
        await s.commit()
    open311_keys.reset_limits()
    yield factory
    await engine.dispose()


@pytest.fixture
def intake(monkeypatch):
    """Stand in for the shared intake pipeline and record what reached it."""
    calls = []

    async def fake_intake(db, request_data, *, source, notify_resident=True, audit_extra=None):
        calls.append({"data": request_data, "source": source,
                      "notify_resident": notify_resident, "audit_extra": audit_extra})
        return types.SimpleNamespace(
            service_request_id="REQ-20261018-ABCDEF12", photos_pending_review=0,
            service_code=request_data.service_code, service_name="Pothole",
            description=request_data.description, status="open", address=None, lat=None, long=None,
            requested_datetime=None)

    monkeypatch.setattr(open311, "_intake_resident_report", fake_intake)
    return calls


@pytest.fixture
def audit(monkeypatch):
    events = []
    from app.services.audit_service import AuditService

    async def fake_log_event(db, **kwargs):
        events.append(kwargs)

    monkeypatch.setattr(AuditService, "log_event", staticmethod(fake_log_event))
    return events


ADMIN = types.SimpleNamespace(id=1, username="clerk.admin", role="admin")


async def _issue_key(factory, **kw):
    plaintext, prefix, digest = open311_keys.generate_key()
    async with factory() as s:
        row = models.Open311ApiKey(name=kw.get("name", "Vendor"), contact_email="dev@vendor.example",
                                   key_prefix=prefix, key_hash=digest,
                                   rate_limit_per_minute=kw.get("limit"),
                                   revoked_at=kw.get("revoked_at"))
        s.add(row)
        await s.commit()
        return plaintext, row.id


async def _allow_anonymous(factory, allowed=True, jurisdiction=None):
    async with factory() as s:
        s.add(models.Open311Settings(allow_anonymous_submissions=allowed, jurisdiction_id=jurisdiction))
        await s.commit()


GOOD_FORM = {
    "service_code": "POTHOLE",
    "description": "Large pothole by the school crossing",
    "lat": "40.2171",
    "long": "-74.7429",
    "attribute[q-depth]": "Deep",
}


# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------

def test_a_key_is_stored_only_as_its_hash():
    plaintext, prefix, digest = open311_keys.generate_key()
    assert len(plaintext) >= 40
    assert prefix == plaintext[:8]
    assert digest == open311_keys.hash_key(plaintext)
    assert plaintext not in digest and len(digest) == 64


@pytest.mark.asyncio
async def test_admin_creates_lists_and_revokes_a_key(db_factory, audit):
    app = _app(db_factory, admin=ADMIN)
    async with _client(app) as c:
        r = await c.post(f"{BASE}/admin/keys", json={"name": "SeeClickFix", "contact_email": "ops@scf.example"})
        assert r.status_code == 201, r.text
        created = r.json()
        key = created["api_key"]
        assert created["key_prefix"] == key[:8] and created["status"] == "active"

        # Stored as a hash, never the key.
        async with db_factory() as s:
            row = (await s.execute(select(models.Open311ApiKey))).scalar_one()
            assert row.key_hash == open311_keys.hash_key(key)
            assert key not in (row.key_hash, row.key_prefix)
            assert row.created_by == "clerk.admin"

        listed = (await c.get(f"{BASE}/admin/keys")).json()
        assert len(listed) == 1 and "api_key" not in listed[0]
        assert key not in r.text.replace(key, "", 1)  # appears exactly once, in the create answer
        assert key not in str(listed)

        r = await c.post(f"{BASE}/admin/keys/{created['id']}/revoke")
        assert r.status_code == 200 and r.json()["status"] == "revoked"
        assert r.json()["revoked_by"] == "clerk.admin"
        # Idempotent, and not audited twice.
        await c.post(f"{BASE}/admin/keys/{created['id']}/revoke")

    kinds = [e["event_type"] for e in audit]
    assert kinds == ["open311_api_key_created", "open311_api_key_revoked"]
    assert all(e["username"] == "clerk.admin" for e in audit)
    assert key not in str(audit)
    async with db_factory() as s:
        assert await open311_keys.authenticate(s, key) is None


@pytest.mark.asyncio
async def test_the_key_endpoints_are_admin_only():
    from app.core.route_access import route_access
    admin_routes = [r for r in open311.router.routes if getattr(r, "path", "").startswith("/admin/")]
    assert len(admin_routes) >= 5
    assert all(route_access(r) == "admin" for r in admin_routes)


@pytest.mark.asyncio
async def test_the_anonymous_switch_defaults_off_and_its_changes_are_audited(db_factory, audit):
    app = _app(db_factory, admin=ADMIN)
    async with _client(app) as c:
        assert (await c.get(f"{BASE}/admin/settings")).json()["allow_anonymous_submissions"] is False
        r = await c.put(f"{BASE}/admin/settings", json={"allow_anonymous_submissions": True})
        assert r.json()["allow_anonymous_submissions"] is True
        await c.put(f"{BASE}/admin/settings", json={"allow_anonymous_submissions": True})  # no change
        await c.put(f"{BASE}/admin/settings", json={"jurisdiction_id": "springfield.nj"})
    assert [e["event_type"] for e in audit] == [
        "open311_anonymous_submissions_changed", "open311_jurisdiction_changed"]
    assert audit[0]["details"] == {"from": False, "to": True}


# --------------------------------------------------------------------------
# POST requests.json
# --------------------------------------------------------------------------

def _spec_error(response, code):
    assert response.status_code == code, response.text
    body = response.json()
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["code"] == code and isinstance(body[0]["description"], str)
    assert "detail" not in body[0]
    return body[0]


@pytest.mark.asyncio
async def test_post_without_a_key_is_refused_by_default(db_factory, intake):
    async with _client(_app(db_factory)) as c:
        r = await c.post(f"{BASE}/requests.json", data=GOOD_FORM)
    assert "api_key" in _spec_error(r, 403)["description"]
    assert not intake


@pytest.mark.asyncio
async def test_post_with_a_bad_key_is_refused(db_factory, intake):
    await _issue_key(db_factory)
    async with _client(_app(db_factory)) as c:
        r = await c.post(f"{BASE}/requests.json", data={**GOOD_FORM, "api_key": "x" * 43})
    _spec_error(r, 403)
    assert not intake


@pytest.mark.asyncio
async def test_post_with_a_revoked_key_is_refused(db_factory, intake):
    key, _ = await _issue_key(db_factory, revoked_at=datetime.now(timezone.utc))
    async with _client(_app(db_factory)) as c:
        r = await c.post(f"{BASE}/requests.json", data={**GOOD_FORM, "api_key": key})
    _spec_error(r, 403)
    assert not intake


@pytest.mark.asyncio
async def test_post_form_encoded_with_a_good_key(db_factory, intake):
    key, key_id = await _issue_key(db_factory, name="CivicApp")
    async with _client(_app(db_factory)) as c:
        r = await c.post(f"{BASE}/requests.json", data={
            **GOOD_FORM, "api_key": key, "address_string": "12 Main St", "zipcode": "08601",
            "first_name": "Jane", "last_name": "Doe", "phone": "555-0100",
            "account_id": "acct-9", "device_id": "dev-1",
            "media_url": "https://cdn.example/p.jpg",
            "attribute[q-lanes][]": ["Left", "Right"],
        })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body == [{"service_request_id": "REQ-20261018-ABCDEF12", "service_notice": None,
                     "account_id": "acct-9"}]
    (call,) = intake
    data = call["data"]
    assert call["source"] == "open311"
    assert data.address == "12 Main St 08601"
    assert (data.lat, data.long) == (40.2171, -74.7429)
    assert (data.first_name, data.last_name, data.phone) == ("Jane", "Doe", "555-0100")
    assert data.media_urls == ["https://cdn.example/p.jpg"]
    # attribute[code] -> the category's questions, stored under their labels.
    assert data.custom_fields == {"How deep is it?": "Deep", "Which lanes?": ["Left", "Right"]}
    # No email: optional in the spec, placeholder stored, nobody emailed.
    assert data.email.endswith("@intake.local") and call["notify_resident"] is False
    assert call["audit_extra"]["api_key_id"] == key_id
    assert call["audit_extra"]["account_id"] == "acct-9"
    assert "dev-1" not in str(call["audit_extra"])
    async with db_factory() as s:
        row = (await s.execute(select(models.Open311ApiKey))).scalar_one()
        assert row.last_used_at is not None


@pytest.mark.asyncio
async def test_post_json_with_an_attribute_object_and_email(db_factory, intake):
    key, _ = await _issue_key(db_factory)
    async with _client(_app(db_factory)) as c:
        r = await c.post(f"{BASE}/requests.json", json={
            "api_key": key, "service_code": "POTHOLE", "description": "Pothole near the library",
            "lat": 40.1, "long": -74.2, "email": "resident@example.com",
            "attribute": {"q-depth": "Shallow", "q-note": "Near the drain"},
        })
    assert r.status_code == 201, r.text
    assert isinstance(r.json(), list)
    data = intake[0]["data"]
    assert data.email == "resident@example.com" and intake[0]["notify_resident"] is True
    assert data.custom_fields == {"How deep is it?": "Shallow", "Anything else?": "Near the drain"}


@pytest.mark.asyncio
@pytest.mark.parametrize("extra,needle", [
    ({"attribute[q-depth]": "Bottomless"}, "q-depth"),
    ({"attribute[q-nope]": "x"}, "q-nope"),
    ({"attribute[q-depth]": ""}, "q-depth"),          # required question unanswered
    ({"lat": "abc"}, "lat"),
    ({"long": ""}, "together"),
    ({"service_code": "NOPE"}, "service code"),
    ({"email": "not-an-email"}, "email"),
    ({"description": "short"}, "description"),
])
async def test_bad_post_fields_are_spec_shaped_400s(db_factory, intake, extra, needle):
    key, _ = await _issue_key(db_factory)
    async with _client(_app(db_factory)) as c:
        r = await c.post(f"{BASE}/requests.json", data={**GOOD_FORM, "api_key": key, **extra})
    err = _spec_error(r, 400)
    assert needle.lower() in err["description"].lower()
    # Never echo a submitted value back.
    assert "not-an-email" not in err["description"]
    assert not intake


@pytest.mark.asyncio
async def test_anonymous_post_works_only_when_allowed_and_is_rate_limited(db_factory, intake):
    await _allow_anonymous(db_factory)
    async with _client(_app(db_factory)) as c:
        statuses = [(await c.post(f"{BASE}/requests.json", data=GOOD_FORM)).status_code for _ in range(11)]
    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429
    assert intake[0]["audit_extra"]["api_key_id"] is None


@pytest.mark.asyncio
async def test_each_key_has_its_own_rate_limit(db_factory, intake):
    key, _ = await _issue_key(db_factory, limit=2)
    async with _client(_app(db_factory)) as c:
        codes = [(await c.post(f"{BASE}/requests.json", data={**GOOD_FORM, "api_key": key})).status_code
                 for _ in range(3)]
        assert codes == [201, 201, 429]
        r = await c.post(f"{BASE}/requests.json", data={**GOOD_FORM, "api_key": key})
    _spec_error(r, 429)
    assert r.headers.get("retry-after") == "60"


@pytest.mark.asyncio
async def test_a_jurisdiction_id_must_match_the_configured_one(db_factory, intake):
    await _allow_anonymous(db_factory, jurisdiction="springfield.nj")
    async with _client(_app(db_factory)) as c:
        bad = await c.post(f"{BASE}/requests.json", data={**GOOD_FORM, "jurisdiction_id": "elsewhere"})
        ok = await c.post(f"{BASE}/requests.json", data={**GOOD_FORM, "jurisdiction_id": "springfield.nj"})
        bad_get = await c.get(f"{BASE}/services.json?jurisdiction_id=elsewhere")
    _spec_error(bad, 400)
    assert ok.status_code == 201
    _spec_error(bad_get, 400)


@pytest.mark.asyncio
async def test_the_post_answer_and_errors_come_as_xml_on_the_xml_path(db_factory, intake):
    key, _ = await _issue_key(db_factory)
    async with _client(_app(db_factory)) as c:
        ok = await c.post(f"{BASE}/requests.xml", data={**GOOD_FORM, "api_key": key, "account_id": "<b>&"})
        bad = await c.post(f"{BASE}/requests.xml", data=GOOD_FORM)
    assert ok.status_code == 201 and ok.headers["content-type"].startswith("text/xml")
    root = ET.fromstring(ok.content)
    assert root.tag == "service_requests"
    assert root.find("request/service_request_id").text == "REQ-20261018-ABCDEF12"
    assert root.find("request/account_id").text == "<b>&"   # escaped on the wire, intact when parsed
    assert b"<b>&" not in ok.content
    err = ET.fromstring(bad.content)
    assert bad.status_code == 403 and err.tag == "errors"
    assert err.find("error/code").text == "403"


# --------------------------------------------------------------------------
# The first-party portal route
# --------------------------------------------------------------------------

def _req(headers):
    return types.SimpleNamespace(headers={k.lower(): v for k, v in headers.items()})


@pytest.mark.parametrize("headers,ok", [
    ({"Sec-Fetch-Site": "same-origin"}, True),
    ({"Origin": "https://town.example", "Host": "town.example"}, True),
    ({"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"}, True),
    ({"Origin": "https://evil.example", "Host": "town.example"}, False),
    ({"Origin": "https://town.example", "Host": "town.example", "Sec-Fetch-Site": "cross-site"}, False),
    ({"Sec-Fetch-Site": "cross-site"}, False),
    ({}, False),
    ({"Origin": "null", "Host": "town.example"}, False),
])
def test_the_portal_route_only_takes_same_origin_browser_posts(monkeypatch, headers, ok):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert open311._first_party_origin_ok(_req(headers)) is ok


@pytest.mark.asyncio
async def test_the_portal_route_refuses_a_script_with_the_old_error_shape(db_factory, intake):
    async with _client(_app(db_factory)) as c:
        r = await c.post(f"{BASE}/portal/requests", json={
            "service_code": "POTHOLE", "description": "Pothole near the library", "email": "a@b.example"})
    assert r.status_code == 403
    assert "detail" in r.json()   # not an Open311 route: FastAPI's shape is kept
    assert not intake


@pytest.mark.asyncio
async def test_the_portal_route_still_files_for_the_portal(db_factory, intake):
    async with _client(_app(db_factory)) as c:
        r = await c.post(f"{BASE}/portal/requests", headers={"Sec-Fetch-Site": "same-origin"}, json={
            "service_code": "POTHOLE", "description": "Pothole near the library", "email": "a@b.example"})
    assert r.status_code == 201, r.text
    assert r.json()["service_request_id"] == "REQ-20261018-ABCDEF12"   # a single object, as before
    assert intake[0]["source"] == "resident_portal"


# --------------------------------------------------------------------------
# GET requests.json / requests/{id}.json
# --------------------------------------------------------------------------

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _row(**kw):
    base = dict(
        id=4711, service_request_id="REQ-1", service_code="POTHOLE", service_name="Pothole",
        description="Deep pothole", status="in_progress", address="12 Main St", lat=40.1, long=-74.2,
        requested_datetime=NOW - timedelta(days=1), updated_datetime=NOW,
        completion_message="Filled it", closed_substatus=None,
        media_urls=["data:image/jpeg;base64,/9j/AAAA"],
        media_pending_review=[{"media": "data:image/jpeg;base64,SECRET", "reason": "error"}],
        first_name="Jane", last_name="Doe", email="jane@example.com", phone="555-0100",
        staff_notes="call back after 5", ai_analysis={"priority_score": 9}, assigned_to="j.morales",
        flagged=True, flag_reason="profanity", priority=2,
        assigned_department=types.SimpleNamespace(name="Public Works"),
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


class _Rows:
    def __init__(self, rows=(), scalar=None):
        self._rows, self._scalar = list(rows), scalar

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._scalar


class SpecSession:
    """Answers each statement by what it selects; keeps the SQL it was sent."""

    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    async def execute(self, statement, *a, **kw):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.sql.append(sql)
        if "FROM system_settings" in sql or "FROM open311_settings" in sql:
            return _Rows(scalar=None)
        if "hidden_from_public IS 1" in sql or "hidden_from_public IS true" in sql:
            return _Rows([("SECRETCAT",)])
        if "service_definitions.sla_hours" in sql:
            return _Rows([("POTHOLE", 48)])
        if "FROM service_requests" in sql:
            return _Rows(self.rows, scalar=self.rows[0] if self.rows else None)
        return _Rows()


def _session_app(session):
    async def _db():
        yield session
    return _app(db_override=_db)


PII_AND_STAFF = ("Jane", "Doe", "jane@example.com", "555-0100", "call back", "priority_score",
                 "j.morales", "profanity", "SECRET", "4711")


@pytest.mark.asyncio
async def test_the_public_list_carries_spec_fields_and_nothing_private():
    session = SpecSession([_row()])
    async with _client(_session_app(session)) as c:
        r = await c.get(f"{BASE}/requests.json")
    assert r.status_code == 200, r.text
    (rec,) = r.json()
    assert rec["status"] == "open"                       # in_progress -> open
    assert rec["status_notes"] is None                   # only once closed
    assert rec["agency_responsible"] == "Public Works"
    assert rec["expected_datetime"] == (NOW - timedelta(days=1) + timedelta(hours=48)).isoformat()
    assert rec["media_url"] == "http://testserver/api/open311/v2/public/requests/REQ-1/media/0"
    for field in ("service_request_id", "status", "status_notes", "service_name", "service_code",
                  "description", "agency_responsible", "service_notice", "requested_datetime",
                  "updated_datetime", "expected_datetime", "address", "address_id", "zipcode",
                  "lat", "long", "media_url"):
        assert field in rec
    for needle in PII_AND_STAFF:
        assert needle not in r.text, needle
    # The public listing rule and the default 90-day window were applied.
    sql = next(s for s in session.sql if "FROM service_requests" in s)
    assert "deleted_at IS NULL" in sql and "is_public IS" in sql and "public_archived IS" in sql
    assert "SECRETCAT" in sql
    assert "requested_datetime >=" in sql and "LIMIT 1000" in sql


@pytest.mark.asyncio
async def test_a_closed_report_shows_its_public_completion_message():
    async with _client(_session_app(SpecSession([_row(status="closed")]))) as c:
        rec = (await c.get(f"{BASE}/requests.json")).json()[0]
    assert rec["status"] == "closed" and rec["status_notes"] == "Filled it"


@pytest.mark.asyncio
async def test_status_and_service_code_filters():
    session = SpecSession([])
    async with _client(_session_app(session)) as c:
        await c.get(f"{BASE}/requests.json?status=open&service_code=POTHOLE,STREETLIGHT")
        bad = await c.get(f"{BASE}/requests.json?status=in_progress")
    sql = [s for s in session.sql if "FROM service_requests" in s][0]
    assert "'open'" in sql and "'in_progress'" in sql and "'closed'" not in sql.split("status IN")[1][:40]
    assert "'POTHOLE'" in sql and "'STREETLIGHT'" in sql
    _spec_error(bad, 400)


@pytest.mark.asyncio
async def test_service_request_ids_override_the_other_filters():
    session = SpecSession([])
    async with _client(_session_app(session)) as c:
        await c.get(f"{BASE}/requests.json?service_request_id=REQ-1,REQ-2&status=closed")
    sql = [s for s in session.sql if "FROM service_requests" in s][0]
    assert "'REQ-1'" in sql and "'REQ-2'" in sql
    assert "requested_datetime >=" not in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("query,code", [
    ("start_date=2026-01-01T00:00:00Z&end_date=2026-06-01T00:00:00Z", 400),   # > 90 days
    ("start_date=2026-06-01T00:00:00Z&end_date=2026-05-01T00:00:00Z", 400),   # reversed
    ("start_date=yesterday", 400),
    ("start_date=2026-09-01T00:00:00Z", 200),                                  # end defaults to +90d
    ("start_date=2026-09-01T00:00:00Z&end_date=2026-10-01T00:00:00-04:00", 200),
])
async def test_the_date_window(query, code):
    async with _client(_session_app(SpecSession([]))) as c:
        r = await c.get(f"{BASE}/requests.json?{query}")
    assert r.status_code == code, r.text
    if code == 400:
        _spec_error(r, 400)


@pytest.mark.asyncio
async def test_by_id_is_an_array_and_unknown_is_a_spec_404():
    async with _client(_session_app(SpecSession([_row()]))) as c:
        r = await c.get(f"{BASE}/requests/REQ-1.json")
    assert r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) == 1
    async with _client(_session_app(SpecSession([]))) as c:
        r = await c.get(f"{BASE}/requests/REQ-404.json")
    _spec_error(r, 404)


@pytest.mark.asyncio
async def test_tokens_answer_an_array():
    class _TokenSession(SpecSession):
        async def execute(self, statement, *a, **kw):
            return _Rows(scalar="REQ-1")
    async with _client(_session_app(_TokenSession([]))) as c:
        r = await c.get(f"{BASE}/tokens/REQ-1.json")
        x = await c.get(f"{BASE}/tokens/REQ-1.xml")
    assert r.json() == [{"service_request_id": "REQ-1", "token": "REQ-1"}]
    assert ET.fromstring(x.content).find("request/token").text == "REQ-1"


@pytest.mark.asyncio
async def test_the_list_as_xml_is_well_formed_and_escaped():
    evil = 'Pothole <script>alert(1)</script> & "quotes" \x00\x07 done'
    async with _client(_session_app(SpecSession([_row(description=evil, status="closed")]))) as c:
        r = await c.get(f"{BASE}/requests.xml")
    assert r.headers["content-type"].startswith("text/xml")
    assert b"<script>" not in r.content
    root = ET.fromstring(r.content)   # raises if not well formed
    assert root.tag == "service_requests"
    req = root.find("request")
    assert req.find("description").text == 'Pothole <script>alert(1)</script> & "quotes"  done'
    assert req.find("status").text == "closed"
    for tag in ("service_request_id", "status_notes", "agency_responsible", "requested_datetime",
                "expected_datetime", "lat", "long", "media_url"):
        assert req.find(tag) is not None, tag


@pytest.mark.asyncio
async def test_services_and_definition_as_xml_use_spec_names(db_factory):
    async with _client(_app(db_factory)) as c:
        services = await c.get(f"{BASE}/services.xml")
        definition = await c.get(f"{BASE}/services/POTHOLE.xml")
        definition_json = await c.get(f"{BASE}/services/POTHOLE.json")
        discovery = await c.get(f"{BASE}/discovery.xml")
        missing = await c.get(f"{BASE}/services/NOPE.json")
    s = ET.fromstring(services.content)
    assert s.tag == "services" and s.find("service/service_code").text == "POTHOLE"
    assert s.find("service/metadata").text == "true"
    d = ET.fromstring(definition.content)
    assert d.tag == "service_definition"
    attrs = d.findall("attributes/attribute")
    assert [a.find("code").text for a in attrs] == ["q-depth", "q-lanes", "q-note"]
    assert attrs[0].find("datatype").text == "singlevaluelist"
    assert [v.find("key").text for v in attrs[0].findall("values/value")] == ["Shallow", "Deep"]
    assert attrs[1].find("datatype").text == "multivaluelist"
    assert definition_json.json()["attributes"][0]["required"] is True
    disc = ET.fromstring(discovery.content)
    assert disc.tag == "discovery"
    assert "text/xml" in [f.text for f in disc.findall("endpoints/endpoint/formats/format")]
    _spec_error(missing, 404)


def test_the_xml_encoder_never_takes_an_element_name_from_data():
    out = open311_format.to_xml("services", [{"service_code": "A", "<bad name>": "x"}])
    root = ET.fromstring(out)
    assert [c.tag for c in root.find("service")] == ["service_code"]


@pytest.mark.asyncio
async def test_validation_errors_on_spec_routes_are_400_in_the_spec_shape():
    async with _client(_session_app(SpecSession([]))) as c:
        r = await c.get(f"{BASE}/requests.json?status=" + "x" * 200)
    _spec_error(r, 400)


@pytest.mark.asyncio
async def test_the_public_photo_route_serves_only_published_photos():
    class _PhotoSession(SpecSession):
        async def execute(self, statement, *a, **kw):
            return _Rows([(["data:image/png;base64,iVBORw0KGgo=", "data:text/html;base64,PHNjcmlwdD4="],)])
    async with _client(_session_app(_PhotoSession([]))) as c:
        ok = await c.get(f"{BASE}/public/requests/REQ-1/media/0")
        html = await c.get(f"{BASE}/public/requests/REQ-1/media/1")
        gone = await c.get(f"{BASE}/public/requests/REQ-1/media/5")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert ok.content.startswith(b"\x89PNG")
    assert html.status_code == 404 and gone.status_code == 404


def test_the_staff_reads_moved_off_the_spec_paths():
    paths = {(m, r.path) for r in open311.router.routes for m in getattr(r, "methods", ())}
    assert ("GET", "/staff/requests") in paths
    assert ("GET", "/staff/requests/{request_id}") in paths
    from app.core.route_access import route_access
    staff = [r for r in open311.router.routes if getattr(r, "path", "").startswith("/staff/")]
    assert staff and all(route_access(r) == "staff" for r in staff)
