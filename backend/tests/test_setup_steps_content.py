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

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "frontend/src/components/setupStepsContent.tsx"


def _catalogs():
    """The real catalogs, minus any that this environment cannot import.

    CI installs four packages, so `app.services.identity` -- which needs PyJWT
    to verify tokens -- is not importable there. Skipping the whole module on
    that basis would take the other twenty-four providers with it, so instead
    each catalog is imported on its own and the checks run against whatever
    loaded. A full install covers all of them; CI covers most.
    """
    catalogs = {}
    sources = {
        "ai": ("app.services.ai.registry", "AI_CATALOG"),
        "translation": ("app.services.translation_providers", "TRANSLATION_CATALOG"),
        "identity": ("app.services.identity", "IDENTITY_CATALOG"),
        "maps": ("app.services.map_provider", "MAP_CATALOG"),
    }
    for capability, (module, name) in sources.items():
        try:
            catalogs[capability] = getattr(__import__(module, fromlist=[name]), name)
        except Exception:
            continue
    try:
        from app.services.delivery_providers import _CATALOGS
        catalogs.update(_CATALOGS)
    except Exception:
        pass
    assert catalogs, "no provider catalog could be imported at all"
    return catalogs


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
        if capability not in catalogs:
            continue  # catalog not importable here; see _catalogs
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


# ---------------------------------------------------------------------------
# One copy of the console walk, not two
# ---------------------------------------------------------------------------

GUIDE = ROOT / "frontend/src/components/SetupIntegrationsPage.tsx"

# Sentences that only belong in a per-provider console walk. If the long-form
# guide starts carrying these again, it has grown a second copy of instructions
# that already live on the cards -- and the copies drift, which is not a
# hypothetical: the guide told towns Okta's issuer was their org URL while the
# card told them it was not, and it asked them to invent a backup passphrase
# months after that field was replaced by a generated one.
DUPLICATED_WALKS = (
    "Create App Integration",
    "New client secret",
    "Certificates &amp; secrets",
    "MapKit JS",
    "Create Credentials",
    "Regular Web Application",
    "Application URIs",
)


def test_the_guide_does_not_repeat_the_cards_console_steps():
    if not GUIDE.exists():
        pytest.skip("frontend not present in this checkout")
    source = GUIDE.read_text()
    repeated = [phrase for phrase in DUPLICATED_WALKS if phrase in source]
    assert not repeated, (
        "the setup guide has grown its own copy of a vendor console walk: "
        f"{repeated}. Those live in setupStepsContent.tsx, where the steps sit "
        "directly above the boxes they fill."
    )


def test_the_guide_no_longer_asks_for_an_invented_backup_passphrase():
    """The backup passphrase is generated and shown once. An instruction to
    choose one sends a clerk looking for a field that is not there."""
    if not GUIDE.exists():
        pytest.skip("frontend not present in this checkout")
    source = GUIDE.read_text()
    assert "Choose a strong" not in source
    assert "Create backup passphrase" in source


# ---------------------------------------------------------------------------
# Pitfalls
# ---------------------------------------------------------------------------

def test_every_provider_records_the_traps_it_has(declarations):
    """Somebody has walked this path and written down what bit them.

    Every path on this page has at least one: a key that Google issues without
    billing and that renders a grey box; an Entra secret shown once with a
    "Secret ID" next to it that is not the secret; an SES sandbox that accepts
    the message and delivers nothing; a KMS key whose deletion cannot be undone
    after the window closes. A provider with no warning almost always means
    nobody has walked it rather than that it has no traps.

    Redaction was the gap this caught: three of its four paths had no warning at
    all, and one of them is the default every install now lands on.

    Widened from `trouble` to `trouble or note`. It used to demand an amber
    warning on every path, which is part of how there came to be one on every
    other step -- writing a new walk meant adding a warning whether or not the
    path had anything alarming in it, and the real ones then had to compete
    with them. The intent survives: what must exist is evidence somebody walked
    it. Whether that evidence is alarming is a separate question, answered by
    `test_warnings_are_rare_enough_to_read`.
    """
    import re

    source = CONTENT.read_text()
    calls = list(re.finditer(r"defineSteps\(\s*'([a-z]+)'\s*,\s*'([a-z0-9]+)'", source))
    missing = []
    for i, call in enumerate(calls):
        end = calls[i + 1].start() if i + 1 < len(calls) else len(source)
        block = source[call.start():end]
        if "trouble:" not in block and "note:" not in block:
            missing.append(f"{call.group(1)}:{call.group(2)}")
    assert not missing, f"nothing written down about the traps in: {missing}"


def test_the_key_deletion_warnings_are_present():
    """The one failure on this page that cannot be undone. Each cloud words it
    differently and each has its own window, so this checks all three rather
    than trusting one sentence to cover them."""
    source = CONTENT.read_text()
    for phrase in (
        "lien",                       # google: project deletion is refused
        "purge protection",           # azure: soft-deleted keys stay recoverable
        "kms:ScheduleKeyDeletion",    # aws: explicit deny beats any allow
        "unrecoverable",              # what happens if all of that fails
    ):
        assert phrase in source, phrase


def test_redaction_says_how_to_prove_it_works():
    """Redaction is the only capability whose failure is invisible from inside
    the product: "found nobody" and "could not ask" both produce an unblurred
    photo and a green card. The only proof is looking at one."""
    source = CONTENT.read_text()
    assert "VERIFY_WITH_A_PHOTO" in source
    assert "UNCONFIGURED_DETECTOR" in source
