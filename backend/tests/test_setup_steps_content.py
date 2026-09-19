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


# Everything that opens a new region of the file: a provider's steps, a
# provider's two paths, or a named step list one of those paths is built from.
# Splitting on all three is what keeps a plain scan honest now that a walk can
# be written once and referenced twice.
_BOUNDARY = re.compile(
    r"defineSteps\(\s*'(?P<cap>[a-z]+)'\s*,\s*'(?P<prov>[a-z0-9]+)'"
    r"|defineFork\(\s*'(?P<fcap>[a-z]+)'\s*,\s*'(?P<fprov>[a-z0-9]+)'"
    r"|const\s+(?P<name>\w+)\s*:\s*StepBuilder"
)


def _fields_in(block: str):
    fields = []
    for chunk in re.findall(r"fields:\s*\[([^\]]*)\]", block):
        fields += re.findall(r"'([A-Z0-9_]+)'", chunk)
    return fields


def _declarations():
    """[(capability, provider, [field keys]), ...] as written in the TSX.

    One entry per *walk*, not per provider. A cloud with a deployment template
    registers two complete walks for the same capability -- the template path
    and the by-hand path -- and both legitimately fill the same boxes, because
    they are two ways to reach the same credentials. Attributing every key in
    the region to one declaration would report that as a provider claiming a
    field twice, which is the one thing this file cannot afford to cry wolf
    about: the check exists to catch two inputs bound to one secret on a single
    screen, and only one path is ever on screen.

    So the named `StepBuilder` consts are collected first, and a `defineFork`
    yields one declaration per path, carrying that path's fields alone.
    """
    source = CONTENT.read_text()
    marks = list(_BOUNDARY.finditer(source))
    named = {}
    out = []
    forks = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(source)
        block = source[mark.start():end]
        if mark.group("name"):
            named[mark.group("name")] = _fields_in(block)
        elif mark.group("cap"):
            out.append((mark.group("cap"), mark.group("prov"), _fields_in(block)))
        else:
            forks.append((mark.group("fcap"), mark.group("fprov"), block))

    for cap, prov, block in forks:
        # `template: azureTemplateSteps(ctx), manual: azureManualSteps(ctx)`
        paths = re.findall(r"(?:template|manual):\s*(\w+)\(", block)
        assert paths, f"defineFork {cap}:{prov} names no step lists this can read"
        for name in paths:
            assert name in named, f"defineFork {cap}:{prov} references unknown {name}"
            out.append((cap, prov, named[name]))
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
    source = CONTENT.read_text()
    marks = list(_BOUNDARY.finditer(source))
    missing = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(source)
        block = source[mark.start():end]
        if "trouble:" in block or "note:" in block:
            continue
        if mark.group("cap"):
            missing.append(f"{mark.group('cap')}:{mark.group('prov')}")
        elif mark.group("name"):
            # A named walk one of the forks is built from. Named rather than
            # keyed by provider because that is all this scan knows about it,
            # and the name says which cloud and which path it is.
            missing.append(mark.group("name"))
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
    ):
        assert phrase in source, phrase

    # And that the end of the road is stated somewhere, in whatever words.
    #
    # This used to pin the single word "unrecoverable". A copy pass then said
    # the same thing more calmly -- "cannot be recovered, by you or by Google"
    # -- and the test failed on a rewrite that had lost nothing. The fact is
    # what has to survive a rewrite; the vocabulary is not, and pinning it
    # pushes the prose towards the more alarming word for no reader's benefit.
    assert re.search(r"cannot be recovered|unrecoverable", source), (
        "no walk says what happens once a key is actually gone"
    )


def test_redaction_says_how_to_prove_it_works():
    """Redaction is the only capability whose failure is invisible from inside
    the product: "found nobody" and "could not ask" both produce an unblurred
    photo and a green card. The only proof is looking at one."""
    source = CONTENT.read_text()
    assert "VERIFY_WITH_A_PHOTO" in source
    assert "UNCONFIGURED_DETECTOR" in source


def test_the_vault_registration_says_which_kind_of_app():
    """"Register an app" is not an instruction: Entra's New registration form
    asks for supported account types and a redirect URI before it will proceed.

    The two registrations in this product need OPPOSITE answers, which is why
    leaving it unsaid is worse than it looks. Staff sign-in is an interactive
    app and needs a Web redirect URI; the vault credential signs no one in and
    needs none. A reader who has just done the sign-in walk will paste the
    callback URL into both.
    """
    source = (ROOT / "frontend/src/components/setupStepsContent.tsx").read_text()

    # Wherever the vault credential is registered -- the by-hand walk and the
    # template walk both do it -- the account type and the redirect URI are named.
    for marker in ("Now the identity Pinpoint signs in as",
                   "How this server opens the vault"):
        assert marker in source, f"the vault registration step moved: {marker}"
        block = source[source.index(marker):][:900]
        assert "organizational directory only" in block, (
            f"{marker}: the step does not say which account type to choose"
        )
        assert "redirect" in block.lower(), (
            f"{marker}: the step does not say what to do about the redirect URI, "
            f"which the sign-in walk tells the same reader to fill in"
        )
