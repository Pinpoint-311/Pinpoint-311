"""A photo past the three-photo cap was never looked at, so it must not be publishable.

`redact_media` and `screen_and_redact` only ever examine the first MAX_IMAGES
photos of a submission -- that is the cost ceiling, and it is fine. What was
not fine is what happened to the rest. Both functions appended every photo past
the cap straight into `BatchResult.media` with a `kept` index, under a comment
saying this was so the function "cannot silently drop a photo".

That put photos nothing had examined into the same list as photos that had been
decoded, SafeSearch'd, blurred and EXIF-stripped, and `create_request` cannot
tell the two apart: it maps `kept` back onto the resident's submitted slots and
stores the first three of the result. So a report whose first photo is withheld
-- which the submitter chooses, by attaching one byte sequence this build
cannot decode -- promotes the fourth photo into a published slot. It reaches
`GET /api/open311/v2/public/requests/{id}` with:

  * no SafeSearch verdict (the moderation half only ever saw the first three
    on the combined Google path, and the `should_block` refusal above it
    therefore never considered this photo at all),
  * no face or licence-plate blur,
  * its EXIF GPS block intact.

`POST /api/open311/v2/requests.json` is unauthenticated and `media_urls` has no
length bound, so the whole sequence is one anonymous request.

The fix is to withhold the overflow rather than carry it: `media` is the
publishable list and nothing unexamined belongs in it. The photo is still not
dropped -- it lands in `withheld`, which the caller parks in
`media_pending_review` for staff, exactly like a photo the detector could not
clear.
"""

import asyncio

import pytest

pytest.importorskip("cryptography")

from app.services import image_redaction as ir  # noqa: E402


REDACTED = "data:image/jpeg;base64,REDACTED-"
UNREADABLE = "data:image/avif;base64,CANNOTDECODE"


def _fake_settings(provider):
    async def _settings():
        return (provider, True, True)

    return _settings


def _fake_redact_image(media, provider, faces, plates):
    """Blur everything except the one photo this build cannot decode."""

    async def _done():
        if media == UNREADABLE:
            return ir.RedactionResult(media, skipped_reason="unreadable-image")
        return ir.RedactionResult(REDACTED + media, faces=1, changed=True)

    return _done()


def _patched(provider, fn, media):
    original_settings, original_redact = ir.settings, ir.redact_image
    ir.settings, ir.redact_image = _fake_settings(provider), _fake_redact_image
    try:
        return asyncio.run(fn(media))
    finally:
        ir.settings, ir.redact_image = original_settings, original_redact


def _submission():
    """Four photos. The first is the one the submitter knows will be withheld,
    which is what frees a slot for the fourth."""
    return [UNREADABLE, "photo-b", "photo-c", "evil-fourth-photo"]


# ------------------------------------------------------------- redact_media


def test_redact_media_does_not_publish_a_photo_it_never_examined():
    out = _patched("local", ir.redact_media, _submission())

    assert "evil-fourth-photo" not in out.media, (
        "the fourth photo was never decoded, never blurred and never "
        "EXIF-stripped, yet it is in the publishable list"
    )
    assert all(m.startswith(REDACTED) for m in out.media), (
        f"every publishable photo must have come back from the redactor: {out.media}"
    )


def test_redact_media_holds_the_overflow_for_staff_rather_than_dropping_it():
    out = _patched("local", ir.redact_media, _submission())

    held = {p["media"] for p in out.withheld}
    assert "evil-fourth-photo" in held
    assert UNREADABLE in held


def test_kept_indices_still_line_up_with_the_media_they_describe():
    """`create_request` reads `media[i]` for `kept[i]`, so an index that points
    past the list is the bug that swaps one resident's photo for another's."""
    out = _patched("local", ir.redact_media, _submission())

    assert len(out.kept) == len(out.media)
    submitted = _submission()
    for position, source_index in enumerate(out.kept):
        assert out.media[position] == REDACTED + submitted[source_index]


# --------------------------------------------------------- screen_and_redact


def test_the_combined_google_path_does_not_publish_the_overflow_either():
    """The Google path folds SafeSearch and redaction into one call, so a photo
    it never examined has no moderation verdict at all -- `should_block` above
    it was decided without ever seeing this photo."""

    async def _one(media, faces, plates):
        from app.services.content_moderation import ModerationResult

        if media == UNREADABLE:
            return ModerationResult(), ir.RedactionResult(media, skipped_reason="unreadable-image")
        return ModerationResult(), ir.RedactionResult(REDACTED + media, faces=1, changed=True)

    original_settings = ir.settings
    original_one = ir._google_screen_and_redact_one
    ir.settings = _fake_settings("google")
    ir._google_screen_and_redact_one = _one
    try:
        _verdict, out = asyncio.run(ir.screen_and_redact(_submission()))
    finally:
        ir.settings = original_settings
        ir._google_screen_and_redact_one = original_one

    assert "evil-fourth-photo" not in out.media
    assert "evil-fourth-photo" in {p["media"] for p in out.withheld}
    assert len(out.kept) == len(out.media)


def test_with_redaction_switched_off_the_overflow_is_not_published_unstripped():
    """The off switch is about blurring, not about publishing a GPS block: the
    first three still go through `exif_only`. A photo past the cap goes through
    nothing at all, so it is held rather than published."""
    stripped = []

    original_settings, original_exif = ir.settings, ir.exif_only
    ir.settings = _fake_settings(None)
    ir.exif_only = lambda m: (stripped.append(m), "stripped-" + m)[1]
    try:
        out = asyncio.run(ir.redact_media(_submission()))
    finally:
        ir.settings, ir.exif_only = original_settings, original_exif

    assert "evil-fourth-photo" not in out.media
    assert all(m.startswith("stripped-") for m in out.media), out.media
    assert len(out.kept) == len(out.media), (
        "an empty `kept` with media present makes create_request drop every "
        "inline photo on a town that has redaction switched off"
    )
