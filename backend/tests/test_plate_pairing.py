"""Plates printed in two groups are blurred whole.

Live check on 2026-10-18 against Azure AI Vision `read`: "A12 BCD" (New Jersey
format) came back as two words, neither of which passed the per-word plate test,
so the plate was not blurred at all; "ABC 1234" had only "1234" blurred.
"""

import pytest

ir = pytest.importorskip("app.services.image_redaction")

W, H = 1280, 960


def _poly(x0, y0, x1, y1):
    return [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]


def _azure(*lines):
    return {"readResult": {"blocks": [{"lines": [
        {"text": " ".join(w[0] for w in words),
         "words": [{"text": t, "boundingPolygon": _poly(*xy), "confidence": c} for t, xy, c in words]}
        for words in lines
    ]}]}}


NJ_SPLIT = _azure(
    [("A12", (522, 652, 620, 700), 0.99), ("BCD", (640, 652, 750, 700), 0.99)],
    [("NEW", (562, 706, 600, 722), 0.97), ("JERSEY", (605, 706, 668, 722), 0.97)],
)


def test_a_split_new_jersey_plate_is_blurred_whole():
    boxes = ir.azure_text_plates(NJ_SPLIT, W, H)
    assert boxes, "the split plate must be found"
    widest = max(boxes, key=lambda b: b.width)
    # The blurred region spans both halves of the plate.
    assert widest.left * W <= 522 + 1 and widest.right * W >= 750 - 1


def test_both_halves_of_abc_1234_are_covered():
    payload = _azure([("ABC", (545, 655, 640, 705), 1.0), ("1234", (660, 655, 760, 705), 0.98)])
    widest = max(ir.azure_text_plates(payload, W, H), key=lambda b: b.width)
    assert widest.left * W <= 546 and widest.right * W >= 759


def test_a_single_word_plate_still_works():
    payload = _azure([("A12-BCD", (522, 652, 750, 700), 0.99)])
    assert len(ir.azure_text_plates(payload, W, H)) == 1


def test_the_state_name_and_far_apart_words_are_not_paired():
    # "NEW JERSEY" has no digit; a house number far from a word is not a plate.
    payload = _azure(
        [("NEW", (562, 706, 600, 722), 0.97), ("JERSEY", (605, 706, 668, 722), 0.97)],
        [("MAIN", (100, 200, 220, 240), 0.99), ("12", (900, 200, 940, 240), 0.99)],
    )
    assert ir.azure_text_plates(payload, W, H) == []


def test_rekognition_pairs_words_from_the_same_line():
    def word(text, left, parent):
        return {"Type": "WORD", "DetectedText": text, "Confidence": 99, "ParentId": parent,
                "Geometry": {"BoundingBox": {"Left": left, "Top": 0.68, "Width": 0.075, "Height": 0.05}}}
    payload = {"TextDetections": [word("BCD", 0.50, 1), word("A12", 0.41, 1)]}
    boxes = ir.rekognition_text_plates(payload)
    assert boxes and max(b.width for b in boxes) > 0.15


def test_google_pairs_adjacent_words():
    def ann(text, x0, x1):
        return {"description": text, "boundingPoly": {"vertices": [
            {"x": x0, "y": 652}, {"x": x1, "y": 652}, {"x": x1, "y": 700}, {"x": x0, "y": 700}]}}
    payload = {"responses": [{"textAnnotations": [{"description": "A12 BCD"}, ann("A12", 522, 620), ann("BCD", 640, 750)]}]}
    boxes = ir.google_text_plates(payload, W, H)
    assert boxes and max(b.right for b in boxes) * W >= 749
