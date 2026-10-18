import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def jpeg(width, height, color=(90, 120, 90), rect=None, rect_color=(255, 0, 0), fmt="PNG", exif=None):
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (width, height), color)
    if rect:
        ImageDraw.Draw(im).rectangle(rect, fill=rect_color)
    buf = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    im.save(buf, fmt, **kwargs)
    return buf.getvalue()


@pytest.fixture
def make_image():
    return jpeg
