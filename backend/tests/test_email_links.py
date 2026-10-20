"""Links in emails go to the site residents use, never to localhost.

The worker that sends notifications was not given DOMAIN by docker-compose.yml,
and the fallback after `custom_domain` and DOMAIN was "http://localhost:5173".
So on every instance without a custom domain, each "Track your request" button
pointed at localhost.
"""
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_worker_is_given_the_sites_address():
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for svc in ("backend", "worker"):
        assert "DOMAIN" in compose["services"][svc]["environment"], svc


def test_no_email_path_falls_back_to_localhost():
    src = (ROOT / "backend/app/tasks/service_requests.py").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("#", '"', "Was ")))
    assert "localhost:5173" not in code


def test_without_an_address_the_link_is_left_out_not_broken():
    from app.services import email_templates as T
    assert T._tracking_url("", "REQ-1") is None
    assert T._tracking_url("https://311.example.gov/", "REQ-1") == "https://311.example.gov/#track/REQ-1"
    assert T._absolute("/api/uploads/a.jpg", "") is None
    assert T._button("Track", None) is None


def test_the_rendered_email_has_the_real_link_or_none():
    from app.services import email_templates as T
    i18n = {}
    _, blocks, _ = T._confirmation_parts(i18n, "Springfield", "REQ-9", "Pothole", "Hole", "1 Main St",
                                         "https://311.springfield.example")
    assert any(b and b.get("url") == "https://311.springfield.example/#track/REQ-9" for b in blocks if isinstance(b, dict))
    _, blocks, _ = T._confirmation_parts(i18n, "Springfield", "REQ-9", "Pothole", "Hole", "1 Main St", "")
    assert not any(isinstance(b, dict) and "localhost" in str(b) for b in blocks)
    assert not any(isinstance(b, dict) and b.get("url") for b in blocks)


async def test_the_task_uses_the_same_lookup_as_the_rest_of_the_app(monkeypatch):
    from app.tasks import service_requests as task
    import app.api.system as system

    async def origin(db):
        return "https://311.springfield.example"
    monkeypatch.setattr(system, "public_origin", origin)
    assert await task._portal_url(None) == "https://311.springfield.example"

    async def nothing(db):
        return None
    monkeypatch.setattr(system, "public_origin", nothing)
    assert await task._portal_url(None) == ""


def test_the_worker_can_delete_the_photos_retention_clears():
    """Scheduled retention runs in the worker. Without the uploads volume (and
    UPLOAD_DIR) it cleared photo links and left every file on disk."""
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    backend, worker = compose["services"]["backend"], compose["services"]["worker"]
    assert worker["environment"]["UPLOAD_DIR"] == backend["environment"]["UPLOAD_DIR"]
    assert any(str(v).startswith("uploads_data:") for v in worker["volumes"])
