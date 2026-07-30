"""The alert for the one failure that cannot be undone.

Every other proactive check warns about something recoverable -- a full disk, a
stale backup. This one warns about a key that has stopped answering, and it is
different in kind: nothing raises when that happens. `_wrap_dek` falls back to
the application key, new reports save normally, and the rows written under the
old key quietly stop being readable.

If the cause is a scheduled deletion, the window to cancel it is 7 to 30 days.
Silence for that long is the difference between an inconvenience and permanent
loss of every resident's contact details. So the alert has to fire, it has to be
critical, and -- the part that is easy to get wrong -- it has to ask the key
service rather than a cache.
"""

import pytest

pytest.importorskip("cryptography")

from app.services import proactive_health as ph


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_a_key_that_stopped_answering_is_critical(monkeypatch):
    """Selected Azure, actually wrapping with the application key. Recoverable
    only while the deletion window is open, so it does not get to be a warning."""
    from app.core import encryption, pii_crypto

    monkeypatch.setattr(encryption, "_kms_provider", lambda: "azure")
    monkeypatch.setattr(pii_crypto, "probe_backend", lambda: "local")

    check = _run(ph._kms_check())
    assert check["status"] == "critical"
    assert "azure" in check["message"]
    assert check["action"], "a critical check with no action is just bad news"


def test_a_working_key_is_quiet(monkeypatch):
    from app.core import encryption, pii_crypto

    monkeypatch.setattr(encryption, "_kms_provider", lambda: "google")
    monkeypatch.setattr(pii_crypto, "probe_backend", lambda: "google")

    assert _run(ph._kms_check())["status"] == "ok"


def test_no_cloud_kms_is_not_an_alert(monkeypatch):
    """A self-hosted town with no cloud account encrypts with the application
    key by choice. Paging them about it every fifteen minutes forever would
    train them to ignore the alert that matters."""
    from app.core import encryption

    monkeypatch.setattr(encryption, "_kms_provider", lambda: "local")
    assert _run(ph._kms_check())["status"] == "ok"


def test_the_probe_does_not_read_a_cache(monkeypatch):
    """The failure mode this check exists for lasts weeks, and a Celery worker
    stays up for weeks. Reading the data key cached at startup would report the
    state of the world before the key broke, for the entire deletion window."""
    import inspect

    # Comments strip out first: this file explains the distinction at length,
    # and matching the prose would pass while the code did the wrong thing.
    code = "\n".join(
        line for line in inspect.getsource(ph._kms_check).splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "probe_backend()" in code
    assert "active_backend()" not in code


def test_the_probe_does_not_disturb_what_it_measures(monkeypatch):
    """A health check that swapped the process's data key would re-encrypt
    nothing but would make every later reading of `active_backend` wrong."""
    from app.core import pii_crypto

    pii_crypto.clear_caches()
    before = pii_crypto._get_active_dek()
    pii_crypto.probe_backend()
    assert pii_crypto._get_active_dek() == before


def test_the_probe_survives_a_key_service_that_raises(monkeypatch):
    """REQUIRE_KMS makes _wrap_dek raise instead of falling back. The probe has
    to answer, not propagate -- it runs inside a scheduled task."""
    from app.core import pii_crypto

    def _boom(_):
        raise RuntimeError("key is pending deletion")

    monkeypatch.setattr(pii_crypto, "_wrap_dek", _boom)
    assert pii_crypto.probe_backend() == "unknown"


def test_the_check_is_actually_collected():
    """An alert nobody runs is not an alert."""
    import inspect

    assert "_kms_check()" in inspect.getsource(ph.collect_checks)


def test_a_critical_check_escalates_and_emails():
    """The scheduled scan emails admins on escalation into warning/critical.
    Confirming the wiring, since this check's whole value is being noticed
    without anybody opening a dashboard."""
    assert ph.is_worse("critical", "ok")
    assert ph.is_worse("critical", "warning")
    assert ph.rollup_status([{"status": "ok"}, {"status": "critical"}]) == "critical"
