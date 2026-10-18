import time

import pytest
from fastapi.testclient import TestClient

from app.backends.base import Detector, ModelFile
from app.config import Settings
from app.main import build_app


class Fake(Detector):
    name = "fake"

    def __init__(self, settings, loaded=("plate",), delay=0.0):
        super().__init__(settings)
        self.models = {k: ModelFile(k, f"{k}.bin") for k in ("plate", "face")}
        self._loaded = loaded
        self.delay = delay
        self.calls = 0

    def load(self):
        for k in self._loaded:
            self.models[k].present = self.models[k].loaded = True

    def infer(self, image, kind):
        self.calls += 1
        time.sleep(self.delay)
        return [[image.width * 0.25, image.height * 0.5, image.width * 0.75, image.height]], [0.9]


def client(settings=None, **kw):
    settings = settings or Settings()
    return TestClient(build_app(settings, Fake(settings, **kw)))


def test_detect_returns_fractions(make_image):
    with client() as c:
        r = c.post("/detect", content=make_image(400, 200))
    assert r.status_code == 200
    assert r.json()["detections"] == [{"x0": 0.25, "y0": 0.5, "x1": 0.75, "y1": 1.0, "score": 0.9, "kind": "plate"}]


def test_models_missing_never_fakes_a_result(make_image):
    with client(loaded=()) as c:
        assert c.get("/health").json()["status"] == "models_missing"
        r = c.post("/detect", content=make_image(10, 10))
    assert r.status_code == 503 and r.json()["detail"] == "models_missing"


def test_asking_for_a_kind_without_a_model_is_503(make_image):
    with client() as c:
        r = c.post("/detect?kinds=plate,face", content=make_image(10, 10))
    assert r.status_code == 503 and r.json()["missing"] == ["face"]


def test_size_limit(make_image):
    with client(Settings(max_bytes=2048)) as c:
        r = c.post("/detect", content=b"x" * 4096)
    assert r.status_code == 413


def test_bad_input():
    with client() as c:
        assert c.post("/detect", content=b"").status_code == 400
        assert c.post("/detect", content=b"not an image").json()["detail"] == "unreadable-image"
        assert c.post("/detect?kinds=car", content=b"x").status_code == 400


def test_timeout(make_image):
    with client(Settings(timeout_s=1.0), delay=1.5) as c:
        r = c.post("/detect", content=make_image(10, 10))
    assert r.status_code == 504


def test_health_reports_backend_models_and_versions():
    with client() as c:
        h = c.get("/health").json()
    assert h["status"] == "ok" and h["backend"] == "fake" and h["kinds"] == ["plate"]
    assert {m["kind"] for m in h["models"]} == {"plate", "face"}
    assert "python" in h["versions"] and h["settings"]["max_edge"] == 1280


def test_unknown_backend_is_reported_not_crashed():
    with TestClient(build_app(Settings(backend="nope"))) as c:
        h = c.get("/health").json()
    assert h["status"] == "config_error" and "nope" in h["error"]
