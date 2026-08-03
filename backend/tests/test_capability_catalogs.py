"""The capabilities whose provider switch existed but was never surfaced.

`EMAIL_PROVIDER`, `SMS_PROVIDER`, `KMS_PROVIDER` and `REDACTION_PROVIDER` are
each read by live dispatch code -- configure_notifications, pii_crypto's
wrap/unwrap, and image_redaction's detector selection -- and not one of them had
a catalog. The admin console had a hand-written SMTP-and-Twilio card and no way
at all to reach Amazon SES, Azure Communication Services, Amazon SNS, any KMS,
or photo redaction. Those settings could only be changed by writing a secret by
hand.

Two things are guarded here, and they are the two ways this goes wrong quietly:

  * every field a card collects must be a key the dispatch code actually reads,
    or the town types a credential into a box and nothing uses it;
  * the generic catalog route must stay registered after the hand-written ones,
    because FastAPI takes the first match and /{capability}/catalog would
    otherwise shadow /ai/catalog and 404 it.
"""

import re

import pytest

from app.services.delivery_providers import (
    _CATALOGS,
    _DEFAULTS,
    catalog_for_api,
    normalize_provider,
)

# Where each provider's settings are actually consumed.
DISPATCH_SOURCES = (
    "app/tasks/service_requests.py",
    "app/core/encryption.py",
    "app/core/azure_keyvault.py",
    "app/core/aws_kms.py",
    "app/core/pii_crypto.py",
    "app/services/notifications.py",
    "app/services/image_redaction.py",
    # image_redaction dispatches Google and AWS detection through here, so this
    # is where the cloud credentials the redaction card collects are read.
    # Missing from the list, a card could ask for a Google or AWS key under any
    # name it liked and this test would have nodded it through.
    "app/services/cloud_moderation.py",
)


def _keys_the_code_reads():
    seen = set()
    for path in DISPATCH_SOURCES:
        try:
            # Both quote styles. Only double quotes were matched, and
            # encryption.py reads the Google service account out of the database
            # with a single-quoted SQL literal -- so the one credential the KMS
            # card cannot work without looked, to this test, like a key nothing
            # reads.
            seen |= set(re.findall(r'''["']([A-Z][A-Z0-9_]{3,})["']''', open(path).read()))
        except OSError:
            pass
    return seen


def test_every_declared_field_is_a_key_the_code_reads():
    """The whole failure mode this catalog exists to avoid: a card that collects
    a credential nothing consumes. Caught three wrong names when written --
    TWILIO_FROM_NUMBER for TWILIO_PHONE_NUMBER, SMS_API_URL for
    SMS_HTTP_API_URL, AZURE_KEY_VAULT_URL for AZURE_KEYVAULT_URL."""
    read = _keys_the_code_reads()
    declared = [
        (cap, provider, entry["key"])
        for cap, catalog in _CATALOGS.items()
        for provider, spec in catalog.items()
        # `requires` too. It names credentials collected on another card, and a
        # typo there is worse than a typo in a box: there is no box to look at,
        # so the only symptom is a badge that never goes green.
        for entry in list(spec["credential_fields"]) + list(spec.get("requires", []))
    ]
    orphans = [f"{cap}/{provider}: {key}" for cap, provider, key in declared if key not in read]
    assert not orphans, "fields nothing reads: " + ", ".join(orphans)


def test_alternative_credential_sets_name_fields_the_card_collects():
    """`requires_any` lists keys, not field definitions. A key that is not also
    a credential field is a rule about a box that does not exist."""
    for cap, catalog in _CATALOGS.items():
        for provider, spec in catalog.items():
            offered = {f["key"] for f in spec["credential_fields"]}
            for group in spec.get("requires_any", []):
                assert group, f"{cap}/{provider}: empty alternative group"
                for key in group:
                    assert key in offered, f"{cap}/{provider}: {key} is in requires_any but has no field"


@pytest.mark.parametrize("capability", sorted(_CATALOGS))
def test_the_catalog_matches_the_providers_the_dispatch_code_branches_on(capability):
    """Offering a provider the backend cannot route to stores fine, reads back
    fine and silently does nothing -- the exact shape of several bugs already
    fixed in this codebase."""
    implemented = {
        "email": {"smtp", "ses", "acs"},
        "sms": {"none", "twilio", "http", "sns", "acs"},
        "kms": {"google", "azure", "aws", "local"},
        "redaction": {"google", "aws", "azure", "local"},
        # `_secrets_provider()` branches on three, and every write falls back to
        # the encrypted database when the selected store is unreachable -- a
        # supported state, so it is a listed provider rather than a hidden one.
        "secrets": {"google", "azure", "aws", "database"},
    }[capability]
    assert set(_CATALOGS[capability]) == implemented


@pytest.mark.parametrize("capability", sorted(_CATALOGS))
def test_the_api_shape_matches_the_other_capabilities(capability):
    """Same shape as AI/translation/identity/maps, so the existing card renders
    them without a special case."""
    for entry in catalog_for_api(capability):
        assert set(entry) >= {"provider", "name", "description", "credential_fields"}
        assert isinstance(entry["credential_fields"], list)


@pytest.mark.parametrize("capability", sorted(_CATALOGS))
def test_an_unknown_provider_falls_back_to_the_default(capability):
    assert normalize_provider(capability, "nonsense") == _DEFAULTS[capability]
    assert normalize_provider(capability, None) == _DEFAULTS[capability]
    assert normalize_provider(capability, "") == _DEFAULTS[capability]


def test_sms_off_is_a_real_choice_not_an_empty_string():
    """The dispatch code treats any unrecognised value as off, so a blank and a
    typo mean the same thing. The picker says so instead of showing nothing."""
    assert "none" in _CATALOGS["sms"]
    assert _CATALOGS["sms"]["none"]["credential_fields"] == []


def test_every_capability_has_a_provider_select_key():
    pytest.importorskip("fastapi")  # system.py pulls in the API stack
    from app.api.system import _PROVIDER_SELECT_KEY

    for capability in _CATALOGS:
        assert capability in _PROVIDER_SELECT_KEY, capability


def test_the_generic_catalog_route_does_not_shadow_the_handwritten_ones():
    """FastAPI takes the first match. Declared before /ai/catalog, the generic
    /{capability}/catalog swallows it and 404s -- which is what happened on the
    first attempt, and it does not show up in any other test."""
    pytest.importorskip("fastapi")
    from app.api.system import router

    paths = [r.path for r in router.routes if r.path.endswith("/catalog")]
    generic = paths.index("/{capability}/catalog")
    for handwritten in ("/ai/catalog", "/translation/catalog", "/identity/catalog", "/maps/catalog"):
        assert paths.index(handwritten) < generic, (
            f"{handwritten} is registered after the generic route and would be shadowed"
        )
