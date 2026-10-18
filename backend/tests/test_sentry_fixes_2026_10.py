"""Fixes for the errors Sentry reported from staffordnjpilot on 2026-10-18."""

import asyncio
import inspect
from types import SimpleNamespace

import pytest


# ---- /api/services: serialised inside the endpoint, full payload translated --

def _service(**over):
    base = dict(id=1, service_code="PTH", service_name="Pothole", description="Holes",
                icon="Construction", is_active=True, display_order=2, sla_hours=48,
                location_mode="required", hidden_from_public=True, departments=[],
                routing_mode="township", routing_config={}, assigned_department_id=None,
                assigned_department=None)
    base.update(over)
    return SimpleNamespace(**base)


class _DB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _q):
        rows = self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _run_list(lang, monkeypatch):
    services = pytest.importorskip("app.api.services")
    translation = pytest.importorskip("app.services.translation")

    async def fake_translate(item, target):
        return {**item, "service_name": f"[{target}] {item['service_name']}"}

    monkeypatch.setattr(translation, "translate_service_response", fake_translate)
    request = SimpleNamespace(headers={"Accept-Language": lang})
    return asyncio.run(services.list_services(request, _DB([_service()])))


def test_services_are_plain_data_not_orm_objects(monkeypatch):
    out = _run_list("en", monkeypatch)
    assert isinstance(out[0], dict)
    assert out[0]["assigned_department"] is None


def test_translated_services_keep_visibility_and_location_mode(monkeypatch):
    out = _run_list("es", monkeypatch)
    assert out[0]["service_name"] == "[es] Pothole"
    # The hand-built dict dropped these, so defaults made a hidden category
    # public and a location-required one optional for non-English residents.
    assert out[0]["hidden_from_public"] is True
    assert out[0]["location_mode"] == "required"
    assert out[0]["display_order"] == 2


# ---- names that did not exist -------------------------------------------------

def test_task_module_has_a_logger():
    tasks = pytest.importorskip("app.tasks.service_requests")
    assert hasattr(tasks, "logger")


def test_gis_has_a_logger():
    gis = pytest.importorskip("app.api.gis")
    assert hasattr(gis, "logger")


# ---- forked workers get their own psycopg2 connections -----------------------

def test_children_drop_inherited_sync_connections():
    celery_app = pytest.importorskip("app.core.celery_app")
    src = inspect.getsource(celery_app._fresh_sync_pool_in_child)
    assert "dispose(close=False)" in src
    module = inspect.getsource(celery_app)
    # Registered for forked children, before the crash-reporting hook that
    # reads the Sentry DSN through the sync engine.
    assert module.index("worker_process_init.connect(_fresh_sync_pool_in_child)") < \
        module.index("worker_process_init.connect(_crash_reporting_in_worker)")


# ---- SMTP cannot hang a task forever --------------------------------------------

def test_smtp_connections_have_a_timeout(monkeypatch):
    notifications = pytest.importorskip("app.services.notifications")
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            seen["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, *a):
            pass

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notifications.smtplib, "SMTP_SSL", FakeSMTP)
    src = inspect.getsource(notifications)
    assert src.count("timeout=SMTP_TIMEOUT_SECONDS") == 2
    assert notifications.SMTP_TIMEOUT_SECONDS == 30


# ---- background tasks are kept alive and drained -----------------------------

def test_spawned_tasks_survive_and_drain_waits_for_them():
    background = pytest.importorskip("app.core.background")
    done = []

    async def write():
        await asyncio.sleep(0.05)
        done.append(True)

    async def main():
        assert background.spawn(write())
        await background.drain(timeout=2)

    asyncio.run(main())
    assert done == [True]


def test_spawn_without_a_loop_says_so():
    background = pytest.importorskip("app.core.background")

    async def write():
        pass

    assert background.spawn(write()) is False


# ---- translation cache tolerates duplicate rows ------------------------------

def test_translation_cache_reads_the_first_match():
    translation = pytest.importorskip("app.services.translation")
    for fn in (translation.get_cached_translation, translation.save_translation_to_cache):
        src = inspect.getsource(fn)
        assert "result.scalar_one_or_none()" not in src and "result.scalars().first()" in src


# ---- health checks follow the configured provider ------------------------------

def _secrets(monkeypatch, values):
    sm = pytest.importorskip("app.services.secret_manager")

    async def fake_get(key):
        return values.get(key)

    monkeypatch.setattr(sm, "get_secret", fake_get)
    switches = pytest.importorskip("app.services.capability_switches")

    async def on(_cap):
        return True

    monkeypatch.setattr(switches, "enabled", on)


def test_ai_health_names_the_selected_provider_not_google(monkeypatch):
    health = pytest.importorskip("app.api.health")
    registry = pytest.importorskip("app.services.ai.registry")
    _secrets(monkeypatch, {"AI_PROVIDER": "azure"})

    async def no_provider(db=None):
        return None

    monkeypatch.setattr(registry, "get_ai_provider", no_provider)
    out = asyncio.run(health.check_vertex_ai(None))
    assert out["provider"] == "azure" and out["status"] == "not_configured"
    assert "GCP" not in out["message"] and "Vertex" not in out["message"]


def test_translation_health_does_not_read_the_maps_key(monkeypatch):
    health = pytest.importorskip("app.api.health")
    tp = pytest.importorskip("app.services.translation_providers")
    _secrets(monkeypatch, {"TRANSLATION_PROVIDER": "aws", "GOOGLE_MAPS_API_KEY": "maps-key"})

    async def none():
        return None

    monkeypatch.setattr(tp, "get_translation_provider", none)
    out = asyncio.run(health.check_translation_api(None))
    assert out["provider"] == "aws" and out["status"] == "not_configured"
    assert "Maps" not in out["message"]
