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


def test_sentry_really_starts_with_the_installed_web_framework():
    """Not mocked: the real sentry_sdk.init with its FastAPI/Starlette integrations.

    Starlette 1.3 with sentry-sdk 2.54 raised ImportError("jinja2 must be
    installed...") inside init, and the API refused to start on every instance
    with crash reporting turned on -- which the rest of this suite, running
    without a DSN, never exercised.
    """
    import sentry_sdk
    try:
        assert crash_reporting.init("https://public@o0.ingest.sentry.io/1", "test") is True
    finally:
        client = sentry_sdk.get_client()
        if client.is_active():
            client.close(timeout=0)
        sentry_sdk.init(dsn=None)
