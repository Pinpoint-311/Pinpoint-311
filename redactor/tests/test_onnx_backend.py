import numpy as np
import pytest

from app.backends.onnx_yolo import OnnxYoloDetector, decode_end2end, letterbox
from app.config import Settings
from app.imaging import prepare


def test_letterbox_geometry_matches_reference():
    img, r, (dw, dh) = letterbox(np.zeros((480, 1280, 3), np.uint8), 640)
    assert img.shape == (640, 640, 3)
    assert r == 0.5 and dw == 0 and dh == 200
    assert img[0, 0, 0] == 114 and img[300, 300, 0] == 0  # pad above, image below


def test_decode_undoes_letterbox_and_thresholds():
    # A box drawn at (100..300, 250..300) in letterboxed 640 space, ratio .5, pad (0, 200)
    rows = [[0, 100, 250, 300, 300, 0, 0.9], [0, 0, 0, 10, 10, 0, 0.1]]
    boxes, scores = decode_end2end(rows, 0.5, (0, 200), 0.25, 1280, 480)
    assert boxes == [[200.0, 100.0, 600.0, 200.0]] and scores == [0.9]


def _model(path, rows, size=64):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    const = helper.make_tensor("rows", TensorProto.FLOAT, [len(rows), 7], np.array(rows, np.float32).ravel())
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
    onnx.save(model, path)


def test_end_to_end_with_a_fake_model(tmp_path, make_image):
    pytest.importorskip("onnxruntime")
    _model(str(tmp_path / "plate.onnx"), [[0, 16, 24, 48, 40, 0, 0.8]])
    det = OnnxYoloDetector(Settings(models_dir=str(tmp_path), onnx_file="plate.onnx", threads=1))
    det.load()
    assert det.status() == "ok" and det.input_size == 64
    image = prepare(make_image(200, 100), 1280, 50_000_000)
    boxes, scores = det.infer(image, "plate")
    # 200x100 -> ratio .32, 64x32, pad (0, 16): (16,24,48,40) -> (50,25,150,75)
    assert [round(v, 3) for v in boxes[0]] == [50.0, 25.0, 150.0, 75.0]
    assert det.models["plate"].sha256 and det.models["plate"].size_bytes > 0


def test_missing_model_reports_models_missing(tmp_path):
    det = OnnxYoloDetector(Settings(models_dir=str(tmp_path)))
    det.load()
    assert det.status() == "models_missing" and det.kinds() == []


def test_corrupt_model_reports_model_error(tmp_path):
    pytest.importorskip("onnxruntime")
    (tmp_path / "plate_detector.onnx").write_bytes(b"garbage")
    det = OnnxYoloDetector(Settings(models_dir=str(tmp_path)))
    det.load()
    assert det.status() == "model_error" and det.models["plate"].error
