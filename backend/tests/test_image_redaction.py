"""Tests for face / licence-plate redaction.

The network calls and the Pillow blur are not the interesting part. What is
worth pinning is the layer between them: four providers that describe a
rectangle four different ways, and a plate heuristic that decides whether to
destroy part of a public record.

Two properties carry most of the weight:

  * a detection must never come back outside the image, because the padding
    step deliberately pushes boxes past the edge and PIL will not crop there;
  * `plate_like` must not fire on street signage, because a blurred STOP sign
    or house number can make an otherwise actionable report useless.
"""

import pytest

from app.services.image_redaction import (
    Box,
    azure_faces,
    azure_text_plates,
    google_faces,
    google_text_plates,
    merge_boxes,
    plate_like,
    rekognition_faces,
    rekognition_text_plates,
)

WIDE = Box(0.4, 0.6, 0.5, 0.63, "plate")      # ~3.3:1, lower half — plate-shaped
TALL = Box(0.4, 0.1, 0.44, 0.3, "plate")      # taller than wide, upper frame


# ---- geometry ---------------------------------------------------------------

def test_a_box_is_clamped_into_the_image():
    box = Box(-0.4, -0.2, 1.9, 1.3).clamped()
    assert (box.left, box.top, box.right, box.bottom) == (0.0, 0.0, 1.0, 1.0)


def test_a_reversed_box_is_straightened_rather_than_producing_negative_area():
    """Right-to-left coordinates come back from at least one provider when a
    face touches the frame edge. Negative width silently blurs nothing."""
    box = Box(0.8, 0.9, 0.2, 0.1).clamped()
    assert box.right > box.left and box.bottom > box.top
    assert box.area > 0


def test_padding_grows_the_box_but_cannot_escape_the_image():
    """Padding exists because a face box is drawn tight and leaves hairline and
    jaw legible. It must still be croppable afterwards."""
    padded = Box(0.02, 0.02, 0.1, 0.1).padded(2.0)
    assert padded.area > Box(0.02, 0.02, 0.1, 0.1).area
    assert padded.left >= 0 and padded.top >= 0
    assert padded.right <= 1 and padded.bottom <= 1


def test_pixel_conversion_never_produces_a_zero_width_crop():
    """A sliver box rounds both edges to the same pixel, and PIL raises on a
    zero-area crop."""
    left, top, right, bottom = Box(0.5, 0.5, 0.5001, 0.5001).to_pixels(100, 100)
    assert right > left and bottom > top


def test_overlapping_boxes_merge_into_their_union():
    merged = merge_boxes([Box(0.1, 0.1, 0.5, 0.5), Box(0.2, 0.2, 0.6, 0.6)])
    assert len(merged) == 1
    assert merged[0].left == pytest.approx(0.1)
    assert merged[0].right == pytest.approx(0.6)


def test_a_contained_box_merges_even_though_its_iou_is_low():
    """The reason _overlap divides by the smaller box rather than the union: a
    small face box inside a large one is the same face, and IoU would keep
    both, blurring the region twice."""
    merged = merge_boxes([Box(0.0, 0.0, 1.0, 1.0), Box(0.45, 0.45, 0.5, 0.5)])
    assert len(merged) == 1


def test_separate_faces_stay_separate():
    """Two people in one photo must count as two, or the number shown to staff
    is wrong."""
    merged = merge_boxes([Box(0.0, 0.0, 0.2, 0.2), Box(0.7, 0.7, 0.9, 0.9)])
    assert len(merged) == 2


def test_a_face_and_a_plate_in_the_same_place_are_not_merged():
    """They carry different padding and are counted separately; collapsing them
    would report one as the other."""
    merged = merge_boxes([Box(0.1, 0.1, 0.5, 0.5, "face"), Box(0.1, 0.1, 0.5, 0.5, "plate")])
    assert len(merged) == 2


# ---- face parsers -----------------------------------------------------------

def test_vision_faces_are_normalised_out_of_pixels():
    payload = {"responses": [{"faceAnnotations": [{
        "detectionConfidence": 0.98,
        "boundingPoly": {"vertices": [{"x": 100, "y": 50}, {"x": 300, "y": 50},
                                      {"x": 300, "y": 250}, {"x": 100, "y": 250}]},
    }]}]}
    box = google_faces(payload, 400, 400)[0]
    assert box.left == pytest.approx(0.25)
    assert box.top == pytest.approx(0.125)
    assert box.right == pytest.approx(0.75)


def test_vision_treats_a_missing_vertex_coordinate_as_zero():
    """Vision omits `x`/`y` entirely when the value is 0. Reading that as a
    missing box would drop every face touching the left or top edge."""
    payload = {"responses": [{"faceAnnotations": [{
        "detectionConfidence": 0.9,
        "boundingPoly": {"vertices": [{"y": 10}, {"x": 80, "y": 10}, {"x": 80, "y": 90}, {"y": 90}]},
    }]}]}
    box = google_faces(payload, 100, 100)[0]
    assert box.left == pytest.approx(0.0)
    assert box.right == pytest.approx(0.8)


def test_a_low_confidence_face_is_still_blurred():
    """The threshold is deliberately low. A false blur costs a slightly worse
    photo; a missed face publishes someone's biometrics on a town website."""
    payload = {"responses": [{"faceAnnotations": [{
        "detectionConfidence": 0.4,
        "boundingPoly": {"vertices": [{"x": 0, "y": 0}, {"x": 50, "y": 0},
                                      {"x": 50, "y": 50}, {"y": 50}]},
    }]}]}
    assert len(google_faces(payload, 100, 100)) == 1


def test_rekognition_boxes_are_already_fractional():
    payload = {"FaceDetails": [{"Confidence": 99.4, "BoundingBox": {
        "Left": 0.1, "Top": 0.2, "Width": 0.3, "Height": 0.4}}]}
    box = rekognition_faces(payload)[0]
    assert box.right == pytest.approx(0.4)
    assert box.bottom == pytest.approx(0.6)


def test_azure_face_rectangles_are_normalised():
    box = azure_faces([{"faceRectangle": {"left": 50, "top": 25, "width": 100, "height": 100}}],
                      200, 200)[0]
    assert box.left == pytest.approx(0.25)
    assert box.bottom == pytest.approx(0.625)


@pytest.mark.parametrize("parse,args", [
    (google_faces, ({}, 100, 100)),
    (google_faces, ({"responses": []}, 100, 100)),
    (google_faces, ({"responses": [{}]}, 100, 100)),
    (rekognition_faces, ({},)),
    (rekognition_faces, ({"FaceDetails": None},)),
    (azure_faces, ([], 100, 100)),
    (azure_faces, (None, 100, 100)),
])
def test_an_empty_or_malformed_response_yields_no_boxes_rather_than_raising(parse, args):
    """A provider hiccup must not take down intake."""
    assert parse(*args) == []


def test_zero_dimensions_do_not_divide_by_zero():
    assert azure_faces([{"faceRectangle": {"left": 1, "top": 1, "width": 1, "height": 1}}], 0, 0) == []


# ---- the plate heuristic ----------------------------------------------------

@pytest.mark.parametrize("text", [
    "STOP", "YIELD", "ONE WAY", "SCHOOL", "DETOUR", "NO PARKING", "EXIT",
])
def test_common_signage_is_not_a_plate(text):
    """The failure that makes this feature unusable: smearing every sign in the
    photo, so staff cannot tell where the report is."""
    assert plate_like(text, WIDE) == 0.0


@pytest.mark.parametrize("text", ["MAIN", "ELM STREET", "HELLO", "PARK"])
def test_a_word_with_no_digits_is_not_a_plate(text):
    """The single strongest rule -- signs are words, plates are not."""
    assert plate_like(text, WIDE) == 0.0


@pytest.mark.parametrize("text", ["AB", "123", "SUPERLONGPLATE", "A1B2C3D4E5"])
def test_wrong_length_strings_are_rejected(text):
    """4-8 characters after stripping punctuation. US plates run 5-7; the window
    is one wider at each end for OCR dropping or splitting a character."""
    assert plate_like(text, WIDE) == 0.0


def test_an_eight_character_alphanumeric_is_accepted():
    """"A1B 2C3D9" strips to eight characters and is plate-plausible -- I first
    wrote this as a rejection case and the heuristic was right, not the test."""
    from app.services.image_redaction import PLATE_MIN_CONFIDENCE
    assert plate_like("A1B 2C3D9", WIDE) >= PLATE_MIN_CONFIDENCE


@pytest.mark.parametrize("text", ["ABC1234", "A12BCD", "XYZ 890", "M45KLT"])
def test_a_plate_shaped_string_in_a_plate_shaped_box_scores(text):
    from app.services.image_redaction import PLATE_MIN_CONFIDENCE
    assert plate_like(text, WIDE) >= PLATE_MIN_CONFIDENCE


def test_geometry_can_veto_a_plausible_string():
    """Same characters, wrong shape and wrong place in the frame. Overhead
    signage and shopfront numbering land here."""
    assert plate_like("ABC1234", TALL) < plate_like("ABC1234", WIDE)


def test_an_all_numeric_string_scores_below_an_alphanumeric_one():
    """A bare number is as likely a house number, and blurring the house number
    out of a pothole report destroys the thing that made it actionable."""
    assert plate_like("12345", WIDE) < plate_like("ABC1234", WIDE)


def test_a_text_region_covering_the_frame_is_not_a_plate():
    """A banner or shopfront. A plate is small in a streetscape photo."""
    banner = Box(0.05, 0.4, 0.95, 0.8, "plate")
    assert plate_like("ABC1234", banner) < plate_like("ABC1234", WIDE)


def test_a_multi_word_string_is_a_sign_not_a_plate():
    assert plate_like("ROUTE 22 EAST", WIDE) == 0.0


def test_the_score_is_always_a_probability():
    for text in ["", "ABC1234", "STOP", "!!!!", "1", "A" * 40]:
        for box in (WIDE, TALL, Box(0, 0, 1, 1, "plate")):
            assert 0.0 <= plate_like(text, box) <= 1.0


# ---- plate parsers ----------------------------------------------------------

def _vision_text(description, vertices):
    return {"responses": [{"textAnnotations": [
        # [0] is the whole-image aggregate that Vision always prepends.
        {"description": "ABC1234 STOP", "boundingPoly": {"vertices": [
            {"x": 0, "y": 0}, {"x": 1000, "y": 0}, {"x": 1000, "y": 1000}, {"x": 0, "y": 1000}]}},
        {"description": description, "boundingPoly": {"vertices": vertices}},
    ]}]}


def test_visions_whole_image_aggregate_is_skipped():
    """textAnnotations[0] spans the entire photo. Treating it as a detection
    blurs the whole image the moment any plate-shaped string appears."""
    payload = _vision_text("ABC1234", [{"x": 400, "y": 700}, {"x": 600, "y": 700},
                                       {"x": 600, "y": 760}, {"x": 400, "y": 760}])
    boxes = google_text_plates(payload, 1000, 1000)
    assert len(boxes) == 1
    assert boxes[0].area < 0.1


def test_vision_signage_produces_no_plate_box():
    payload = _vision_text("STOP", [{"x": 400, "y": 700}, {"x": 600, "y": 700},
                                    {"x": 600, "y": 760}, {"x": 400, "y": 760}])
    assert google_text_plates(payload, 1000, 1000) == []


def test_rekognition_uses_words_not_lines():
    """A LINE glues the plate to the state name and the dealer frame, breaking
    both the character-count and aspect-ratio tests."""
    geometry = {"BoundingBox": {"Left": 0.4, "Top": 0.7, "Width": 0.2, "Height": 0.06}}
    payload = {"TextDetections": [
        {"Type": "LINE", "DetectedText": "NEW JERSEY ABC1234", "Confidence": 99, "Geometry": geometry},
        {"Type": "WORD", "DetectedText": "ABC1234", "Confidence": 99, "Geometry": geometry},
    ]}
    assert len(rekognition_text_plates(payload)) == 1


def test_low_ocr_confidence_gates_the_geometry_score():
    """Otherwise a half-read smudge in a plate-shaped box passes on shape
    alone."""
    geometry = {"BoundingBox": {"Left": 0.4, "Top": 0.7, "Width": 0.2, "Height": 0.06}}
    payload = {"TextDetections": [
        {"Type": "WORD", "DetectedText": "ABC1234", "Confidence": 20, "Geometry": geometry}]}
    assert rekognition_text_plates(payload) == []


def test_azure_read_words_are_parsed():
    payload = {"readResult": {"blocks": [{"lines": [{"words": [
        {"text": "ABC1234", "confidence": 0.97, "boundingPolygon": [
            {"x": 400, "y": 700}, {"x": 600, "y": 700},
            {"x": 600, "y": 760}, {"x": 400, "y": 760}]},
    ]}]}]}}
    assert len(azure_text_plates(payload, 1000, 1000)) == 1


@pytest.mark.parametrize("parse,args", [
    (google_text_plates, ({}, 100, 100)),
    (rekognition_text_plates, ({},)),
    (azure_text_plates, ({}, 100, 100)),
    (azure_text_plates, ({"readResult": {"blocks": None}}, 100, 100)),
])
def test_plate_parsers_tolerate_junk(parse, args):
    assert parse(*args) == []
