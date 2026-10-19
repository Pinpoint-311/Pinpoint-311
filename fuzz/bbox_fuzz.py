"""Fuzz target: the map viewport parser (parse_bbox in backend/app/services/gis_layers.py).

The bbox query parameter comes straight from the browser. parse_bbox must
either return a finite, correctly ordered west,south,east,north box or raise
its documented LayerUploadError (which the API turns into a 400); any other
exception would be a 500.
"""
import math

import _harness
from app.services.gis_layers import LayerUploadError, parse_bbox


def fuzz(buf: bytes) -> None:
    s = _harness.text(buf)
    for raw in (s, s.strip(), s.replace("\n", ",")):
        try:
            box = parse_bbox(raw)
        except LayerUploadError:
            continue
        w, south, e, n = box
        assert all(isinstance(v, float) and math.isfinite(v) for v in box), box
        assert -180 <= w < e <= 180 and -90 <= south < n <= 90, box


if __name__ == "__main__":
    _harness.run(fuzz, "bbox")
