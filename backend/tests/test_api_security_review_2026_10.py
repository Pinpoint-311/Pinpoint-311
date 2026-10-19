"""Regressions from the October 2026 API security review.

Each test pins one finding. The review walked every route in app.main:app and
probed them on a throwaway stack with no token, a staff token from one
department, a staff token from another, a researcher token and an admin token.

  * research GeoJSON export: `?privacy_mode=x` returned exact coordinates to a
    researcher. The admin check matched only "exact", the fuzzing matched only
    "fuzzed", and anything else fell between them.
  * withheld-photo review: any staffer could release or discard a photo on
    another department's report, and got its full staff detail back. (Pinned in
    test_staff_requests_are_department_scoped.BY_ID_STAFF_ENDPOINTS.)
  * public audit log: `extra_data` was passed through verbatim. A manual
    intake's "submitted" row carries the assignee's username and routing.
  * photo screening: the per-caller limit trusted the leftmost
    X-Forwarded-For entry, which a client writes itself.
  * staff statistics: `recent_requests` listed every department's newest
    reports, deleted ones included.
  * user update: an admin could demote or deactivate the last admin.
  * break-glass exchange: a non-ASCII signature was a 500, not a 401.
  * SSO callback: an email the provider says is unverified still signed in
    the staff account with that address.
  * resident POST: an address longer than its column was a 500.
"""

import base64
import hashlib
import hmac
import inspect
import json
import types
import typing

import pytest

# Submodule guards, per tests/test_migrate.py: CI installs only a handful of
# packages, and a guard on a bare namespace name passes silently.
pytest.importorskip("fastapi.routing")
pytest.importorskip("sqlalchemy.orm")

from fastapi import HTTPException  # noqa: E402


# ---------------------------------------------------------------------------
# research export: an unknown privacy_mode must never mean "exact"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", ["export_csv", "export_geojson"])
def test_research_exports_accept_only_the_two_privacy_modes(endpoint):
    research = pytest.importorskip("app.api.research")
    annotation = inspect.signature(getattr(research, endpoint)).parameters["privacy_mode"].annotation
    assert typing.get_origin(annotation) is typing.Literal
    assert set(typing.get_args(annotation)) == {"fuzzed", "exact"}


@pytest.mark.parametrize("endpoint", ["export_csv", "export_geojson"])
def test_research_export_rejects_an_unknown_privacy_mode(endpoint):
    """Validated with the same pydantic machinery FastAPI applies to the query
    parameter. Not a TestClient: see tests/test_deploy_templates._fetch for why
    the production image's httpx cannot drive one."""
    research = pytest.importorskip("app.api.research")
    from pydantic import TypeAdapter, ValidationError

    annotation = inspect.signature(getattr(research, endpoint)).parameters["privacy_mode"].annotation
    with pytest.raises(ValidationError):
        TypeAdapter(annotation).validate_python("x")
    assert TypeAdapter(annotation).validate_python("fuzzed") == "fuzzed"


def test_geojson_fuzzes_anything_that_is_not_exact():
    research = pytest.importorskip("app.api.research")
    source = inspect.getsource(research.export_geojson)
    assert 'if privacy_mode != "exact":' in source
    assert 'if privacy_mode == "fuzzed":' not in source


# ---------------------------------------------------------------------------
# public audit log: extra_data is allow-listed
# ---------------------------------------------------------------------------


def _entry(action, extra):
    return types.SimpleNamespace(action=action, extra_data=extra)


def test_public_audit_log_drops_manual_intake_routing():
    open311 = pytest.importorskip("app.api.open311")
    entry = _entry("submitted", {"intake_options": {
        "fields": ["assigned_to", "staff_notes"],
        "assigned_to": "jane.clerk",
        "assigned_department_id": 4,
    }})
    assert open311._public_audit_extra(entry) is None


def test_public_audit_log_keeps_how_a_report_was_closed():
    open311 = pytest.importorskip("app.api.open311")
    entry = _entry("status_change", {
        "substatus": "resolved",
        "completion_message": "Filled",
        "internal": "not for residents",
    })
    assert open311._public_audit_extra(entry) == {
        "substatus": "resolved", "completion_message": "Filled",
    }


def test_public_audit_log_tolerates_missing_extra():
    open311 = pytest.importorskip("app.api.open311")
    assert open311._public_audit_extra(_entry("status_change", None)) is None


# ---------------------------------------------------------------------------
# photo screening: the limiter key is the trusted client address
# ---------------------------------------------------------------------------


def test_photo_screen_limit_ignores_a_forged_forwarded_for():
    open311 = pytest.importorskip("app.api.open311")
    from starlette.requests import Request
    from app.core.client_ip import rate_limit_key

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/open311/v2/photos/screen",
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")],
        "client": ("172.19.0.5", 12345),
    }
    request = Request(scope)
    assert open311._screen_rate_key(request) == rate_limit_key(request)
    assert open311._screen_rate_key(request) != "6.6.6.6"


# ---------------------------------------------------------------------------
# staff statistics: recent_requests is scoped and excludes deleted reports
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalar(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Recorder:
    def __init__(self, answers=None):
        self.statements = []
        self.answers = list(answers or [])

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.answers.pop(0) if self.answers else [])

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_statistics_recent_requests_are_department_scoped():
    system = pytest.importorskip("app.api.system")
    db = _Recorder()
    staff = types.SimpleNamespace(id=7, username="parks.clerk", role="staff")
    await system.get_statistics(db=db, current_user=staff)
    recent = [s for s in db.statements if getattr(s, "_limit_clause", None) is not None]
    assert recent, "no LIMITed query found -- did recent_requests move?"
    where = " ".join(str(recent[-1].whereclause).split())
    assert "deleted_at IS NULL" in where
    assert "assigned_department_id" in where


# ---------------------------------------------------------------------------
# users: the last active admin cannot be demoted or deactivated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"role": "staff"}, {"is_active": False}])
async def test_the_last_admin_cannot_be_demoted_or_deactivated(change):
    users = pytest.importorskip("app.api.users")
    from app.schemas import UserUpdate

    target = types.SimpleNamespace(id=1, username="only.admin", role="admin", is_active=True)
    # 1st query: the user; 2nd: how many OTHER active admins exist (none).
    db = _Recorder([[target], [0]])
    with pytest.raises(HTTPException) as caught:
        await users.update_user(
            user_id=1, user_data=UserUpdate(**change), db=db, _=target,
        )
    assert caught.value.status_code == 400
    assert target.role == "admin" and target.is_active is True


# ---------------------------------------------------------------------------
# break-glass: malformed tokens are 401s, never 500s
# ---------------------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_break_glass_non_ascii_signature_is_a_401():
    provisioning = pytest.importorskip("app.api.provisioning")
    with pytest.raises(HTTPException) as caught:
        provisioning._verify_break_glass(_b64(b'{"typ":"x"}') + ".éé", "k" * 40)
    assert caught.value.status_code == 401


def test_break_glass_signed_garbage_is_a_401():
    provisioning = pytest.importorskip("app.api.provisioning")
    key = "k" * 40
    payload = b'{"typ":"state_ops_break_glass","exp":"soon"}'
    sig = _b64(hmac.new(key.encode(), payload, hashlib.sha256).digest())
    with pytest.raises(HTTPException) as caught:
        provisioning._verify_break_glass(_b64(payload) + "." + sig, key)
    assert caught.value.status_code == 401


def test_break_glass_valid_token_still_verifies():
    provisioning = pytest.importorskip("app.api.provisioning")
    key = "k" * 40
    payload = json.dumps({"typ": "state_ops_break_glass", "exp": 4102444800, "actor": "a"}).encode()
    sig = _b64(hmac.new(key.encode(), payload, hashlib.sha256).digest())
    assert provisioning._verify_break_glass(_b64(payload) + "." + sig, key)["actor"] == "a"


# ---------------------------------------------------------------------------
# SSO: an email the provider reports as unverified does not sign in
# ---------------------------------------------------------------------------


def test_sso_callback_refuses_an_explicitly_unverified_email():
    auth = pytest.importorskip("app.api.auth")
    source = inspect.getsource(auth.auth0_callback)
    guard = source.find('user_info.get("email_verified") is False')
    lookup = source.find("select(User).where(User.email == email)")
    assert guard != -1, "the email_verified check is gone"
    assert guard < lookup, "the check must run before the account is matched by email"


# ---------------------------------------------------------------------------
# resident POST: bounds a client can act on, not a 500
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("address", "x" * 501),
    ("lat", 91.0),
    ("long", -181.0),
])
def test_resident_submission_bounds(field, value):
    schemas = pytest.importorskip("app.schemas")
    from pydantic import ValidationError

    body = {"service_code": "POTHOLE", "description": "A deep pothole here", "email": "r@example.com"}
    body[field] = value
    with pytest.raises(ValidationError):
        schemas.ServiceRequestCreate(**body)


# ---------------------------------------------------------------------------
# shared-secret checks: a non-ASCII value is a refusal, never a 500
# ---------------------------------------------------------------------------
#
# hmac.compare_digest raises TypeError when either str holds non-ASCII. Every
# one of these compared attacker-supplied text as str, so a junk header, URL
# segment or OAuth state from an unauthenticated caller was an unhandled 500.


@pytest.mark.parametrize("module_name,func_name", [
    ("app.api.telemetry", "require_panel_token"),
    ("app.api.provisioning", "require_provisioning_token"),
])
def test_orchestrator_tokens_refuse_non_ascii(monkeypatch, module_name, func_name):
    module = pytest.importorskip(module_name)
    monkeypatch.setattr(module, "get_settings",
                        lambda: types.SimpleNamespace(provisioning_token="p" * 40))
    with pytest.raises(HTTPException) as caught:
        getattr(module, func_name)("é" * 10)
    assert caught.value.status_code == 401
    assert getattr(module, func_name)("p" * 40)


def test_accela_state_with_non_ascii_signature_is_rejected_not_raised():
    accela = pytest.importorskip("app.integrations.accela_oauth")
    try:
        result = accela.verify_state("e30.éé")
    except TypeError:
        pytest.fail("verify_state raised on a non-ASCII signature")
    assert result is None


# ---------------------------------------------------------------------------
# Open311 discovery: key_service must not send client developers to staff login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_key_service_is_not_the_staff_login():
    open311 = pytest.importorskip("app.api.open311")
    request = types.SimpleNamespace(base_url="https://town.example/")
    discovery = await open311.open311_discovery(request)
    assert "/api/auth/login" not in discovery["key_service"]
    # Keys are issued by the town's administrators, and the text says so.
    assert "api_key" in discovery["key_service"]
    assert "administrator" in discovery["key_service"]
