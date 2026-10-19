"""Crash reporting starts from the DSN saved on the setup page, not only from
an environment variable. Live, a town's saved DSN was never read, so it had no
crash reporting and nothing said so."""
import asyncio

import pytest

pytest.importorskip("sentry_sdk")
cr = pytest.importorskip("app.core.crash_reporting")


@pytest.fixture
def no_env(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(cr, "is_active", lambda: False)


def test_the_saved_credential_is_used_when_no_env_var_is_set(no_env, monkeypatch):
    started = []
    monkeypatch.setattr(cr, "init", lambda dsn, source: started.append((dsn, source)) or True)

    async def saved():
        return "https://key@o1.ingest.us.sentry.io/2"

    monkeypatch.setattr(cr, "_saved_dsn", saved)
    assert asyncio.run(cr.init_from_saved_credential()) is True
    assert started == [("https://key@o1.ingest.us.sentry.io/2", "saved credential")]


def test_the_environment_wins_when_set(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://env@o1.ingest.us.sentry.io/3")
    monkeypatch.setattr(cr, "is_active", lambda: False)
    started = []
    monkeypatch.setattr(cr, "init", lambda dsn, source: started.append(source) or True)

    async def saved():
        raise AssertionError("must not read the saved DSN when the env var is set")

    monkeypatch.setattr(cr, "_saved_dsn", saved)
    assert asyncio.run(cr.init_from_saved_credential()) is True
    assert started == ["environment"]


def test_nothing_saved_means_nothing_started(no_env, monkeypatch):
    async def saved():
        return None

    monkeypatch.setattr(cr, "_saved_dsn", saved)
    monkeypatch.setattr(cr, "init", lambda *a: pytest.fail("started without a DSN"))
    assert asyncio.run(cr.init_from_saved_credential()) is False


def test_the_worker_starts_it_too():
    from pathlib import Path
    src = (Path(cr.__file__).parent / "celery_app.py").read_text(encoding="utf-8")
    assert "worker_process_init.connect(_crash_reporting_in_worker)" in src


def test_reports_never_carry_pii():
    import inspect
    assert "send_default_pii=False" in inspect.getsource(cr.init)
