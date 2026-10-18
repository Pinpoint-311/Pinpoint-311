"""End-to-end YOLO ONNX plate detector as a backend (onnxruntime, CPU).

Written for the open-image-models "license-plate-end2end" exports
(github.com/ankandrew/open-image-models, MIT), whose graphs include NMS, and
follows that project's own pre/post-processing so the published accuracy
applies. References are to its yolo_v9 module at the commit evaluated:

* Input size is read from the model's input shape, which must be square
  (yolo_v9/inference.py:79-85).
* Pre-processing: letterbox to the input size keeping aspect ratio, pad value
  114, scale-up allowed (preprocess.py `letterbox`); then HWC->CHW and BGR->RGB,
  /255, float32, batch dim (preprocess.py `preprocess`). Their input is a cv2
  BGR image, so "BGR->RGB" means the model wants RGB -- which is what we hold.
* Output: one row per kept box, [batch_idx, x1, y1, x2, y2, class_id, score]
  in letterboxed pixels (postprocess.py: bboxes = [:, 1:5], class = [:, 5],
  score = [:, 6]); un-letterboxed as (v - pad) / ratio.
* Threshold: score >= 0.25 by default (inference.py:66), configurable.

Any other ONNX detector with the same end-to-end output layout drops in by
changing REDACTOR_ONNX_MODEL.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Tuple

from app.backends.base import Detector, ModelFile
from app.imaging import Prepared


def letterbox(rgb, size: int, pad: int = 114):
    """Resize keeping aspect ratio and pad to size x size.

    Returns (image, ratio, (dw, dh)) with the same geometry as the reference
    (preprocess.py letterbox): unpadded size rounded, padding split in two with
    the -0.1/+0.1 trick so odd padding goes bottom/right. The resize itself is
    Pillow bilinear rather than cv2.INTER_LINEAR, so this image does not carry
    OpenCV (~75 MB); on the evaluation set the detections were the same.
    """
    import numpy as np
    from PIL import Image

    h, w = rgb.shape[:2]
    r = min(size / h, size / w)
    new_w, new_h = int(round(w * r)), int(round(h * r))
    dw, dh = (size - new_w) / 2, (size - new_h) / 2
    if (w, h) != (new_w, new_h):
        rgb = np.asarray(Image.fromarray(rgb).resize((new_w, new_h), Image.BILINEAR))
    top = int(round(dh - 0.1))
    left = int(round(dw - 0.1))
    canvas = np.full((size, size, 3), pad, dtype=np.uint8)
    canvas[top:top + new_h, left:left + new_w] = rgb
    return canvas, r, (dw, dh)


def decode_end2end(rows, ratio: float, pad: Tuple[float, float], threshold: float,
                   width: int, height: int) -> Tuple[List[List[float]], List[float]]:
    """[batch, x1, y1, x2, y2, cls, score] rows -> boxes in the input frame."""
    boxes: List[List[float]] = []
    scores: List[float] = []
    dw, dh = pad
    for row in rows:
        row = [float(v) for v in list(row)]
        if len(row) < 7:
            continue
        score = row[6]
        if score < threshold:
            continue
        x0 = (row[1] - dw) / ratio
        y0 = (row[2] - dh) / ratio
        x1 = (row[3] - dw) / ratio
        y1 = (row[4] - dh) / ratio
        boxes.append([max(0.0, min(width, x0)), max(0.0, min(height, y0)),
                      max(0.0, min(width, x1)), max(0.0, min(height, y1))])
        scores.append(score)
    return boxes, scores


class OnnxYoloDetector(Detector):
    name = "onnx"

    def __init__(self, settings):
        super().__init__(settings)
        self.models = {"plate": ModelFile("plate", settings.onnx_file, required=True)}
        self._lock = threading.Lock()
        self.input_size = 0

    def _open(self, path: str, kind: str) -> Any:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = self.settings.threads
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session = ort.InferenceSession(path, sess_options=opts,
                                       providers=["CPUExecutionProvider"])
        shape = session.get_inputs()[0].shape  # [batch, 3, H, W]
        h, w = shape[2], shape[3]
        if not (isinstance(h, int) and isinstance(w, int)) or h != w:
            raise ValueError(f"expected a fixed square input, got {shape}")
        self.input_size = int(h)
        return session

    def describe(self) -> Dict[str, Any]:
        return {"threshold": self.settings.onnx_threshold, "input_size": self.input_size}

    def infer(self, image: Prepared, kind: str) -> Tuple[List[List[float]], List[float]]:
        import numpy as np

        session = self.models[kind].handle
        boxed, ratio, pad = letterbox(image.rgb, self.input_size)
        tensor = (boxed.transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        with self._lock:
            out = session.run([session.get_outputs()[0].name],
                              {session.get_inputs()[0].name: tensor})[0]
        rows = np.asarray(out).reshape(-1, np.asarray(out).shape[-1]) if np.asarray(out).size else []
        return decode_end2end(rows, ratio, pad, self.settings.onnx_threshold,
                              image.width, image.height)
