"""On-server plate model (YOLOv9 ONNX) and face fallback (YuNet) in the
synchronous redaction path.

Pinned here:
  * a plate the model finds is blurred, with the existing padding and blur;
  * the model is used by default once its file is present, the OCR heuristic
    otherwise, and the heuristic is NOT also run unless PLATE_OCR_UNION is on;
  * a configured model that is missing, broken or too slow withholds the photo
    (fail closed) -- it never reads as "no plates";
  * faces: cloud -> YuNet -> withhold, with the detector that ran recorded;
  * the model holder loads once, lazily, and unloads when idle.
"""

import asyncio
import base64
import io
import threading
import time

import numpy as np
import pytest

pytest.importorskip("cryptography")
pytest.importorskip("PIL")

from app.services import image_redaction as ir  # noqa: E402
from app.services import onnx_detectors as od  # noqa: E402


# ------------------------------------------------------------------ fixtures

def _photo(w=400, h=300) -> str:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (w, h), (90, 120, 90))
    d = ImageDraw.Draw(im)
    for x in range(200, 300, 4):            # a striped "plate" at (0.5..0.75, 0.66..0.8)
        d.line([(x, 200), (x, 240)], fill=(255, 255, 255), width=2)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _img(media):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(media.split(",", 1)[1]))).convert("RGB")


def _spread(im, y=220):
    row = [sum(im.getpixel((x, y))) for x in range(200, 300)]
    return max(row) - min(row)


def _end2end_model(path, rows, size=64):
    """A tiny ONNX graph with the open-image-models end2end I/O signature:
    images [1,3,S,S] float32 -> rows [N,7] (batch, x1, y1, x2, y2, class, score)."""
    onnx = pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    from onnx import TensorProto, helper

    const = helper.make_tensor("rows", TensorProto.FLOAT, [len(rows), 7],
                               np.array(rows, np.float32).ravel())
    graph = helper.make_graph(
        [helper.make_node("ReduceMax", ["images"], ["unused"], keepdims=0),
         helper.make_node("Constant", [], ["output"], value=const)],
        "fake_end2end",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, size, size])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [len(rows), 7]),
         helper.make_tensor_value_info("unused", TensorProto.FLOAT, [])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))


@pytest.fixture
def secrets(monkeypatch):
    values = {}

    async def get_secret(key):
        return values.get(key)

    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", get_secret)
    return values


@pytest.fixture
def models(tmp_path, monkeypatch):
    monkeypatch.setenv("PINPOINT_MODELS_DIR", str(tmp_path))
    monkeypatch.delenv("PLATE_MODEL_FILE", raising=False)
    monkeypatch.delenv("FACE_MODEL_FILE", raising=False)
    od.plate_holder.unload()
    od.face_holder.unload()
    yield tmp_path
    od.plate_holder.unload()
    od.face_holder.unload()


@pytest.fixture
def plate_model(models):
    # 400x300 photo -> letterbox 64: ratio .16, 64x48, pad (0, 8).
    # Plate at (200..300, 200..240) px -> (32..48, 40..46.4) letterboxed.
    _end2end_model(models / od.DEFAULT_PLATE_MODEL, [[0, 32, 40, 48, 46.4, 0, 0.9]])
    return models


@pytest.fixture
def local_spy(monkeypatch):
    calls = []

    async def local(raw, w, h, faces, plates):
        calls.append((faces, plates))
        return []

    async def usable(p):
        return p == "local"

    monkeypatch.setattr(ir, "_local_detect", local)
    monkeypatch.setattr(ir, "_usable", usable)
    return calls


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ plates

def test_a_plate_the_model_finds_is_blurred(plate_model, secrets, local_spy):
    media = _photo()
    result = run(ir.redact_image(media, "local", True, True))
    assert result.changed and result.plates == 1 and result.faces == 0
    assert _spread(_img(media)) > 300 and _spread(_img(result.media)) < 150
    far_after, far_before = _img(result.media).getpixel((20, 20)), _img(media).getpixel((20, 20))
    assert all(abs(a - b) <= 3 for a, b in zip(far_after, far_before)), "JPEG rounding only"


def test_the_model_is_the_default_once_installed_and_ocr_is_not_also_run(plate_model, secrets, local_spy):
    assert run(ir.plate_detector()) == "yolo"
    run(ir.redact_image(_photo(), "local", True, True))
    assert local_spy == [(True, False)], "faces only: the OCR plate heuristic stays off"


def test_union_with_ocr_is_opt_in(plate_model, secrets, local_spy):
    secrets["PLATE_OCR_UNION"] = "true"
    run(ir.redact_image(_photo(), "local", True, True))
    assert local_spy == [(True, True)]


def test_without_a_model_file_it_is_ocr_as_before(models, secrets, local_spy):
    assert run(ir.plate_detector()) == "ocr"
    result = run(ir.redact_image(_photo(), "local", True, True))
    assert local_spy == [(True, True)]
    assert result.skipped_reason == "no-detections"


def test_selected_but_missing_withholds_the_photo(models, secrets, local_spy):
    secrets["PLATE_DETECTOR"] = "yolo"
    result = run(ir.redact_image(_photo(), "local", True, True))
    assert result.skipped_reason == "plate-detector-error"
    assert "plate-detector-error" in ir.WITHHOLD_REASONS
    batch_secrets_media = _photo()

    async def settings():
        return ("local", True, True)

    ir_settings = ir.settings
    ir.settings = settings
    try:
        batch = run(ir.redact_media([batch_secrets_media]))
    finally:
        ir.settings = ir_settings
    assert batch.media == [] and batch.withheld[0]["reason"] == "plate-detector-error"


def test_a_corrupt_model_withholds_the_photo(models, secrets, local_spy):
    pytest.importorskip("onnxruntime")
    (models / od.DEFAULT_PLATE_MODEL).write_bytes(b"not a model")
    result = run(ir.redact_image(_photo(), "local", True, True))
    assert result.skipped_reason == "plate-detector-error"
    assert od.plate_holder.status()["error"]


def test_the_plate_model_is_bounded_in_time(plate_model, secrets, local_spy, monkeypatch):
    def slow(raw):
        time.sleep(2)
        return []

    monkeypatch.setattr(od, "detect_plates", slow)
    monkeypatch.setattr(ir, "PLATE_MODEL_TIMEOUT_S", 0.2)
    async def timed():
        started = time.monotonic()
        result = await ir.redact_image(_photo(), "local", True, True)
        return result, time.monotonic() - started

    result, took = run(timed())
    assert result.skipped_reason == "plate-detector-error"
    assert took < 1.5, "the resident's request does not wait for a stuck model"


def test_plates_off_runs_no_plate_detector(plate_model, secrets, local_spy):
    secrets["PLATE_DETECTOR"] = "off"
    result = run(ir.redact_image(_photo(), "local", True, True))
    assert local_spy == [(True, False)] and result.plates == 0


def test_the_google_combined_path_uses_the_model_too(plate_model, secrets, monkeypatch):
    from app.services import cloud_moderation

    seen = {}

    async def annotate(probe, features):
        seen["features"] = [f["type"] for f in features]
        return {"responses": [{}]}

    monkeypatch.setattr(cloud_moderation, "vision_annotate", annotate)
    verdict, result = run(ir._google_screen_and_redact_one(_photo(), True, True))
    assert "TEXT_DETECTION" not in seen["features"]
    assert result.plates == 1


# ------------------------------------------------------------------ faces

def _rejecting(monkeypatch):
    async def fail(*a, **kw):
        raise RuntimeError("429 quota exceeded")

    async def usable(_p):
        return True

    monkeypatch.setattr(ir, "_azure_detect", fail)
    monkeypatch.setattr(ir, "_usable", usable)


def test_cloud_failure_falls_back_to_yunet_and_says_so(models, secrets, monkeypatch):
    (models / od.DEFAULT_FACE_MODEL).write_bytes(b"x")       # "installed"
    _rejecting(monkeypatch)
    calls = []

    def faces(raw):
        calls.append(1)
        return [(0.1, 0.1, 0.3, 0.4, 0.9)]

    monkeypatch.setattr(od, "detect_faces", faces)
    secrets["PLATE_DETECTOR"] = "off"
    result = run(ir.redact_image(_photo(), "azure", True, True))
    assert calls == [1]
    assert result.faces == 1 and result.detector == "yunet-fallback"


def test_yunet_failing_withholds_rather_than_dropping_to_haar(models, secrets, monkeypatch):
    (models / od.DEFAULT_FACE_MODEL).write_bytes(b"x")
    _rejecting(monkeypatch)

    def broken(raw):
        raise od.ModelUnavailable("face: failed to load")

    monkeypatch.setattr(od, "detect_faces", broken)
    secrets["PLATE_DETECTOR"] = "off"
    result = run(ir.redact_image(_photo(), "azure", True, True))
    assert result.skipped_reason == "no-detector"


def test_fallback_off_withholds_without_trying_on_server(models, secrets, monkeypatch, local_spy):
    _rejecting(monkeypatch)
    secrets.update(FACE_FALLBACK="off", PLATE_DETECTOR="off")
    result = run(ir.redact_image(_photo(), "azure", True, True))
    assert result.skipped_reason == "no-detector" and local_spy == []


def test_without_yunet_the_haar_cascades_still_answer(models, secrets, monkeypatch):
    _rejecting(monkeypatch)
    secrets["PLATE_DETECTOR"] = "off"
    assert run(ir.face_fallback()) == "opencv"
    result = run(ir.redact_image(_photo(), "azure", True, True))
    assert result.skipped_reason == "no-detections" and result.detector == "opencv-fallback"


def test_choices_and_aliases(models, secrets):
    assert run(ir.face_fallback()) == "opencv"
    (models / od.DEFAULT_FACE_MODEL).write_bytes(b"x")
    assert run(ir.face_fallback()) == "yunet"
    secrets["FACE_FALLBACK"] = "haar"
    assert run(ir.face_fallback()) == "opencv"
    secrets["PLATE_DETECTOR"] = "onnx"
    assert run(ir.plate_detector()) == "yolo"
    secrets["PLATE_DETECTOR"] = "nonsense"
    assert run(ir.plate_detector()) == "ocr"


# ------------------------------------------------------------------ the holder

def test_loads_once_lazily_and_unloads_when_idle(models, monkeypatch):
    (models / "m.bin").write_bytes(b"x")
    loads = []

    def loader(path):
        time.sleep(0.05)
        loads.append(path)
        return object()

    holder = od._Holder("test", lambda: str(models / "m.bin"), loader)
    assert not holder.loaded and loads == []
    threads = [threading.Thread(target=holder.get) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(loads) == 1 and holder.loaded

    monkeypatch.setenv("MODEL_IDLE_UNLOAD_S", "60")
    assert holder.unload_if_idle(now=holder.last_used + 30) is False
    assert holder.unload_if_idle(now=holder.last_used + 61) is True
    assert not holder.loaded
    holder.get()
    assert len(loads) == 2, "reloaded on demand"


def test_missing_file_is_an_error_not_an_empty_result(models):
    with pytest.raises(od.ModelUnavailable):
        od.detect_plates(base64.b64decode(_photo().split(",", 1)[1]))


def test_session_options_keep_memory_down():
    pytest.importorskip("onnxruntime")
    opts = od.session_options()
    assert opts.enable_cpu_mem_arena is False and opts.enable_mem_pattern is False
    assert opts.inter_op_num_threads == 1 and opts.intra_op_num_threads >= 1


def test_letterbox_and_decode_round_trip():
    canvas, r, pad = od.letterbox(np.zeros((480, 1280, 3), np.uint8), 640)
    assert canvas.shape == (640, 640, 3) and r == 0.5 and pad == (0.0, 200.0)
    boxes = od.decode_end2end([[0, 100, 250, 300, 300, 0, 0.9], [0, 0, 0, 9, 9, 0, 0.1]],
                              r, pad, 0.25, 1280, 480)
    assert boxes == [(200 / 1280, 100 / 480, 600 / 1280, 200 / 480, 0.9)]


def test_google_mid_call_failure_falls_back_to_on_server(monkeypatch):
    """Parity with the AWS/Azure path: a Vision failure during the combined
    call tries the on-server detectors instead of withholding outright."""
    import asyncio
    import app.services.image_redaction as ir
    import app.services.cloud_moderation as cm

    async def boom(*a, **k):
        raise RuntimeError("vision down")

    async def fallback():
        return "yunet"

    async def usable(_):
        return True

    calls = {}

    async def fake_redact(media, provider, faces, plates):
        calls["provider"] = provider
        return ir.RedactionResult(media, faces=1, changed=True)

    async def no_plates():
        return "off"

    monkeypatch.setattr(cm, "vision_annotate", boom)
    monkeypatch.setattr(ir, "face_fallback", fallback)
    monkeypatch.setattr(ir, "_usable", usable)
    monkeypatch.setattr(ir, "redact_image", fake_redact)
    monkeypatch.setattr(ir, "plate_detector", no_plates)
    async def no_quota(*a, **k):
        return None
    import app.services.connector_health as ch
    monkeypatch.setattr(ch, "note_quota_failure", no_quota)

    from PIL import Image
    import io, base64
    buf = io.BytesIO(); Image.new("RGB", (64, 64), (120, 120, 120)).save(buf, "JPEG")
    media = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    verdict, result = asyncio.run(ir._google_screen_and_redact_one(media, True, True))
    assert calls["provider"] == "local"
    assert result.detector == "yunet-fallback" and result.skipped_reason == ""
    assert not verdict.should_block
