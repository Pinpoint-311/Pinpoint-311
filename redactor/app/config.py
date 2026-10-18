"""Settings, all from the environment. Nothing here reaches the network."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    # Which detector backend runs: "onnx" (a YOLO-style end-to-end ONNX plate
    # detector) or "egoblur" (Meta's EgoBlur Gen2 TorchScript models).
    backend: str = "onnx"
    models_dir: str = "/models"
    # egoblur
    lp_file: str = "ego_blur_lp_gen2.jit"
    face_file: str = "ego_blur_face_gen2.jit"
    egoblur_lp_threshold: float = 0.74475
    egoblur_face_threshold: float = 0.67416
    egoblur_nms_iou: float = 0.5
    device: str = "cpu"     # cpu | cuda:0 -- EgoBlur needs a GPU for practical speed
    # onnx
    onnx_file: str = "plate_detector.onnx"
    onnx_threshold: float = 0.25
    # common
    max_edge: int = 1280
    threads: int = 2
    timeout_s: float = 30.0
    max_bytes: int = 15 * 1024 * 1024
    max_pixels: int = 50_000_000
    queue_max: int = 8
    hash_models: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        d = cls()
        return cls(
            backend=(os.environ.get("REDACTOR_BACKEND") or d.backend).strip().lower(),
            models_dir=os.environ.get("REDACTOR_MODELS_DIR") or d.models_dir,
            lp_file=os.environ.get("REDACTOR_LP_MODEL") or d.lp_file,
            face_file=os.environ.get("REDACTOR_FACE_MODEL") or d.face_file,
            egoblur_lp_threshold=_float("REDACTOR_LP_THRESHOLD", d.egoblur_lp_threshold),
            egoblur_face_threshold=_float("REDACTOR_FACE_THRESHOLD", d.egoblur_face_threshold),
            egoblur_nms_iou=_float("REDACTOR_NMS_IOU", d.egoblur_nms_iou),
            device=(os.environ.get("REDACTOR_DEVICE") or d.device).strip(),
            onnx_file=os.environ.get("REDACTOR_ONNX_MODEL") or d.onnx_file,
            onnx_threshold=_float("REDACTOR_ONNX_THRESHOLD", d.onnx_threshold),
            max_edge=max(64, _int("REDACTOR_MAX_EDGE", d.max_edge)),
            threads=max(1, _int("REDACTOR_THREADS", d.threads)),
            timeout_s=max(1.0, _float("REDACTOR_TIMEOUT_S", d.timeout_s)),
            max_bytes=max(1024, _int("REDACTOR_MAX_BYTES", d.max_bytes)),
            max_pixels=max(1, _int("REDACTOR_MAX_PIXELS", d.max_pixels)),
            queue_max=max(1, _int("REDACTOR_QUEUE_MAX", d.queue_max)),
            hash_models=(os.environ.get("REDACTOR_HASH_MODELS", "1").lower()
                         not in ("0", "false", "no")),
        )
