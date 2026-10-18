"""Decoding and geometry shared by every backend."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


class ImageRejected(ValueError):
    """The bytes are not an image we are willing to decode. str() is the reason."""


@dataclass
class Prepared:
    """The photo as a backend receives it.

    `rgb` is H x W x 3 uint8 in RGB order, already oriented and downscaled;
    `width`/`height` are its size, which is the frame every backend reports
    boxes in before they become fractions.
    """

    rgb: Any
    width: int
    height: int
    original_width: int
    original_height: int


def prepare(raw: bytes, max_edge: int, max_pixels: int) -> Prepared:
    """Decode, bake EXIF orientation, drop metadata, downscale to `max_edge`.

    EXIF never goes anywhere: only decoded pixels leave this function.
    Orientation is applied first so a portrait phone photo is detected in the
    frame the caller blurs (the backend bakes orientation in before sending, so
    for its requests this is a no-op; for anyone else it keeps boxes honest).

    The pixel count is checked from the header before anything is decoded --
    the same 50 MP guard the backend uses -- so a decompression bomb costs a
    header read.
    """
    import numpy as np
    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(raw))
        width, height = image.size
    except Exception as exc:
        raise ImageRejected("unreadable-image") from exc
    if width <= 0 or height <= 0:
        raise ImageRejected("unreadable-image")
    if width * height > max_pixels:
        raise ImageRejected("image-too-large")
    try:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
    except Exception as exc:
        raise ImageRejected("unreadable-image") from exc
    ow, oh = image.size
    if max(ow, oh) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.BILINEAR)
    w, h = image.size
    return Prepared(np.asarray(image, dtype=np.uint8), w, h, ow, oh)


def to_fractions(boxes: Iterable, scores: Iterable, width: int, height: int,
                 kind: str) -> List[Dict[str, Any]]:
    """XYXY pixel boxes in a `width` x `height` frame -> clamped fractions."""
    out: List[Dict[str, Any]] = []
    if width <= 0 or height <= 0:
        return out
    for box, score in zip(list(boxes), list(scores)):
        x0, y0, x1, y1 = (float(v) for v in list(box)[:4])
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        fx0, fx1 = (min(1.0, max(0.0, v / width)) for v in (x0, x1))
        fy0, fy1 = (min(1.0, max(0.0, v / height)) for v in (y0, y1))
        if fx1 <= fx0 or fy1 <= fy0:
            continue
        out.append({
            "x0": round(fx0, 6), "y0": round(fy0, 6),
            "x1": round(fx1, 6), "y1": round(fy1, 6),
            "score": round(float(score), 5), "kind": kind,
        })
    return out
