"""Sentry is told which build an error came from (needed for suspect commits)."""
import pytest

pytest.importorskip("sentry_sdk")
from app.core import crash_reporting


def test_release_comes_from_the_image_stamp(monkeypatch):
    monkeypatch.setenv("PINPOINT_VERSION", "1.9.0")
    monkeypatch.setenv("GIT_SHA", "abc123")
    assert crash_reporting.release_name() == "pinpoint-311@1.9.0"
    monkeypatch.setenv("PINPOINT_VERSION", "")
    assert crash_reporting.release_name() == "abc123"
    monkeypatch.delenv("GIT_SHA")
    assert crash_reporting.release_name() is None


def test_init_passes_the_release(monkeypatch):
    seen = {}
    import sentry_sdk
    monkeypatch.setattr(crash_reporting, "is_active", lambda: bool(seen))
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    monkeypatch.setenv("PINPOINT_VERSION", "2.0.0")
    crash_reporting.init("https://k@o0.ingest.sentry.io/1", "test")
    assert seen["release"] == "pinpoint-311@2.0.0"
    assert seen["send_default_pii"] is False
