"""A fresh install must blur photos, and must say what it is doing.

Before this, a deployment with no cloud credentials did neither.
`resolve_provider()` fell through Google, then the moderation provider, then the
AI provider, and returned None -- because `local` was deliberately excluded from
the fall-through on the reasoning that OpenCV quality is low enough to deserve a
decision rather than a default.

That reasoning compares local against a cloud detector. The real alternative,
on a deployment with no cloud account, is no detection at all. Every resident
photo was stored unmodified: faces of neighbours and passers-by, licence plates
of parked cars, in a public record.

And the page said otherwise. The catalog default was "google", so the Photo
Redaction card displayed Google Cloud Vision as the provider while the runtime
had redaction switched off entirely. The behaviour and the interface disagreed,
and the interface was the reassuring one.
"""

import asyncio

import pytest

pytest.importorskip("cryptography")

from app.services import image_redaction as ir


def _resolve(**secrets):
    """resolve_provider() with a given set of configured secrets."""
    async def _fake(key):
        return secrets.get(key)

    from app.services import secret_manager
    original = secret_manager.get_secret
    secret_manager.get_secret = _fake
    try:
        return asyncio.run(ir.resolve_provider())
    finally:
        secret_manager.get_secret = original


def test_a_bare_install_blurs():
    """The case that was broken. Nothing configured, no cloud account, and the
    answer has to be a detector that runs here rather than None."""
    assert _resolve() == "local"


def test_both_toggles_are_on_for_a_bare_install():
    """settings() already defaulted these to True and documented why. They were
    inert because the provider resolved to None first."""
    async def _fake(key):
        return None

    from app.services import secret_manager
    original = secret_manager.get_secret
    secret_manager.get_secret = _fake
    try:
        provider, faces, plates = asyncio.run(ir.settings())
    finally:
        secret_manager.get_secret = original

    assert provider == "local"
    assert faces is True
    assert plates is True


def test_the_card_names_the_detector_that_is_actually_running():
    """The catalog default fed the UI. Showing Google Cloud Vision on an install
    with no Google account is the half of this bug that made it invisible."""
    from app.services.delivery_providers import normalize_provider
    assert normalize_provider("redaction", None) == "local"


def test_a_town_can_still_turn_it_off_deliberately():
    """Local is the floor, not a lock. The distinction that matters is between
    a town deciding not to blur and a town not knowing it wasn't."""
    assert _resolve(REDACTION_PROVIDER="none") is None
    assert _resolve(REDACTION_PROVIDER="off") is None
    assert _resolve(REDACTION_PROVIDER="disabled") is None


def test_an_explicit_choice_still_wins():
    assert _resolve(REDACTION_PROVIDER="azure") == "azure"
    assert _resolve(REDACTION_PROVIDER="google") == "google"


def test_a_town_with_cloud_credentials_still_gets_the_better_detector():
    """The fall-through exists so somebody who already pasted one set of cloud
    credentials gets redaction without configuring a second thing. Making local
    the floor must not shadow that."""
    assert _resolve(MODERATION_PROVIDER="google") == "google"
    assert _resolve(AI_PROVIDER="vertex") == "google"
    assert _resolve(AI_PROVIDER="bedrock") == "aws"
    assert _resolve(AI_PROVIDER="azure") == "azure"


def test_local_detection_needs_no_credential():
    """The reason this is a safe floor: nothing to configure, nothing to pay
    for, and no resident photo leaves the building."""
    from app.services.delivery_providers import REDACTION_CATALOG
    offered = {f["key"] for f in REDACTION_CATALOG["local"]["credential_fields"]}
    assert offered == {"REDACT_FACES", "REDACT_PLATES"}
