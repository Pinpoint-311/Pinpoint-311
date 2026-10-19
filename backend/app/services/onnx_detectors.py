"""On-server detectors for photo redaction: a licence-plate model and a face model.

Plates: no cloud vendor sells a plate detector, so the cloud path infers plates
from OCR text (image_redaction.plate_like), which needs a digit -- vanity
plates ("CRAZYGUY", "KATYDID") were published unblurred -- and also blurs street
signs ("243 ST") and bus displays. A real detector fixes both. The default is
YOLOv9-s-608 from open-image-models (ankandrew), run with onnxruntime: ~29 MB,
~0.5 s a photo on two aarch64 cores, and it found 20/20 plates on the
evaluation set, both vanity plates included.

Faces: the town's cloud provider stays the face detector. When it cannot answer,
OpenCV's YuNet (opencv_zoo, MIT, 230 KB) is the on-server fallback, in place of
the 2001-era Haar cascades.

Weights are never bundled. Each town downloads them into the models directory
(default /models, mounted read-only into the backend); see
docs/PHOTO_REDACTION_MODELS.md for URLs, checksums and licences.

Memory: one copy, loaded on first use, dropped when idle
--------------------------------------------------------
Only the API process runs photo redaction (intake and the pick-time screen), so
that is the only process that ever loads these; the Celery worker never imports
a detector, and its prefork children therefore hold nothing. Inside the process
there is one module-level holder per model, created lazily on the first photo
and released after MODEL_IDLE_UNLOAD_S (default 10 minutes) with no use, so an
idle town pays nothing for having them configured.

Session options are chosen for a small resident set rather than peak
throughput: no CPU memory arena and no memory-pattern pre-allocation (each
otherwise holds on to the largest activation buffer ever needed), one
inter-op thread, ONNX_THREADS intra-op threads (default 2).
"""

from __future__ import annotations

import gc
import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MODELS_DIR = "/models"
DEFAULT_PLATE_MODEL = "yolo-v9-s-608-license-plates-end2end.onnx"
DEFAULT_FACE_MODEL = "face_detection_yunet_2023mar.onnx"

# open-image-models' own default (yolo_v9/inference.py). Measured on the
# evaluation set at 0.25 / 0.4 / 0.6: 0.25 found every plate.
DEFAULT_PLATE_THRESHOLD = 0.25
# YuNet's demo uses 0.9. A missed face costs more than a blurred patch of
# background (the same asymmetry as FACE_MIN_CONFIDENCE for the cloud), so lower.
DEFAULT_FACE_THRESHOLD = 0.6
# Longest edge the face model sees. Faces smaller than this resolution allows
# are below what the cloud detectors find too.
FACE_MAX_EDGE = 1600
PLATE_MAX_EDGE = 1280


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def models_dir() -> str:
    return _env("PINPOINT_MODELS_DIR", DEFAULT_MODELS_DIR)


def plate_model_path() -> str:
    return os.path.join(models_dir(), _env("PLATE_MODEL_FILE", DEFAULT_PLATE_MODEL))


def face_model_path() -> str:
    return os.path.join(models_dir(), _env("FACE_MODEL_FILE", DEFAULT_FACE_MODEL))


def onnx_threads() -> int:
    try:
        return max(1, int(os.environ.get("ONNX_THREADS") or 2))
    except ValueError:
        return 2


def idle_unload_seconds() -> float:
    return max(0.0, _env_float("MODEL_IDLE_UNLOAD_S", 600.0))


class ModelUnavailable(RuntimeError):
    """The model is configured but missing, failed to load, or failed to run."""


# --------------------------------------------------------------------------
# the holder: lazy, shared, idle-unloaded
# --------------------------------------------------------------------------

class _Holder:
    """One loaded model per process, created on first use.

    Thread-safe: loading and unloading happen under a lock, and a caller keeps
    its own reference for the duration of an inference, so an unload that
    races an inference only drops the holder's reference -- the memory goes
    when that inference finishes.
    """

    def __init__(self, name: str, path_fn: Callable[[], str], loader: Callable[[str], Any]):
        self.name = name
        self._path_fn = path_fn
        self._loader = loader
        self._lock = threading.Lock()
        self._handle: Any = None
        self._path = ""
        self.last_used = 0.0
        self.loaded_at = 0.0
        self.load_error = ""
        self._reaper: Optional[threading.Thread] = None

    @property
    def path(self) -> str:
        return self._path_fn()

    def present(self) -> bool:
        return os.path.isfile(self.path)

    @property
    def loaded(self) -> bool:
        return self._handle is not None

    def get(self) -> Any:
        path = self.path
        with self._lock:
            if self._handle is not None and self._path != path:
                self._handle = None            # the configured file changed
            if self._handle is None:
                if not os.path.isfile(path):
                    self.load_error = "model file missing"
                    raise ModelUnavailable(f"{self.name}: model file missing ({path})")
                started = time.monotonic()
                try:
                    self._handle = self._loader(path)
                except Exception as exc:
                    self.load_error = str(exc)[:300]
                    raise ModelUnavailable(f"{self.name}: failed to load: {self.load_error}") from exc
                self._path = path
                self.load_error = ""
                self.loaded_at = time.time()
                logger.info("[Redaction] loaded %s model %s in %.2fs", self.name,
                            os.path.basename(path), time.monotonic() - started)
                self._start_reaper()
            self.last_used = time.monotonic()
            return self._handle

    def unload(self) -> bool:
        with self._lock:
            if self._handle is None:
                return False
            self._handle = None
        gc.collect()
        _release_freed_memory()
        logger.info("[Redaction] unloaded idle %s model", self.name)
        return True

    def unload_if_idle(self, now: Optional[float] = None) -> bool:
        limit = idle_unload_seconds()
        if not limit:
            return False
        now = time.monotonic() if now is None else now
        with self._lock:
            idle = self._handle is not None and now - self.last_used >= limit
        return self.unload() if idle else False

    def _start_reaper(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return

        def reap():
            while True:
                time.sleep(max(5.0, min(60.0, idle_unload_seconds() / 4 or 60.0)))
                if self.unload_if_idle():
                    return
                if self._handle is None:
                    return

        self._reaper = threading.Thread(target=reap, name=f"{self.name}-model-reaper", daemon=True)
        self._reaper.start()

    def status(self) -> Dict[str, Any]:
        path = self.path
        present = os.path.isfile(path)
        return {
            "file": os.path.basename(path),
            "present": present,
            "loaded": self.loaded,
            "error": self.load_error,
            "sha256": _sha256_cached(path) if present else "",
            "size_bytes": os.path.getsize(path) if present else 0,
        }


def _release_freed_memory() -> None:
    """Hand freed heap back to the OS. glibc keeps it otherwise, and the
    process's resident size would not fall when a model is unloaded."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


_sha_cache: Dict[Tuple[str, float, int], str] = {}


def _sha256_cached(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = (path, st.st_mtime, st.st_size)
    if key not in _sha_cache:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _sha_cache.clear()
        _sha_cache[key] = h.hexdigest()
    return _sha_cache[key]


# --------------------------------------------------------------------------
# plates: YOLOv9 end-to-end ONNX (open-image-models)
# --------------------------------------------------------------------------
#
# Pre/post-processing follows open-image-models' yolo_v9 module so its
# published accuracy applies: letterbox to the square input size keeping aspect
# ratio with pad value 114 (preprocess.py), RGB, /255, float32 NCHW; the graph
# includes NMS and emits rows [batch, x1, y1, x2, y2, class, score] in
# letterboxed pixels (postprocess.py), undone as (v - pad) / ratio.

def session_options():
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.enable_cpu_mem_arena = False
    opts.enable_mem_pattern = False
    opts.intra_op_num_threads = onnx_threads()
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.log_severity_level = 3
    return opts


@dataclass
class _PlateModel:
    session: Any
    input_name: str
    output_name: str
    size: int


def _load_plate(path: str) -> _PlateModel:
    import onnxruntime as ort

    session = ort.InferenceSession(path, sess_options=session_options(),
                                   providers=["CPUExecutionProvider"])
    inp = session.get_inputs()[0]
    shape = inp.shape
    if len(shape) != 4 or not isinstance(shape[2], int) or shape[2] != shape[3]:
        raise ValueError(f"expected a fixed square NCHW input, got {shape}")
    return _PlateModel(session, inp.name, session.get_outputs()[0].name, int(shape[2]))


def letterbox(rgb, size: int, pad: int = 114):
    """(canvas, ratio, (dw, dh)), geometry as open-image-models' letterbox."""
    import numpy as np
    from PIL import Image

    h, w = rgb.shape[:2]
    r = min(size / h, size / w)
    new_w, new_h = int(round(w * r)), int(round(h * r))
    dw, dh = (size - new_w) / 2, (size - new_h) / 2
    if (w, h) != (new_w, new_h):
        rgb = np.asarray(Image.fromarray(rgb).resize((new_w, new_h), Image.BILINEAR))
    top, left = int(round(dh - 0.1)), int(round(dw - 0.1))
    canvas = np.full((size, size, 3), pad, dtype=np.uint8)
    canvas[top:top + new_h, left:left + new_w] = rgb
    return canvas, r, (dw, dh)


def decode_end2end(rows, ratio: float, pad: Tuple[float, float], threshold: float,
                   width: int, height: int) -> List[Tuple[float, float, float, float, float]]:
    """End-to-end rows -> (x0, y0, x1, y1, score) as fractions of the image."""
    out = []
    dw, dh = pad
    for row in rows:
        row = [float(v) for v in list(row)]
        if len(row) < 7 or row[6] < threshold:
            continue
        x0, x1 = sorted(((row[1] - dw) / ratio, (row[3] - dw) / ratio))
        y0, y1 = sorted(((row[2] - dh) / ratio, (row[4] - dh) / ratio))
        box = (max(0.0, min(1.0, x0 / width)), max(0.0, min(1.0, y0 / height)),
               max(0.0, min(1.0, x1 / width)), max(0.0, min(1.0, y1 / height)), row[6])
        if box[2] > box[0] and box[3] > box[1]:
            out.append(box)
    return out


def _rgb(raw: bytes, max_edge: int):
    import io

    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        if max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.BILINEAR)
        return np.asarray(image, dtype=np.uint8)


plate_holder = _Holder("plate", plate_model_path, _load_plate)

# One plate inference at a time per process. A report carries up to three
# photos and they are redacted concurrently; three simultaneous runs would
# triple the activation memory (~60 MB each for YOLOv9-s) and oversubscribe the
# API container's two CPUs for no gain in total time.
_plate_slot = threading.BoundedSemaphore(1)


def detect_plates(raw: bytes) -> List[Tuple[float, float, float, float, float]]:
    """Plate boxes as fractions of the (already upright) image. Blocking.

    Raises ModelUnavailable when the model is missing, will not load, or fails
    to run -- never returns [] for "could not look".
    """
    import numpy as np

    model: _PlateModel = plate_holder.get()
    try:
        rgb = _rgb(raw, PLATE_MAX_EDGE)
        h, w = rgb.shape[:2]
        canvas, ratio, pad = letterbox(rgb, model.size)
        tensor = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        with _plate_slot:
            out = np.asarray(model.session.run([model.output_name], {model.input_name: tensor})[0])
    except ModelUnavailable:
        raise
    except Exception as exc:
        raise ModelUnavailable(f"plate: inference failed: {exc}") from exc
    rows = out.reshape(-1, out.shape[-1]) if out.size else []
    return decode_end2end(rows, ratio, pad, _env_float("PLATE_THRESHOLD", DEFAULT_PLATE_THRESHOLD), w, h)


# --------------------------------------------------------------------------
# faces: YuNet via OpenCV's FaceDetectorYN (opencv_zoo, MIT)
# --------------------------------------------------------------------------
#
# cv2.FaceDetectorYN is OpenCV's own YuNet runner (prior generation, decoding,
# NMS), already in this image's opencv-python-headless. Its detector object is
# not thread-safe, so inference is serialised on a lock.

@dataclass
class _FaceModel:
    detector: Any
    lock: threading.Lock


def _load_face(path: str) -> _FaceModel:
    import cv2

    detector = cv2.FaceDetectorYN.create(
        path, "", (320, 320),
        _env_float("FACE_THRESHOLD", DEFAULT_FACE_THRESHOLD), 0.3, 5000,
    )
    return _FaceModel(detector, threading.Lock())


face_holder = _Holder("face", face_model_path, _load_face)


def detect_faces(raw: bytes) -> List[Tuple[float, float, float, float, float]]:
    """Face boxes as fractions of the (already upright) image. Blocking.

    Raises ModelUnavailable like detect_plates.
    """
    model: _FaceModel = face_holder.get()
    try:
        rgb = _rgb(raw, FACE_MAX_EDGE)
        bgr = rgb[:, :, ::-1].copy()
        h, w = bgr.shape[:2]
        with model.lock:
            model.detector.setInputSize((w, h))
            _, faces = model.detector.detect(bgr)
    except ModelUnavailable:
        raise
    except Exception as exc:
        raise ModelUnavailable(f"face: inference failed: {exc}") from exc
    out = []
    for f in (faces if faces is not None else []):
        x, y, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[-1])
        box = (max(0.0, x / w), max(0.0, y / h), min(1.0, (x + fw) / w), min(1.0, (y + fh) / h), score)
        if box[2] > box[0] and box[3] > box[1]:
            out.append(box)
    return out


def status() -> Dict[str, Any]:
    return {"plate": plate_holder.status(), "face": face_holder.status(),
            "models_dir": models_dir(), "idle_unload_s": idle_unload_seconds(),
            "threads": onnx_threads()}
