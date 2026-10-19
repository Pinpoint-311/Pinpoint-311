"""Signing out ends the session; tokens never ride in URLs; one-time means once.

From the 2026-10 security review:

* Logout did not revoke the JWT -- a copy kept working for the rest of its
  eight hours. Every session token now carries the account's session
  generation (`tv`), get_current_user compares it with `users.token_version`,
  and logout, deactivation, role/department changes and password resets bump it.
* The SSO callback redirected to `?token=<jwt>`, so the token sat in browser
  history and access logs. It now redirects with a single-use 60-second code
  that the page trades over POST /api/auth/exchange.
* A break-glass token could be exchanged repeatedly until it expired, and an
  Accela OAuth state replayed within its ten minutes. Both are now burned in
  the database on first use.
"""

import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
import types
import urllib.parse

import pytest

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("aiosqlite")
pytest.importorskip("fastapi.routing")
auth_core = pytest.importorskip("app.core.auth")
models = pytest.importorskip("app.models")
auth_api = pytest.importorskip("app.api.auth")
users_api = pytest.importorskip("app.api.users")
provisioning = pytest.importorskip("app.api.provisioning")
one_time = pytest.importorskip("app.services.one_time")
login_state = pytest.importorskip("app.services.login_state")
accela_oauth = pytest.importorskip("app.integrations.accela_oauth")
schemas = pytest.importorskip("app.schemas")

import jwt as jwt_lib  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

User = models.User
Department = models.Department

TABLES = [
    t for t in (
        User.__table__,
        Department.__table__,
        models.user_departments,
        models.SystemSecret.__table__,
        getattr(models, "AuditLog", None) and models.AuditLog.__table__,
        getattr(models, "AuditAnchor", None) and models.AuditAnchor.__table__,
    ) if t is not None
]


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    """Exercise the in-process fallback; no Redis in the test container."""
    monkeypatch.setattr(login_state, "_client", lambda: None)
    monkeypatch.setattr(one_time, "_client", lambda: None)
    one_time._memory.clear()
    login_state._memory.clear()
    yield
    one_time._memory.clear()
    login_state._memory.clear()


@pytest.fixture
async def maker():
    with tempfile.TemporaryDirectory() as d:
        engine = create_async_engine(f"sqlite+aiosqlite:///{os.path.join(d, 't.db')}", poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: models.Base.metadata.create_all(c, tables=TABLES))
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await engine.dispose()


async def _user(maker, username="clerk", role="staff", **kw):
    async with maker() as db:
        u = User(username=username, email=f"{username}@town.gov", role=role, is_active=True, **kw)
        db.add(u)
        await db.commit()
        return u.id


async def _me(maker, token):
    """What a request carrying this token gets back."""
    async with maker() as db:
        return await auth_core.get_current_user(token=token, db=db)


async def _token_for(maker, user_id):
    async with maker() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        return auth_core.create_session_token(user)


def _claims(token):
    return jwt_lib.decode(token, options={"verify_signature": False})


def _req(token=None):
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return types.SimpleNamespace(client=types.SimpleNamespace(host="198.51.100.9"), headers=headers)


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


async def test_session_tokens_carry_a_jti_and_the_session_generation(maker):
    uid = await _user(maker)
    claims = _claims(await _token_for(maker, uid))
    assert claims["jti"] and len(claims["jti"]) >= 32
    assert claims["uid"] == uid
    assert claims["tv"] == 0
    assert claims["sub"] == "clerk"


# ---------------------------------------------------------------------------
# revocation
# ---------------------------------------------------------------------------


async def test_a_token_works_until_logout_then_gets_401(maker, monkeypatch):
    monkeypatch.setattr(auth_api.Auth0Service, "get_config", staticmethod(lambda db: _none()))
    uid = await _user(maker)
    token = await _token_for(maker, uid)
    other_device = await _token_for(maker, uid)

    assert (await _me(maker, token)).id == uid

    async with maker() as db:
        me = await auth_core.get_current_user(token=token, db=db)
        await auth_api.logout(request=_req(token), current_user=me, db=db, return_to="https://town.gov")

    for t in (token, other_device):
        with pytest.raises(HTTPException) as caught:
            await _me(maker, t)
        assert caught.value.status_code == 401

    # Signing in again works.
    assert (await _me(maker, await _token_for(maker, uid))).id == uid


async def _none():
    return None


async def test_tokens_from_before_the_upgrade_still_work_until_the_first_bump(maker):
    """No `tv`/`uid` claim reads as generation 0: the deploy signs nobody out."""
    await _user(maker)
    legacy = auth_core.create_access_token({"sub": "clerk", "role": "staff"})
    assert (await _me(maker, legacy)).username == "clerk"


async def test_a_recreated_username_does_not_inherit_old_sessions(maker):
    uid = await _user(maker)
    token = await _token_for(maker, uid)
    await _user(maker, username="someone-else")  # so SQLite cannot reuse the rowid
    async with maker() as db:
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()
    await _user(maker)  # same username, new row
    with pytest.raises(HTTPException) as caught:
        await _me(maker, token)
    assert caught.value.status_code == 401


async def _admin(maker):
    aid = await _user(maker, username="boss", role="admin")
    async with maker() as db:
        return (await db.execute(select(User).where(User.id == aid))).scalar_one()


async def _update(maker, uid, admin, **fields):
    async with maker() as db:
        return await users_api.update_user(uid, schemas.UserUpdate(**fields), db=db, _=admin)


async def test_deactivation_revokes_even_after_reactivation(maker):
    admin = await _admin(maker)
    uid = await _user(maker)
    token = await _token_for(maker, uid)

    await _update(maker, uid, admin, is_active=False)
    with pytest.raises(HTTPException):
        await _me(maker, token)

    await _update(maker, uid, admin, is_active=True)
    with pytest.raises(HTTPException) as caught:
        await _me(maker, token)
    assert caught.value.status_code == 401


async def test_role_change_revokes(maker):
    admin = await _admin(maker)
    uid = await _user(maker, role="admin", username="deputy")
    token = await _token_for(maker, uid)

    await _update(maker, uid, admin, role="staff")
    with pytest.raises(HTTPException) as caught:
        await _me(maker, token)
    assert caught.value.status_code == 401


async def test_department_removal_revokes_but_an_unrelated_edit_does_not(maker):
    admin = await _admin(maker)
    async with maker() as db:
        roads, parks = Department(name="Roads"), Department(name="Parks")
        db.add_all([roads, parks])
        await db.commit()
        roads_id, parks_id = roads.id, parks.id
    uid = await _user(maker)
    await _update(maker, uid, admin, department_ids=[roads_id, parks_id])
    token = await _token_for(maker, uid)

    await _update(maker, uid, admin, full_name="Pat Clerk")
    assert (await _me(maker, token)).id == uid, "a name change must not sign anyone out"

    await _update(maker, uid, admin, department_ids=[roads_id])
    with pytest.raises(HTTPException) as caught:
        await _me(maker, token)
    assert caught.value.status_code == 401


async def test_admin_can_sign_a_user_out_everywhere(maker):
    admin = await _admin(maker)
    uid = await _user(maker)
    token = await _token_for(maker, uid)
    async with maker() as db:
        await users_api.revoke_sessions(uid, db=db, current_user=admin)
    with pytest.raises(HTTPException) as caught:
        await _me(maker, token)
    assert caught.value.status_code == 401


# ---------------------------------------------------------------------------
# SSO callback: a code in the URL, never the token
# ---------------------------------------------------------------------------


async def _callback(maker, monkeypatch):
    async def exchange(code, callback_url, db):
        return {"id_token": "idt"}

    async def verify(id_token, db):
        return {"email": "clerk@town.gov", "email_verified": True, "sub": "idp|1"}

    monkeypatch.setattr(auth_api.Auth0Service, "exchange_code_for_tokens", staticmethod(exchange))
    monkeypatch.setattr(auth_api.Auth0Service, "verify_token", staticmethod(verify))
    await login_state.remember("st", "https://town.gov/login")
    async with maker() as db:
        resp = await auth_api.auth0_callback(
            request=_req(), state="st", code="idp-code", error=None, error_description=None, db=db,
        )
    return resp.headers["location"]


async def test_the_callback_redirect_carries_no_token(maker, monkeypatch):
    await _user(maker)
    location = await _callback(maker, monkeypatch)
    assert "token=" not in location.replace("login_code=", "")
    assert "eyJ" not in location  # no JWT of any name
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert set(query) == {"login_code"}


async def test_the_exchange_code_works_once(maker, monkeypatch):
    uid = await _user(maker)
    location = await _callback(maker, monkeypatch)
    code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["login_code"][0]

    exchange = auth_api.exchange_login_code.__wrapped__  # past the rate limiter
    async with maker() as db:
        out = await exchange(request=None, body=auth_api.LoginCodeExchange(code=code), db=db)
    assert (await _me(maker, out["access_token"])).id == uid

    async with maker() as db:
        with pytest.raises(HTTPException) as caught:
            await exchange(request=None, body=auth_api.LoginCodeExchange(code=code), db=db)
    assert caught.value.status_code == 401


async def test_the_exchange_code_expires(maker):
    uid = await _user(maker)
    code = await one_time.issue_login_code({"uid": uid, "jti": "j"})
    value, _exp = one_time._memory[code]
    one_time._memory[code] = (value, time.time() - 1)  # 60 s have passed
    assert await one_time.redeem_login_code(code) is None


async def test_the_exchange_refuses_an_account_disabled_in_between(maker):
    uid = await _user(maker)
    code = await one_time.issue_login_code({"uid": uid, "jti": "j"})
    async with maker() as db:
        (await db.execute(select(User).where(User.id == uid))).scalar_one().is_active = False
        await db.commit()
    async with maker() as db:
        with pytest.raises(HTTPException) as caught:
            await auth_api.exchange_login_code.__wrapped__(
                request=None, body=auth_api.LoginCodeExchange(code=code), db=db)
    assert caught.value.status_code == 401


async def test_redis_path_is_single_use_too(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.kv = {}

        async def setex(self, key, ttl, value):
            self.kv[key] = value

        async def getdel(self, key):
            return self.kv.pop(key, None)

    fake = FakeRedis()
    monkeypatch.setattr(one_time, "_client", lambda: fake)
    code = await one_time.issue_login_code({"uid": 1})
    assert not one_time._memory, "Redis holds it when Redis is up"
    assert await one_time.redeem_login_code(code) == {"uid": 1}
    assert await one_time.redeem_login_code(code) is None


# ---------------------------------------------------------------------------
# break-glass: once
# ---------------------------------------------------------------------------

KEY = "p" * 40


def _break_glass_token(jti="bg-1", actor="ops@state.gov"):
    payload = json.dumps({
        "typ": "state_ops_break_glass", "exp": time.time() + 600, "actor": actor, "jti": jti,
    }).encode()
    body = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(KEY.encode(), payload, hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{body}.{sig}"


async def test_break_glass_token_is_refused_the_second_time(maker, monkeypatch):
    monkeypatch.setattr(provisioning, "get_settings",
                        lambda: types.SimpleNamespace(managed_mode=True, provisioning_token=KEY))
    token = _break_glass_token()
    body = provisioning.BreakGlassExchange(token=token)

    async with maker() as db:
        first = await provisioning.exchange_break_glass(body, db=db)
    assert (await _me(maker, first["access_token"])).username == "state-ops:ops@state.gov"

    async with maker() as db:
        with pytest.raises(HTTPException) as caught:
            await provisioning.exchange_break_glass(body, db=db)
    assert caught.value.status_code == 401
    assert "already used" in caught.value.detail

    # A fresh token from the panel still works.
    async with maker() as db:
        again = await provisioning.exchange_break_glass(
            provisioning.BreakGlassExchange(token=_break_glass_token(jti="bg-2")), db=db)
    assert again["access_token"]


# ---------------------------------------------------------------------------
# Accela OAuth state: once
# ---------------------------------------------------------------------------


async def test_accela_state_is_refused_the_second_time(maker):
    state = accela_oauth.sign_state(7, "admin-1", "https://town.gov/cb")
    payload = accela_oauth.verify_state(state)
    async with maker() as db:
        assert await accela_oauth.consume_state(db, payload) is True
    async with maker() as db:
        assert await accela_oauth.consume_state(db, payload) is False
    # A different state for the same connection is unaffected.
    other = accela_oauth.verify_state(accela_oauth.sign_state(7, "admin-1", "https://town.gov/cb"))
    async with maker() as db:
        assert await accela_oauth.consume_state(db, other) is True


def test_the_accela_callback_burns_the_state():
    from pathlib import Path
    source = Path(accela_oauth.__file__).parents[1].joinpath("api/integrations.py").read_text()
    handler = source[source.index("async def accela_oauth_callback"):]
    handler = handler[:handler.index("\n@router")]
    assert handler.index("verify_state(state)") < handler.index("consume_state(db, payload)") \
        < handler.index("exchange_code(")


def test_the_migration_matches_the_model():
    from pathlib import Path
    # Shipped in the release's single combined revision (see its docstring).
    text = (Path(__file__).resolve().parents[1]
            / "alembic/versions/e3a5c7d9f1b2_open311_keys_audit_chain_v2_token_version.py").read_text()
    assert 'revision = "e3a5c7d9f1b2"' in text
    assert 'down_revision = "d2e4f6a8b0c1"' in text
    assert '"token_version"' in text and 'server_default="0"' in text
    # No data writes: neither raw SQL nor op.execute ("updated_at" is a column).
    import re
    assert "op.execute" not in text and not re.search(r"\bUPDATE\s+\w+\s+SET\b", text, re.I)
    assert "token_version" in User.__table__.columns
