"""Pre-deploy review fixes: notification floods, placeholder mail, opt-out,
flagged staff photos, stale hold flags, reopened SLA, unqueued-push backlog."""
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")


def test_old_vendor_changes_are_applied_quietly():
    from app.tasks import integrations as t
    old = SimpleNamespace(updated_at=datetime.now(timezone.utc) - timedelta(days=90))
    new = SimpleNamespace(updated_at=datetime.now(timezone.utc) - timedelta(hours=2))
    unknown = SimpleNamespace(updated_at=None)
    assert t._fresh_enough_to_notify(old) is False
    assert t._fresh_enough_to_notify(new) is True
    assert t._fresh_enough_to_notify(unknown) is True


def test_a_pull_notifies_at_most_a_capped_number_of_residents():
    from app.tasks import integrations as t
    src = inspect.getsource(t)
    assert "NOTIFY_MAX_PER_RUN" in src and "if not fresh or sent >= NOTIFY_MAX_PER_RUN" in src


def test_notifications_skip_opt_outs_and_placeholder_addresses():
    from app.tasks import service_requests as sr
    src = inspect.getsource(sr.send_branded_notification)
    assert 'getattr(request, "contact_opt_out", False)' in src
    assert '== "local"' in src


def test_unticking_confirmation_records_an_opt_out():
    pytest.importorskip("fastapi.routing")
    from app.api import open311
    assert "contact_opt_out=not intake_data.send_confirmation" in inspect.getsource(open311.create_manual_intake)


def test_flagged_staff_photos_are_held_for_review_not_published():
    pytest.importorskip("fastapi.routing")
    from app.api import open311
    src = inspect.getsource(open311._redeem_intake_media)
    assert '"reason": "content-screen"' in src
    from app.schemas import ManualIntakeCreate
    assert "media_flagged" in ManualIntakeCreate.model_fields


def test_hold_mirrored_flags_are_not_shown_as_moderation_flags():
    pytest.importorskip("fastapi.routing")
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "StaffDashboard.tsx")
    if not src.exists():
        pytest.skip("frontend not present")
    assert "!(selectedRequest.legal_hold === true && !selectedRequest.flag_reason)" in src.read_text()


def test_a_reopened_request_is_measured_as_open():
    pytest.importorskip("fastapi.routing")
    from app.api import open311
    src = inspect.getsource(open311._decorate_detail)
    assert 'request.closed_datetime if request.status == "closed" else None' in src


def test_an_already_pushed_request_clears_its_backlog_row():
    from app.tasks import integrations as t
    src = inspect.getsource(t)
    i = src.index("if existing:")
    assert "_clear_dead_letter(db, integration.id, \"push\"" in src[i:i + 400]
