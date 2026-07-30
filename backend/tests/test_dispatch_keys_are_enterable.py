"""Every credential the dispatch code reads must have a box on the page.

The recurring failure on this platform is a setting that stores fine, reads
back fine, and silently does nothing. This is its purest form: code asks
`get_secret("AZURE_FACE_KEY")`, no card offers that key, so selecting the
provider saves a choice, reports success, and then finds nothing and does
nothing -- with no error and nowhere to go to fix it.

That is exactly what photo redaction did. Google and AWS reuse credentials
entered elsewhere, so nobody noticed that Azure does not: it reads four keys of
its own, and the catalog offered two toggles. A town could pick Azure, tick both
boxes, save, and have every resident photo stored unblurred.

The test is written against the dispatch code rather than a hand-listed set, so
adding a `get_secret("NEW_KEY")` to a provider path fails here instead of
shipping a switch that does nothing.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

# Dispatch modules whose secrets a town enters on the setup page.
DISPATCH_SOURCES = ("app/services/image_redaction.py",)

# Keys that are legitimately not per-provider credential fields.
EXEMPT = {
    # Which provider to use -- written by the provider picker, not typed.
    "REDACTION_PROVIDER", "MODERATION_PROVIDER", "AI_PROVIDER", "EMAIL_PROVIDER",
    "SMS_PROVIDER", "KMS_PROVIDER", "SECRETS_PROVIDER", "TRANSLATION_PROVIDER",
    "IDENTITY_PROVIDER", "MAPS_PROVIDER",
}


def _keys_read(path: Path):
    try:
        source = path.read_text()
    except OSError:
        return set()
    return set(re.findall(r'get_secret\(\s*"([A-Z0-9_]+)"', source))


def _all_catalog_keys():
    """Every key any provider card can accept, across every catalog."""
    keys = set()
    sources = (
        ("app.services.ai.registry", "AI_CATALOG"),
        ("app.services.translation_providers", "TRANSLATION_CATALOG"),
        ("app.services.identity", "IDENTITY_CATALOG"),
        ("app.services.map_provider", "MAP_CATALOG"),
    )
    for module, name in sources:
        try:
            catalog = getattr(__import__(module, fromlist=[name]), name)
        except Exception:
            continue
        for entry in catalog.values():
            keys |= {f["key"] for f in entry.get("credential_fields", [])}
    from app.services.delivery_providers import _CATALOGS
    for catalog in _CATALOGS.values():
        for entry in catalog.values():
            keys |= {f["key"] for f in entry.get("credential_fields", [])}
    return keys


def test_every_secret_the_dispatch_code_reads_has_somewhere_to_be_entered():
    enterable = _all_catalog_keys()
    assert enterable, "expected to load at least one provider catalog"

    unreachable = {}
    for relative in DISPATCH_SOURCES:
        for key in _keys_read(BACKEND / relative) - EXEMPT - enterable:
            unreachable.setdefault(relative, []).append(key)

    assert not unreachable, (
        "these secrets are read by dispatch code but no provider card offers "
        f"them, so nothing can ever set them: {unreachable}"
    )


def test_azure_redaction_offers_its_four_keys():
    """Named explicitly because this is the instance that was broken, and
    because the two endpoints are easy to collapse into one by mistake -- Face
    and Vision are separate Azure resources with separate keys."""
    from app.services.delivery_providers import REDACTION_CATALOG

    offered = {f["key"] for f in REDACTION_CATALOG["azure"]["credential_fields"]}
    for key in ("AZURE_FACE_ENDPOINT", "AZURE_FACE_KEY",
                "AZURE_VISION_ENDPOINT", "AZURE_VISION_KEY"):
        assert key in offered, key


def test_the_providers_that_reuse_credentials_do_not_ask_again():
    """Google and AWS take the service account and access keys entered
    elsewhere. Asking for them a second time here would be two boxes writing one
    secret, and whichever was filled last would win."""
    from app.services.delivery_providers import REDACTION_CATALOG

    for provider in ("google", "aws", "local"):
        offered = {f["key"] for f in REDACTION_CATALOG[provider]["credential_fields"]}
        assert offered == {"REDACT_FACES", "REDACT_PLATES"}, (provider, offered)
