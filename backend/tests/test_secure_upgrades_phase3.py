"""Secure upgrades, Phase 3: the console requests, the host updater executes.

docs/design/secure-upgrades.md section 4. Pinned here:

  * the updater's internal channel takes only a live updater token (bad,
    revoked, missing and proxied callers are refused) and records check-ins;
  * exactly one claim wins;
  * an upgrade can only name a release the updater reported as verified and
    schema-compatible;
  * two-person approval: the requester cannot approve their own upgrade, a
    different admin can, and with the setting off self-approval is allowed;
    restarts need one admin;
  * cancel rules; step and outcome reports drive the status;
  * the git/docker endpoints are gone and system.py starts no processes;
  * route_access labels the channel "updater-token"; Caddy refuses the prefix.

Runs the real routers against a file-backed SQLite database (a file, so two
sessions really are two connections for the claim race).
"""

import asyncio
import json
import re
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("aiosqlite")
pytest.importorskip("fastapi.routing")
httpx = pytest.importorskip("httpx")
models = pytest.importorskip("app.models")
upgrades_api = pytest.importorskip("app.api.upgrades")
internal_api = pytest.importorskip("app.api.updater_internal")
U = pytest.importorskip("app.services.upgrades")

from fastapi import FastAPI  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.core.auth import get_current_admin  # noqa: E402
from app.db.session import get_db  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("UpgradeRequest", "UpgradeRequestStep", "UpdaterToken", "UpdaterRelease", "UpdaterSettings", "AuditLog")

ALICE = types.SimpleNamespace(id=1, username="alice", email="alice@town.example", role="admin")
BOB = types.SimpleNamespace(id=2, username="bob", email="bob@town.example", role="admin")


class Harness:
    def __init__(self, factory):
        self.factory = factory
        self.admin = ALICE
        self.emails = []
        app = FastAPI()
        app.include_router(upgrades_api.router, prefix="/api/system")
        app.include_router(internal_api.router, prefix="/api/internal/updater")

        async def _db():
            async with factory() as s:
                yield s

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_admin] = lambda: self.admin
        self.app = app

    def client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1:8000")

    async def token(self, revoked=False):
        plaintext, prefix, digest = U.generate_token()
        async with self.factory() as s:
            s.add(models.UpdaterToken(token_prefix=prefix, token_hash=digest, created_by="alice",
                                      revoked_at=datetime.now(timezone.utc) if revoked else None))
            await s.commit()
        return plaintext

    async def rows(self, model, *where):
        async with self.factory() as s:
            return (await s.execute(select(model).where(*where))).scalars().all()


@pytest.fixture
async def h(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    async with engine.begin() as conn:
        for name in TABLES:
            await conn.run_sync(getattr(models, name).__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    harness = Harness(factory)

    async def fake_notify(kind, request_id=None, actor=None):
        harness.emails.append((kind, request_id) if actor is None else (kind, request_id, actor))

    monkeypatch.setattr(U, "notify_admins", fake_notify)
    yield harness
    await engine.dispose()


def bearer(token):
    return {"Authorization": f"Bearer {token}", "User-Agent": "pinpoint-updater/0.2.0"}


RELEASES = {
    "releases": [
        {"tag": "v1.8.0", "version": "1.8.0", "name": "1.8.0", "published_at": "2026-10-10T12:00:00Z",
         "notes": "## Changes\n- faster", "url": "https://github.com/Pinpoint-311/Pinpoint-311/releases/tag/v1.8.0",
         "signature_verified": True, "gate_passed": True, "attested": True,
         "db_revision": "e3a5c7d9f1b2", "min_db_revision": "d2e4f6a8b0c1", "compatible": True,
         "compatibility": "db_revision d2e4f6a8b0c1 inside window",
         "backend_digest": "sha256:" + "a" * 64, "frontend_digest": "sha256:" + "b" * 64},
        {"tag": "v1.9.0-unsigned", "version": "1.9.0", "signature_verified": False, "compatible": True},
        {"tag": "v2.0.0", "version": "2.0.0", "signature_verified": True, "gate_passed": True, "compatible": False,
         "compatibility": "db_revision d2e4f6a8b0c1 outside compatibility window [x .. y]"},
        {"tag": "v1.8.1", "version": "1.8.1", "signature_verified": None, "compatible": None},
    ],
    "current": {"version": "v1.7.0", "backend": "ghcr.io/p/b@sha256:" + "1" * 64,
                "frontend": "ghcr.io/p/f@sha256:" + "2" * 64},
}


async def connect(h, c):
    """An updater checks in and reports releases."""
    tok = await h.token()
    r = await c.put("/api/internal/updater/releases", json=RELEASES, headers=bearer(tok))
    assert r.status_code == 200, r.text
    return tok


async def file_request(h, c, admin=ALICE, **body):
    h.admin = admin
    payload = {"action": "upgrade", "target_tag": "v1.8.0", "reason": "monthly patch window"}
    payload.update(body)
    return await c.post("/api/system/upgrade-requests", json=payload)


# ---------------------------------------------------------------------------
# Token auth
# ---------------------------------------------------------------------------

async def test_the_channel_refuses_missing_bad_and_revoked_tokens(h):
    revoked = await h.token(revoked=True)
    async with h.client() as c:
        assert (await c.get("/api/internal/updater/requests")).status_code == 401
        assert (await c.get("/api/internal/updater/requests", headers=bearer("ppu_" + "x" * 40))).status_code == 401
        assert (await c.get("/api/internal/updater/requests", headers={"Authorization": "Basic abc"})).status_code == 401
        assert (await c.get("/api/internal/updater/requests", headers=bearer(revoked))).status_code == 401
        good = await h.token()
        r = await c.get("/api/internal/updater/requests", headers=bearer(good))
        assert r.status_code == 200 and r.json()["requests"] == []
    (row,) = await h.rows(models.UpdaterToken, models.UpdaterToken.token_hash == U.hash_token(good))
    assert row.last_used_at is not None
    (settings,) = await h.rows(models.UpdaterSettings)
    assert settings.updater_last_seen_at is not None and settings.updater_version == "0.2.0"


async def test_a_proxied_request_is_refused_even_with_a_good_token(h):
    """Through Caddy means from the internet: the updater calls loopback directly."""
    good = await h.token()
    async with h.client() as c:
        for header in ("X-Forwarded-For", "Forwarded", "X-Real-IP", "Via"):
            r = await c.get("/api/internal/updater/requests", headers={**bearer(good), header: "203.0.113.9"})
            assert r.status_code == 404, header


async def test_only_a_hash_and_prefix_are_stored_and_the_token_is_shown_once(h):
    async with h.client() as c:
        r = await c.post("/api/system/updater-tokens", json={"label": "town host"})
        assert r.status_code == 201
        plaintext = r.json()["token"]
        assert plaintext.startswith("ppu_") and len(plaintext) > 40
        listing = (await c.get("/api/system/updater-tokens")).json()
        assert "token" not in listing["tokens"][0] and listing["tokens"][0]["token_prefix"] == plaintext[:12]
        (row,) = await h.rows(models.UpdaterToken)
        assert row.token_hash == U.hash_token(plaintext) and plaintext not in (row.token_prefix + row.token_hash)
        assert (await c.get("/api/internal/updater/requests", headers=bearer(plaintext))).status_code == 200
        assert (await c.post(f"/api/system/updater-tokens/{row.id}/revoke")).json()["status"] == "revoked"
        assert (await c.get("/api/internal/updater/requests", headers=bearer(plaintext))).status_code == 401
    events = [a.event_type for a in await h.rows(models.AuditLog)]
    assert "updater_token_created" in events and "updater_token_revoked" in events
    created = [a for a in await h.rows(models.AuditLog) if a.event_type == "updater_token_created"][0]
    assert plaintext not in str(created.details)


# ---------------------------------------------------------------------------
# Requests: validation, approval, cancel
# ---------------------------------------------------------------------------

async def test_nothing_can_be_requested_before_an_updater_checks_in(h):
    async with h.client() as c:
        r = await file_request(h, c)
        assert r.status_code == 409 and "No updater" in r.json()["detail"]
        r = await file_request(h, c, action="restart", target_tag=None)
        assert r.status_code == 409


@pytest.mark.parametrize("tag,needle", [
    ("v9.9.9", "not in the list"),
    ("v1.9.0-unsigned", "failed signature verification"),
    ("v1.8.1", "has not been signature-verified"),
    ("v2.0.0", "not compatible"),
    (None, "Choose a release"),
])
async def test_an_upgrade_must_name_a_verified_compatible_reported_release(h, tag, needle):
    async with h.client() as c:
        await connect(h, c)
        r = await file_request(h, c, target_tag=tag)
        assert r.status_code == 422, r.text
        assert needle in r.json()["detail"]
    refused = [a for a in await h.rows(models.AuditLog) if a.event_type == "upgrade_request_refused"]
    assert refused and refused[0].success is False


async def test_the_live_schema_is_checked_as_well_as_the_report(h):
    async with h.factory() as s:
        await s.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await s.execute(text("INSERT INTO alembic_version VALUES ('c7d9e1f3a5b6')"))
        await s.commit()
    async with h.client() as c:
        await connect(h, c)
        r = await file_request(h, c)
        assert r.status_code == 422 and "this database is at c7d9e1f3a5b6" in r.json()["detail"]
        listed = (await c.get("/api/system/releases")).json()
        row = next(x for x in listed["releases"] if x["tag"] == "v1.8.0")
        assert row["requestable"] is False and row["signature_verified"] is True


async def test_scheduling_in_the_past_and_destructive_rollbacks_are_refused(h):
    async with h.client() as c:
        await connect(h, c)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert (await file_request(h, c, scheduled_for=past)).status_code == 422
        r = await file_request(h, c, action="rollback", target_tag=None, allow_destructive=True)
        assert r.status_code == 422


async def test_two_person_approval_is_enforced_by_default(h):
    async with h.client() as c:
        await connect(h, c)
        r = await file_request(h, c, allow_destructive=True)
        assert r.status_code == 201, r.text
        req = r.json()
        assert req["status"] == "pending_approval" and req["allow_destructive"] is True
        assert req["can_approve"] is False and "different admin" in req["approve_blocked_reason"]
        assert h.emails == [("created", req["id"])]

        # The requester cannot approve it...
        h.admin = ALICE
        r = await c.post(f"/api/system/upgrade-requests/{req['id']}/approve")
        assert r.status_code == 403 and "different admin" in r.json()["detail"]
        # ...and the updater sees nothing yet.
        tok = await h.token()
        assert (await c.get("/api/internal/updater/requests", headers=bearer(tok))).json()["requests"] == []

        # A different admin can.
        h.admin = BOB
        listed = (await c.get("/api/system/upgrade-requests")).json()["requests"][0]
        assert listed["can_approve"] is True
        r = await c.post(f"/api/system/upgrade-requests/{req['id']}/approve")
        assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_by"] == "bob"

        pending = (await c.get("/api/internal/updater/requests", headers=bearer(tok))).json()
        (p,) = pending["requests"]
        # The updater's UpgradeRequest shape (updater/pinpoint_updater/request_source.py).
        assert p == {**p, "id": str(req["id"]), "action": "upgrade", "tag": "v1.8.0", "requested_by": "alice",
                     "reason": "monthly patch window", "approvals": ["bob"], "allow_destructive": True,
                     "policy": "two_person"}
    events = [a.event_type for a in await h.rows(models.AuditLog)]
    assert {"upgrade_request_created", "upgrade_request_approval_refused", "upgrade_request_approved"} <= set(events)


async def test_with_two_person_approval_off_one_admin_may_approve(h):
    async with h.client() as c:
        await connect(h, c)
        req = (await file_request(h, c)).json()
        assert req["status"] == "pending_approval"
        r = await c.put("/api/system/upgrade-settings", json={"require_two_person_approval": False})
        assert r.status_code == 200 and r.json()["require_two_person_approval"] is False
        h.admin = ALICE
        r = await c.post(f"/api/system/upgrade-requests/{req['id']}/approve")
        assert r.status_code == 200 and r.json()["status"] == "approved"

        # A new request is approved as it is filed.
        await c.post(f"/api/system/upgrade-requests/{req['id']}/cancel")
        r = await file_request(h, c)
        assert r.status_code == 201 and r.json()["status"] == "approved" and r.json()["approved_by"] == "alice"
    changed = [a for a in await h.rows(models.AuditLog) if a.event_type == "upgrade_settings_changed"]
    assert changed and changed[0].details["previous"] is True


async def test_a_restart_needs_one_admin_and_never_runs_beside_another_job(h):
    async with h.client() as c:
        tok = await connect(h, c)
        up = (await file_request(h, c)).json()               # pending approval
        r = await file_request(h, c, action="restart", target_tag=None, reason="worker stuck")
        assert r.status_code == 201 and r.json()["status"] == "approved" and r.json()["target_tag"] is None
        restart = r.json()
        # A second restart while one is queued is refused, and so is a second upgrade.
        assert (await file_request(h, c, action="restart", target_tag=None)).status_code == 409
        assert (await file_request(h, c, admin=BOB)).status_code == 409
        (p,) = (await c.get("/api/internal/updater/requests", headers=bearer(tok))).json()["requests"]
        assert p["action"] == "restart" and p["policy"] == "single" and p["approvals"] == ["alice"]
        # While the restart runs, nothing else can be filed.
        assert (await c.post(f"/api/internal/updater/requests/{restart['id']}/claim", headers=bearer(tok))).status_code == 200
        await c.post(f"/api/system/upgrade-requests/{up['id']}/cancel")
        assert (await file_request(h, c, admin=BOB)).status_code == 409


async def test_cancel_rules(h):
    async with h.client() as c:
        tok = await connect(h, c)
        req = (await file_request(h, c)).json()
        # Any admin may cancel a pending request (stopping needs no second person).
        h.admin = BOB
        r = await c.post(f"/api/system/upgrade-requests/{req['id']}/cancel")
        assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["cancelled_by"] == "bob"
        assert (await c.post(f"/api/system/upgrade-requests/{req['id']}/cancel")).status_code == 409
        assert (await c.post(f"/api/system/upgrade-requests/{req['id']}/approve")).status_code == 409

        # Once claimed it cannot be cancelled from the console.
        r = await file_request(h, c, action="restart", target_tag=None)
        rid = r.json()["id"]
        assert (await c.post(f"/api/internal/updater/requests/{rid}/claim", headers=bearer(tok))).status_code == 200
        r = await c.post(f"/api/system/upgrade-requests/{rid}/cancel")
        assert r.status_code == 409 and "already running" in r.json()["detail"]
        # A cancelled request cannot be claimed.
        assert (await c.post(f"/api/internal/updater/requests/{req['id']}/claim", headers=bearer(tok))).status_code == 409


# ---------------------------------------------------------------------------
# The updater side: claim, steps, outcome, releases
# ---------------------------------------------------------------------------

async def test_only_one_claim_wins(h):
    async with h.client() as c:
        tok = await connect(h, c)
        rid = (await file_request(h, c, action="restart", target_tag=None)).json()["id"]
        url = f"/api/internal/updater/requests/{rid}/claim"
        results = await asyncio.gather(*[c.post(url, headers=bearer(tok)) for _ in range(5)])
        codes = sorted(r.status_code for r in results)
        assert codes == [200, 409, 409, 409, 409], codes
        (row,) = await h.rows(models.UpgradeRequest, models.UpgradeRequest.id == rid)
        assert row.status == "claimed" and row.claimed_at is not None
        assert (await c.post("/api/internal/updater/requests/9999/claim", headers=bearer(tok))).status_code == 404
        assert (await c.post("/api/internal/updater/requests/abc/claim", headers=bearer(tok))).status_code == 404


async def test_a_scheduled_request_waits_for_its_time(h):
    async with h.client() as c:
        tok = await connect(h, c)
        later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        rid = (await file_request(h, c, action="restart", target_tag=None, scheduled_for=later)).json()["id"]
        assert (await c.get("/api/internal/updater/requests", headers=bearer(tok))).json()["requests"] == []
        assert (await c.post(f"/api/internal/updater/requests/{rid}/claim", headers=bearer(tok))).status_code == 409


async def test_steps_and_outcome_drive_the_status_and_email_admins(h):
    async with h.client() as c:
        tok = await connect(h, c)
        req = (await file_request(h, c)).json()
        h.admin = BOB
        await c.post(f"/api/system/upgrade-requests/{req['id']}/approve")
        base = f"/api/internal/updater/requests/{req['id']}"
        # Steps before a claim are refused.
        assert (await c.post(f"{base}/steps", json={"name": "preflight", "status": "ok"}, headers=bearer(tok))).status_code == 409
        assert (await c.post(f"{base}/claim", headers=bearer(tok))).status_code == 200
        step = {"name": "preflight", "status": "ok", "detail": "signature verified", "data": {"big": "x" * 10},
                "duration": 1.2, "at": "2026-10-18T10:00:00+00:00"}
        r = await c.post(f"{base}/steps", json=step, headers=bearer(tok))
        assert r.status_code == 200 and r.json()["status"] == "running"
        await c.post(f"{base}/steps", json={"name": "health", "status": "failed", "detail": "500 on /"}, headers=bearer(tok))
        detail = (await c.get(f"/api/system/upgrade-requests/{req['id']}")).json()
        assert detail["status"] == "running" and [s["step"] for s in detail["steps"]] == ["preflight", "health"]

        outcome = {"outcome": "rolled_back", "summary": "v1.8.0 was unhealthy; rolled back to v1.7.0",
                   "steps": [step], "data": {}, "finished_at": "2026-10-18T10:05:00+00:00"}
        r = await c.post(f"{base}/outcome", json=outcome, headers=bearer(tok))
        assert r.status_code == 200 and r.json()["status"] == "rolled_back"
        detail = (await c.get(f"/api/system/upgrade-requests/{req['id']}")).json()
        assert detail["outcome"] == "rolled_back" and detail["finished_at"].startswith("2026-10-18T10:05")
        assert "rolled back" in detail["outcome_summary"]
        # Finished means finished: no more reports.
        assert (await c.post(f"{base}/outcome", json=outcome, headers=bearer(tok))).status_code == 409
        assert (await c.post(f"{base}/steps", json=step, headers=bearer(tok))).status_code == 409
    assert ("finished", req["id"]) in h.emails
    finished = [a for a in await h.rows(models.AuditLog) if a.event_type == "upgrade_request_finished"]
    assert finished and finished[0].success is False and finished[0].username.startswith("updater:ppu_")


@pytest.mark.parametrize("outcome,status,email", [
    ("succeeded", "succeeded", "finished"),
    ("noop", "succeeded", "finished"),
    ("refused", "refused", "finished"),
    ("needs_approval", "needs_approval", "needs_approval"),
    ("migration_failed", "failed", "finished"),
    ("rollback_failed", "failed", "finished"),
    ("something-new", "failed", "finished"),
])
async def test_outcome_words_map_to_statuses(h, outcome, status, email):
    async with h.client() as c:
        tok = await connect(h, c)
        rid = (await file_request(h, c, action="restart", target_tag=None)).json()["id"]
        await c.post(f"/api/internal/updater/requests/{rid}/claim", headers=bearer(tok))
        r = await c.post(f"/api/internal/updater/requests/{rid}/outcome", json={"outcome": outcome, "summary": "s"},
                         headers=bearer(tok))
        assert r.json()["status"] == status
    assert (email, rid) in h.emails


async def test_the_release_report_replaces_the_list_and_records_what_runs(h):
    async with h.client() as c:
        tok = await connect(h, c)
        listed = (await c.get("/api/system/releases")).json()
        assert listed["updater"]["connected"] is True
        assert listed["updater"]["current"]["version"] == "v1.7.0"
        tags = [r["tag"] for r in listed["releases"]]
        assert "v1.8.0" in tags and len(tags) == 4
        good = next(r for r in listed["releases"] if r["tag"] == "v1.8.0")
        assert good["requestable"] is True and good["gate_passed"] is True and good["attested"] is True
        assert good["notes"].startswith("## Changes")
        bad = next(r for r in listed["releases"] if r["tag"] == "v2.0.0")
        assert bad["requestable"] is False and "not compatible" in bad["refusal"]

        r = await c.put("/api/internal/updater/releases", json={"releases": [RELEASES["releases"][0]]}, headers=bearer(tok))
        assert r.json()["stored"] == 1
        assert [x["tag"] for x in (await c.get("/api/system/releases")).json()["releases"]] == ["v1.8.0"]
        # A non-https notes link is dropped rather than rendered.
        bad_url = {**RELEASES["releases"][0], "url": "javascript:alert(1)"}
        await c.put("/api/internal/updater/releases", json={"releases": [bad_url]}, headers=bearer(tok))
        assert (await c.get("/api/system/releases")).json()["releases"][0]["url"] is None


async def test_writes_are_refused_in_managed_mode(h, monkeypatch):
    from app.core import config

    real = config.get_settings()
    fake = types.SimpleNamespace(**{k: getattr(real, k) for k in ("app_version", "git_sha", "min_db_revision")},
                                 managed_mode=True)
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    import app.core.managed as managed
    monkeypatch.setattr(managed, "get_settings", lambda: fake)
    tok = await h.token()
    async with h.client() as c:
        assert (await file_request(h, c)).status_code == 403
        assert (await c.post("/api/system/updater-tokens", json={})).status_code == 403
        assert (await c.get("/api/internal/updater/requests", headers=bearer(tok))).status_code == 404
        assert (await c.get("/api/system/upgrade-requests")).status_code == 200  # read-only still works


# ---------------------------------------------------------------------------
# The old paths are gone
# ---------------------------------------------------------------------------

def test_system_py_starts_no_processes():
    source = (ROOT / "backend/app/api/system.py").read_text()
    assert "import subprocess" not in source and "subprocess." not in source
    assert not re.search(r"""["']git["']\s*,""", source), "a git argv survived in system.py"
    assert not re.search(r"""["']docker["']\s*,""", source), "a docker argv survived in system.py"
    assert "api.github.com" not in source
    assert not (ROOT / "backend/app/services/self_management.py").exists()


def test_the_git_and_docker_endpoints_are_gone():
    main = pytest.importorskip("app.main")
    from fastapi.routing import APIRoute

    routes = {(m, r.path) for r in main.app.routes if isinstance(r, APIRoute) for m in r.methods}
    for gone in [("POST", "/api/system/update"), ("POST", "/api/system/switch-version"),
                 ("GET", "/api/system/releases/{ref}/security"), ("GET", "/api/system/self-management")]:
        assert gone not in routes, gone
    for kept in [("GET", "/api/system/current-version"), ("GET", "/api/system/releases"),
                 ("POST", "/api/system/upgrade-requests"), ("POST", "/api/system/runbook/{action}")]:
        assert kept in routes, kept


async def test_runbook_restarts_point_at_restart_requests():
    system = pytest.importorskip("app.api.system")
    from fastapi import HTTPException

    for action in ("restart-all", "restart-backend", "restart-caddy"):
        with pytest.raises(HTTPException) as exc:
            await system.execute_runbook(action, backup_name=None, confirm=False, db=None, current_user=ALICE)
        assert exc.value.status_code == 410 and "upgrade-requests" in exc.value.detail


async def test_current_version_reports_the_stamp_and_the_reported_digests(h, monkeypatch):
    system = pytest.importorskip("app.api.system")
    from app.core import config

    fake = types.SimpleNamespace(app_version="1.7.0", git_sha="0123456789abcdef", min_db_revision="d2e4f6a8b0c1",
                                 managed_mode=False)
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    async with h.client() as c:
        await connect(h, c)
    async with h.factory() as s:
        out = await system.get_current_version(db=s, _=ALICE)
    assert out["display"] == "v1.7.0" and out["sha"] == "0123456" and out["git_sha"] == "0123456789abcdef"
    assert out["backend_digest"] == "sha256:" + "1" * 64 and out["frontend_digest"] == "sha256:" + "2" * 64


# ---------------------------------------------------------------------------
# Classification and the proxy rule
# ---------------------------------------------------------------------------

def test_route_access_labels_the_updater_channel():
    main = pytest.importorskip("app.main")
    from fastapi.routing import APIRoute

    from app.core.route_access import ADMIN, UPDATER, access_note, route_access

    internal = [r for r in main.app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/internal/")]
    assert {(m, r.path) for r in internal for m in r.methods} == {
        ("GET", "/api/internal/updater/requests"),
        ("POST", "/api/internal/updater/requests/{request_id}/claim"),
        ("POST", "/api/internal/updater/requests/{request_id}/steps"),
        ("POST", "/api/internal/updater/requests/{request_id}/outcome"),
        ("POST", "/api/internal/updater/requests/{request_id}/heartbeat"),
        ("PUT", "/api/internal/updater/releases"),
    }
    assert all(route_access(r) == UPDATER for r in internal)
    assert "updater token" in access_note(internal[0]).lower()
    admin = [r for r in main.app.routes if isinstance(r, APIRoute)
             and re.match(r"^/api/system/(upgrade-requests|upgrade-settings|updater-tokens|releases$)", r.path)]
    assert len(admin) >= 9 and all(route_access(r) == ADMIN for r in admin)


def test_caddy_refuses_the_internal_prefix_for_every_site():
    caddyfile = (ROOT / "Caddyfile").read_text()
    snippet = caddyfile[caddyfile.index("(pinpoint_site) {"):]
    snippet = snippet[: snippet.index("\n}\n")]
    m = re.search(r"handle /api/internal/\* \{\s*respond 404\s*\}", snippet)
    assert m, "pinpoint_site must answer 404 for /api/internal/*"
    assert m.start() < snippet.index("handle /api/* {")


# ---------------------------------------------------------------------------
# The lease: an updater that stops reporting
# ---------------------------------------------------------------------------

async def _backdate(h, rid, minutes):
    async with h.factory() as s:
        req = await s.get(models.UpgradeRequest, rid)
        req.last_report_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        await s.commit()


async def _claimed_restart(h, c, tok):
    rid = (await file_request(h, c, action="restart", target_tag=None)).json()["id"]
    assert (await c.post(f"/api/internal/updater/requests/{rid}/claim", headers=bearer(tok))).status_code == 200
    return rid


async def _claimed_upgrade(h, c, tok):
    rid = (await file_request(h, c)).json()["id"]
    h.admin = BOB
    await c.post(f"/api/system/upgrade-requests/{rid}/approve")
    assert (await c.post(f"/api/internal/updater/requests/{rid}/claim", headers=bearer(tok))).status_code == 200
    return rid


async def test_a_silent_restart_expires_when_read(h):
    async with h.client() as c:
        tok = await connect(h, c)
        rid = await _claimed_restart(h, c, tok)
        await _backdate(h, rid, 9)
        assert (await c.get(f"/api/system/upgrade-requests/{rid}")).json()["status"] == "claimed"
        await _backdate(h, rid, 11)
        listed = (await c.get("/api/system/upgrade-requests")).json()["requests"][0]
        assert listed["status"] == "failed" and listed["outcome"] == "lease_expired"
        assert listed["outcome_summary"] == "The updater stopped reporting; check the server"
    assert ("finished", rid) in h.emails
    audit = [a for a in await h.rows(models.AuditLog) if a.event_type == "upgrade_request_finished"]
    assert audit and audit[0].username == "system:lease" and audit[0].success is False


async def test_an_upgrade_gets_the_longer_lease_and_reports_renew_it(h, monkeypatch):
    monkeypatch.delenv("UPGRADE_LEASE_MINUTES", raising=False)
    async with h.client() as c:
        tok = await connect(h, c)
        rid = await _claimed_upgrade(h, c, tok)
        await _backdate(h, rid, 40)
        assert (await c.get(f"/api/system/upgrade-requests/{rid}")).json()["status"] == "claimed"
        # A step renews the lease.
        r = await c.post(f"/api/internal/updater/requests/{rid}/steps", json={"name": "backup", "status": "ok"},
                         headers=bearer(tok))
        assert r.status_code == 200
        (row,) = await h.rows(models.UpgradeRequest, models.UpgradeRequest.id == rid)
        assert U.aware(row.last_report_at) > datetime.now(timezone.utc) - timedelta(minutes=1)
        await _backdate(h, rid, 46)
        assert (await c.get(f"/api/system/upgrade-requests/{rid}")).json()["status"] == "failed"
        # The lease is configurable.
        monkeypatch.setenv("UPGRADE_LEASE_MINUTES", "120")
        assert U.lease_minutes("upgrade") == 120 and U.lease_minutes("restart") == 10


async def test_the_updater_pending_call_applies_the_lease_too(h):
    async with h.client() as c:
        tok = await connect(h, c)
        rid = await _claimed_restart(h, c, tok)
        await _backdate(h, rid, 30)
        assert (await c.get("/api/internal/updater/requests", headers=bearer(tok))).status_code == 200
    (row,) = await h.rows(models.UpgradeRequest, models.UpgradeRequest.id == rid)
    assert row.status == "failed" and row.outcome == "lease_expired"
    assert ("finished", rid) in h.emails


@pytest.mark.parametrize("read_first", [True, False])
async def test_a_late_report_from_a_revived_updater_is_refused(h, read_first):
    async with h.client() as c:
        tok = await connect(h, c)
        rid = await _claimed_restart(h, c, tok)
        await _backdate(h, rid, 60)
        if read_first:
            await c.get("/api/system/upgrade-requests")
        r = await c.post(f"/api/internal/updater/requests/{rid}/outcome", json={"outcome": "succeeded", "summary": "ok"},
                         headers=bearer(tok))
        assert r.status_code == 409 and "not applied" in r.json()["detail"]
        r = await c.post(f"/api/internal/updater/requests/{rid}/steps", json={"name": "health", "status": "ok"},
                         headers=bearer(tok))
        assert r.status_code == 409
    (row,) = await h.rows(models.UpgradeRequest, models.UpgradeRequest.id == rid)
    assert row.status == "failed" and row.outcome == "lease_expired"
    assert await h.rows(models.UpgradeRequestStep, models.UpgradeRequestStep.request_id == rid) == []
    late = [a for a in await h.rows(models.AuditLog) if a.event_type == "upgrade_request_late_report"]
    assert len(late) == 2


async def test_the_beat_task_sweeps_expired_requests(h, monkeypatch):
    tasks = pytest.importorskip("app.tasks.upgrades")
    from app.core.celery_app import celery_app
    import app.db.session as session

    entry = celery_app.conf.beat_schedule["upgrade-request-lease"]
    assert entry["task"] == "app.tasks.upgrades.expire_stale_upgrade_requests" and entry["schedule"] == 300
    async with h.client() as c:
        tok = await connect(h, c)
        rid = await _claimed_restart(h, c, tok)
    await _backdate(h, rid, 15)
    monkeypatch.setattr(session, "SessionLocal", h.factory)
    assert await tasks.run_lease_sweep() == [rid]
    assert await tasks.run_lease_sweep() == []          # once only
    (row,) = await h.rows(models.UpgradeRequest, models.UpgradeRequest.id == rid)
    assert row.status == "failed" and ("finished", rid) in h.emails


async def test_an_admin_can_mark_an_in_flight_request_failed(h):
    async with h.client() as c:
        tok = await connect(h, c)
        pending = (await file_request(h, c)).json()["id"]
        assert (await c.post(f"/api/system/upgrade-requests/{pending}/fail")).status_code == 409
        await c.post(f"/api/system/upgrade-requests/{pending}/cancel")
        rid = await _claimed_restart(h, c, tok)
        h.admin = BOB
        r = await c.post(f"/api/system/upgrade-requests/{rid}/fail", json={"reason": "host rebooted"})
        assert r.status_code == 200 and r.json()["status"] == "failed" and r.json()["outcome"] == "marked_failed"
        assert "bob" in r.json()["outcome_summary"] and "host rebooted" in r.json()["outcome_summary"]
        r = await c.post(f"/api/internal/updater/requests/{rid}/outcome", json={"outcome": "succeeded"}, headers=bearer(tok))
        assert r.status_code == 409
    assert ("finished", rid) in h.emails
    marked = [a for a in await h.rows(models.AuditLog) if a.event_type == "upgrade_request_marked_failed"]
    assert marked and marked[0].username == "bob"


async def test_turning_two_person_approval_off_emails_every_admin(h):
    async with h.client() as c:
        await c.put("/api/system/upgrade-settings", json={"require_two_person_approval": True})
        assert h.emails == []
        await c.put("/api/system/upgrade-settings", json={"require_two_person_approval": False})
        assert h.emails == [("two_person_disabled", None, "alice")]
        await c.put("/api/system/upgrade-settings", json={"require_two_person_approval": False})  # already off
        await c.put("/api/system/upgrade-settings", json={"require_two_person_approval": True})   # on: audit only
        assert h.emails == [("two_person_disabled", None, "alice")]
    from app.services import email_layout as L
    subject, blocks = U.compose_settings_email("alice", town="Stafford", L=L)
    text = json.dumps(blocks)
    assert "turned off" in subject and "alice" in text and "require_two_person_approval: true" in text
    changes = [a for a in await h.rows(models.AuditLog) if a.event_type == "upgrade_settings_changed"]
    assert len(changes) == 4


# ---------------------------------------------------------------------------
# Heartbeats keep long steps alive
# ---------------------------------------------------------------------------

async def test_a_heartbeat_renews_the_lease_without_a_step_or_an_audit_entry(h):
    async with h.client() as c:
        tok = await connect(h, c)
        rid = await _claimed_upgrade(h, c, tok)
        audit_before = len(await h.rows(models.AuditLog))
        # A backup running for an hour: beats keep it alive past the 45-minute lease.
        for _ in range(3):
            await _backdate(h, rid, 30)
            r = await c.post(f"/api/internal/updater/requests/{rid}/heartbeat", headers=bearer(tok))
            assert r.status_code == 200 and r.json()["status"] == "claimed"
            assert (await c.get(f"/api/system/upgrade-requests/{rid}")).json()["status"] == "claimed"
        assert await h.rows(models.UpgradeRequestStep, models.UpgradeRequestStep.request_id == rid) == []
        assert len(await h.rows(models.AuditLog)) == audit_before
        # Without beats it expires.
        await _backdate(h, rid, 46)
        assert (await c.get(f"/api/system/upgrade-requests/{rid}")).json()["status"] == "failed"


async def test_a_heartbeat_for_an_expired_finished_or_unclaimed_request_is_refused(h):
    async with h.client() as c:
        tok = await connect(h, c)
        rid = await _claimed_restart(h, c, tok)
        await _backdate(h, rid, 11)
        r = await c.post(f"/api/internal/updater/requests/{rid}/heartbeat", headers=bearer(tok))
        assert r.status_code == 409 and "not applied" in r.json()["detail"]
        (row,) = await h.rows(models.UpgradeRequest, models.UpgradeRequest.id == rid)
        assert row.status == "failed" and row.outcome == "lease_expired"
        assert not [a for a in await h.rows(models.AuditLog) if a.event_type == "upgrade_request_late_report"]
        pending = (await file_request(h, c, action="restart", target_tag=None, scheduled_for=(
            datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())).json()["id"]
        assert (await c.post(f"/api/internal/updater/requests/{pending}/heartbeat", headers=bearer(tok))).status_code == 409
        assert (await c.post("/api/internal/updater/requests/999/heartbeat", headers=bearer(tok))).status_code == 404
        assert (await c.post(f"/api/internal/updater/requests/{rid}/heartbeat")).status_code == 401
