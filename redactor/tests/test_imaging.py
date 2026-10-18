import pytest

from app.imaging import ImageRejected, prepare, to_fractions


def test_downscales_to_max_edge_and_keeps_original_size(make_image):
    p = prepare(make_image(2000, 1500), max_edge=1280, max_pixels=50_000_000)
    assert (p.width, p.height) == (1280, 960)
    assert (p.original_width, p.original_height) == (2000, 1500)
    assert p.rgb.shape == (960, 1280, 3) and str(p.rgb.dtype) == "uint8"


def test_small_image_is_not_upscaled(make_image):
    p = prepare(make_image(640, 480), 1280, 50_000_000)
    assert (p.width, p.height) == (640, 480)


def test_rgb_order_is_preserved(make_image):
    p = prepare(make_image(10, 10, color=(255, 0, 0)), 1280, 50_000_000)
    assert tuple(p.rgb[5, 5]) == (255, 0, 0)


def test_exif_orientation_is_baked_in(make_image):
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    p = prepare(make_image(400, 200, fmt="JPEG", exif=exif.tobytes()), 1280, 50_000_000)
    assert (p.width, p.height) == (200, 400)


def test_unreadable_and_too_large_are_refused(make_image):
    with pytest.raises(ImageRejected, match="unreadable-image"):
        prepare(b"not an image", 1280, 50_000_000)
    with pytest.raises(ImageRejected, match="image-too-large"):
        prepare(make_image(300, 300), 1280, max_pixels=300 * 300 - 1)


def test_to_fractions_clamps_orders_and_drops_empty():
    out = to_fractions([[-10, 50, 110, 150], [60, 80, 20, 40], [5, 5, 5, 9]],
                       [0.9, 0.8, 0.7], 100, 200, "plate")
    assert out[0] == {"x0": 0.0, "y0": 0.25, "x1": 1.0, "y1": 0.75, "score": 0.9, "kind": "plate"}
    assert (out[1]["x0"], out[1]["y0"], out[1]["x1"], out[1]["y1"]) == (0.2, 0.2, 0.6, 0.4)
    assert len(out) == 2
