"""EgoBlur's real code path, driven by a tiny scripted model with Gen2's
calling convention (scripts/egoblur_signature.py)."""

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("gen2.script.predictor")

from app.backends.egoblur import EgoBlurDetector  # noqa: E402
from app.config import Settings  # noqa: E402
from app.imaging import prepare, to_fractions  # noqa: E402


@pytest.fixture(scope="module")
def detector(tmp_path_factory):
    import egoblur_signature

    d = tmp_path_factory.mktemp("models")
    egoblur_signature.build_dummy(str(d / "ego_blur_lp_gen2.jit"))
    det = EgoBlurDetector(Settings(models_dir=str(d), threads=1))
    det.load()
    yield det
    det.close()


def test_loads_plate_model_face_optional(detector):
    assert detector.status() == "ok"
    assert detector.kinds() == ["plate"]
    assert not detector.models["face"].present


def test_box_survives_both_resizes_and_bgr_layout(detector, make_image):
    # 2000x1500 -> our 1280 max edge -> EgoBlur's own 1200 resize -> back.
    raw = make_image(2000, 1500, rect=(1000, 900, 1399, 1099))
    image = prepare(raw, 1280, 50_000_000)
    boxes, scores = detector.infer(image, "plate")
    out = to_fractions(boxes, scores, image.width, image.height, "plate")
    # Only the red box survives: the duplicate is removed by NMS, the 0.50
    # box by the 0.74475 threshold, the class-0 box by the class filter.
    assert len(out) == 1
    box = out[0]
    assert box["score"] == pytest.approx(0.95)
    assert box["x0"] == pytest.approx(0.5, abs=0.004) and box["y0"] == pytest.approx(0.6, abs=0.004)
    assert box["x1"] == pytest.approx(0.7, abs=0.004) and box["y1"] == pytest.approx(0.7333, abs=0.004)


def test_blue_is_not_red(detector, make_image):
    # If the tensor were RGB instead of BGR the dummy would see this blue patch as red.
    raw = make_image(800, 600, rect=(100, 100, 300, 200), rect_color=(0, 0, 255))
    boxes, _ = detector.infer(prepare(raw, 1280, 50_000_000), "plate")
    assert boxes == []


def test_threshold_is_configurable(tmp_path, make_image):
    import egoblur_signature

    egoblur_signature.build_dummy(str(tmp_path / "ego_blur_lp_gen2.jit"))
    det = EgoBlurDetector(Settings(models_dir=str(tmp_path), egoblur_lp_threshold=0.3, threads=1))
    det.load()
    try:
        boxes, scores = det.infer(prepare(make_image(800, 600), 1280, 50_000_000), "plate")
        assert scores == [pytest.approx(0.5)]  # the low-score box now passes
    finally:
        det.close()
