"""The detector interface every backend implements.

A backend owns its model files and turns a `Prepared` image into pixel boxes.
Everything else -- HTTP, limits, concurrency, orientation, fractions -- is the
service's job, so adding a backend is one file with three methods.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from app.config import Settings
from app.imaging import Prepared


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ModelFile:
    """One model file a backend wants, and what happened when it tried."""

    kind: str                 # plate | face
    file: str
    required: bool = True
    present: bool = False
    loaded: bool = False
    error: str = ""
    sha256: str = ""
    size_bytes: int = 0
    load_seconds: float = 0.0
    handle: Any = field(default=None, repr=False)

    def public(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "file": self.file, "required": self.required,
            "present": self.present, "loaded": self.loaded, "error": self.error,
            "sha256": self.sha256, "size_bytes": self.size_bytes,
            "load_seconds": round(self.load_seconds, 2),
        }


class Detector:
    """Base class. Subclasses set `name`, fill `self.models`, implement `_open`
    and `infer`."""

    name = "base"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.models: Dict[str, ModelFile] = {}

    # -- lifecycle ----------------------------------------------------------

    def load(self) -> None:
        """Open every model file that is present. Never raises: a missing or
        corrupt file is reported by status(), it does not stop the service."""
        for model in self.models.values():
            path = os.path.join(self.settings.models_dir, model.file)
            model.present = os.path.isfile(path)
            if not model.present:
                continue
            model.size_bytes = os.path.getsize(path)
            if self.settings.hash_models:
                try:
                    model.sha256 = sha256_file(path)
                except OSError as exc:
                    model.error = f"cannot read: {exc}"
                    continue
            started = time.monotonic()
            try:
                model.handle = self._open(path, model.kind)
                model.loaded = True
            except Exception as exc:
                model.error = str(exc)[:500]
            model.load_seconds = time.monotonic() - started

    def close(self) -> None:  # pragma: no cover - default no-op
        pass

    def _open(self, path: str, kind: str) -> Any:
        raise NotImplementedError

    # -- status -------------------------------------------------------------

    def kinds(self) -> List[str]:
        return [k for k, m in self.models.items() if m.loaded]

    def status(self) -> str:
        """ok | models_missing | model_error. "ok" needs the plate model."""
        plate = self.models.get("plate")
        if plate and plate.loaded:
            return "ok"
        if any(m.present and not m.loaded for m in self.models.values()):
            return "model_error"
        return "models_missing"

    def describe(self) -> Dict[str, Any]:
        """Backend-specific settings worth showing on /health."""
        return {}

    # -- inference ----------------------------------------------------------

    def infer(self, image: Prepared, kind: str) -> Tuple[List[List[float]], List[float]]:
        """(XYXY pixel boxes in image.width x image.height, scores), already
        thresholded and de-duplicated the way the model's authors do it."""
        raise NotImplementedError
