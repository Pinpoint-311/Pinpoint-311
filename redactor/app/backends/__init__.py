"""Detector backends. Add one by subclassing backends.base.Detector."""

from __future__ import annotations

from app.backends.base import Detector
from app.config import Settings

BACKENDS = ("onnx", "egoblur")


def create(settings: Settings) -> Detector:
    if settings.backend == "egoblur":
        from app.backends.egoblur import EgoBlurDetector
        return EgoBlurDetector(settings)
    if settings.backend == "onnx":
        from app.backends.onnx_yolo import OnnxYoloDetector
        return OnnxYoloDetector(settings)
    raise ValueError(f"unknown REDACTOR_BACKEND {settings.backend!r}; expected one of {BACKENDS}")
