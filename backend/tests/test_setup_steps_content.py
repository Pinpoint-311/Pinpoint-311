"""The setup instructions must name credential keys that actually exist.

`setupStepsContent.tsx` is prose about somebody else's console, and prose cannot
be tested. What can be tested is the part of it that is load-bearing: each step
declares `fields: ['SOME_KEY']`, and the card renders exactly those inputs
beneath that step. A key invented from memory renders a box that looks like
every other box, accepts what a clerk types, and saves it to a name nothing
reads -- which is indistinguishable, from the clerk's side, from a credential
that does not work.

That is not hypothetical. Three keys in an earlier draft of this file were
wrong: TWILIO_FROM_NUMBER for TWILIO_PHONE_NUMBER, SMS_API_URL for
SMS_HTTP_API_URL, and AZURE_KEY_VAULT_URL for AZURE_KEYVAULT_URL. All three were
plausible, none existed, and nothing would have said so.

So this parses the TSX and checks every declaration against the catalogs the
save endpoint validates against -- the same dicts, not a copy of them.
"""

import re
from pathlib import Path

import pytest

CONTENT = Path(__file__).resolve().parents[2] / "frontend/src/components/setupStepsContent.tsx"


def _catalogs():
    from app.services.ai.registry import AI_CATALOG
    from app.services.delivery_providers import _CATALOGS
    from app.services.identity import IDENTITY_CATALOG
    from app.services.map_provider import MAP_CATALOG
    from app.services.translation_providers import TRANSLATION_CATALOG

    return {
        "ai": AI_CATALOG,
        "translation": TRANSLATION_CATALOG,
        "identity": IDENTITY_CATALOG,
        "maps": MAP_CATALOG,
        **_CATALOGS,
    }


def _declarations():
    """[(capability, provider, [field keys]), ...] as written in the TSX.

    Each defineSteps call runs to the next one, so the fields between two calls
    belong to the first -- which is what lets a plain scan attribute keys to
    providers without parsing JSX.
    """
    source = CONTENT.read_text()
    calls = list(re.finditer(r"defineSteps\(\s*'([a-z]+)'\s*,\s*'([a-z0-9]+)'", source))
    out = []
    for i, call in enumerate(calls):
        end = calls[i + 1].start() if i + 1 < len(calls) else len(source)
        body = source[call.start():end]
        fields = []
        for block in re.findall(r"fields:\s*\[([^\]]*)\]", body):
            fields += re.findall(r"'([A-Z0-9_]+)'", block)
        out.append((call.group(1), call.group(2), fields))
    return out


@pytest.fixture(scope="module")
def declarations():
    if not CONTENT.exists():
        pytest.skip("frontend not present in this checkout")
    found = _declarations()
    assert found, "expected to parse defineSteps declarations out of the TSX"
    return found


def test_every_step_names_a_real_capability_and_provider(declarations):
    """A typo'd provider id registers steps under a key nothing looks up, so the
    card silently falls back to its plain field list and the instructions vanish
    with no error anywhere."""
    catalogs = _catalogs()
    for capability, provider, _ in declarations:
        assert capability in catalogs, f"unknown capability: {capability}"
        assert provider in catalogs[capability], f"unknown provider: {capability}:{provider}"


def test_every_declared_field_exists_in_that_providers_catalog(declarations):
    """The failure this file is here for. The save endpoint rejects any key not
    in the provider's credential_fields, so a wrong key here is a box whose
    contents are refused -- or, worse, one whose contents are accepted under a
    name no reader consults."""
    catalogs = _catalogs()
    problems = []
    for capability, provider, fields in declarations:
        entry = catalogs.get(capability, {}).get(provider)
        if not entry:
            continue
        real = {f["key"] for f in entry.get("credential_fields", [])}
        for key in fields:
            if key not in real:
                problems.append(f"{capability}:{provider} declares {key}; catalog has {sorted(real)}")
    assert not problems, "\n".join(problems)


def test_no_field_is_claimed_by_two_steps(declarations):
    """The card renders each step's fields beneath it. A key in two steps renders
    two inputs bound to one secret, and whichever the clerk fills second wins."""
    for capability, provider, fields in declarations:
        assert len(fields) == len(set(fields)), f"{capability}:{provider} repeats a field"


def test_every_provider_with_credentials_has_instructions(declarations):
    """The card falls back to a plain list of labelled boxes when a provider has
    no steps, which is a supported state -- but for a provider whose credentials
    come from a console menu three levels deep, a labelled box is not enough to
    act on. Providers with no credentials at all (Off, the application key) are
    exempt: there is nothing to instruct.
    """
    catalogs = _catalogs()
    written = {(c, p) for c, p, _ in declarations}
    missing = [
        f"{capability}:{provider}"
        for capability, catalog in catalogs.items()
        for provider, entry in catalog.items()
        if entry.get("credential_fields") and (capability, provider) not in written
    ]
    assert not missing, f"no setup steps written for: {sorted(missing)}"


def test_the_instructions_cover_every_credential_box(declarations):
    """A field no step claims still renders, at the end of the card, so nothing
    becomes unreachable. But an orphaned box is one the instructions never
    mention, which leaves a clerk to guess -- so a provider that has steps at all
    should account for all of its fields.
    """
    catalogs = _catalogs()
    orphans = []
    for capability, provider, fields in declarations:
        entry = catalogs.get(capability, {}).get(provider)
        if not entry:
            continue
        real = {f["key"] for f in entry.get("credential_fields", [])}
        for key in sorted(real - set(fields)):
            orphans.append(f"{capability}:{provider} field {key} is in no step")
    assert not orphans, "\n".join(orphans)


def test_the_callback_url_matches_the_route_that_receives_it():
    """Every identity provider is told to register the same redirect URI, and it
    has to be the one `auth.py` actually builds. A mismatch is the worst failure
    on this page: the password is accepted, the redirect is refused, and the
    error a clerk sees says nothing about a URL."""
    pytest.importorskip("fastapi")
    import inspect

    from app.api import auth

    source = inspect.getsource(auth)
    assert '"/api/auth/callback"' in source or "/api/auth/callback" in source
    assert "/api/auth/callback" in CONTENT.read_text()
