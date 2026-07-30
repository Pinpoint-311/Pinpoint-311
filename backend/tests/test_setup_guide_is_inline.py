"""The setup guide is where setup happens, not a signpost to somewhere else.

This file exists because of a specific wrong turn. Asked to put the credential
boxes inline in the guide, I instead built the "step owns its fields" layout on
the provider cards and left the guide saying "scroll to the Maps card below and
choose your provider" -- and then wrote a test asserting the guide did NOT carry
the steps, which locked the mistake in. A test can encode a misreading as firmly
as it encodes a requirement.

So the requirement, stated plainly: a clerk following this guide top to bottom
never has to leave it. Each section that needs a credential renders the console
walk and the boxes it fills, for the provider the questionnaire already
established, with a Save & Test button.

There is still exactly one copy of the walk -- both the guide and the cards
mount ProviderCredentialSteps over setupStepsContent.tsx. The thing the old test
was really guarding, two hand-written copies drifting apart, is guarded by
`test_the_guide_does_not_repeat_the_cards_console_steps` in
test_setup_steps_content.py, which still passes and should keep passing.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "frontend/src/components/SetupIntegrationsPage.tsx"
INLINE = ROOT / "frontend/src/components/InlineProviderSetup.tsx"
SHARED = ROOT / "frontend/src/components/ProviderCredentialSteps.tsx"
CARDS = ROOT / "frontend/src/components/ServiceProviders.tsx"


@pytest.fixture(scope="module")
def guide() -> str:
    if not GUIDE.exists():
        pytest.skip("frontend not present in this checkout")
    return GUIDE.read_text()


# ---------------------------------------------------------------------------
# No handoffs
# ---------------------------------------------------------------------------

# The exact shapes the guide used to end its sections with. Any of these coming
# back means a section has gone back to describing work that happens elsewhere.
HANDOFF_PHRASES = (
    "Scroll to the",
    "card below and choose your",
    "card further down the page and",
)


def test_no_section_defers_to_a_card(guide):
    """A guide that says "go and do this somewhere else" is a table of contents.

    The specific failure: someone reading step 2 of sign-in was sent three
    thousand pixels down the page, to a card that then asked them again which
    provider they wanted -- a question they had answered in the questionnaire at
    the top of this very panel.
    """
    found = [p for p in HANDOFF_PHRASES if p in guide]
    assert not found, (
        f"the setup guide has gone back to pointing at the cards: {found}. "
        "Sections that need a credential should mount InlineProviderSetup instead."
    )


def test_every_credential_section_sets_up_inline(guide):
    """Each capability a town can configure from the guide does it here.

    Not an arbitrary list: these are the capabilities whose absence stops a town
    taking a report or sending a reply. Redaction is included because a fresh
    install blurs on this server and a town should be able to point that at a
    cloud without hunting for a card.
    """
    expected = {"identity", "maps", "ai", "translation", "kms", "email", "sms", "redaction"}
    mounted = set(re.findall(r'<InlineProviderSetup[^>]*?\scap="([a-z]+)"', guide))
    missing = expected - mounted
    assert not missing, f"no inline setup in the guide for: {sorted(missing)}"


def test_inline_setup_can_actually_save(guide):
    """Boxes with no save button are a form that loses what you typed.

    Each call site has to pass onSaved through, or the progress chips
    and "Done" badges at the top never move and the clerk cannot tell that
    anything landed.
    """
    if not INLINE.exists():
        pytest.skip("frontend not present in this checkout")
    inline = INLINE.read_text()
    assert "api.saveProvider" in inline, "the inline block cannot save"
    assert "api.testProvider" in inline, "a save that is not verified is the failure this page exists to avoid"
    assert "onSaved={onRefresh}" in guide, "saves in the guide never refresh the page's own status"


# ---------------------------------------------------------------------------
# One copy of the walk, rendered twice
# ---------------------------------------------------------------------------

def test_the_guide_and_the_cards_render_the_same_component():
    """Inline in two places is right. Written in two places is what drifted.

    Last time this page carried two hand-written copies, the guide told towns
    Okta's issuer was their org URL while the card told them the opposite.
    """
    if not (SHARED.exists() and CARDS.exists() and INLINE.exists()):
        pytest.skip("frontend not present in this checkout")
    for path in (CARDS, INLINE):
        assert "ProviderCredentialSteps" in path.read_text(), (
            f"{path.name} renders setup steps without the shared component"
        )
    # The shared component is the only place stepsFor is turned into markup.
    assert "stepsFor" in SHARED.read_text()


# ---------------------------------------------------------------------------
# Dynamic: the questionnaire actually drives what is shown
# ---------------------------------------------------------------------------

def test_the_cloud_answer_picks_the_provider_rather_than_asking_again(guide):
    """Asking "which cloud?" at the top is pointless if every section re-asks.

    AI, translation and key management are cloud decisions, so they take the
    answer. Email, SMS and redaction genuinely are not -- a town on Google may
    well send through SES -- so those keep a picker seeded from the cloud.
    """
    for derived in ("aiProvider", "emailProvider", "smsProvider", "redactionProvider"):
        assert f"const {derived} =" in guide, f"{derived} is not derived from the questionnaire"
    assert 'cap="ai" provider={aiProvider}' in guide
    assert 'cap="translation" provider={setupCloud}' in guide
    assert 'cap="kms" provider={setupCloud}' in guide
    assert 'cap="identity" provider={setupIdp}' in guide
    assert 'cap="maps" provider={setupMaps}' in guide


def test_changing_the_cloud_moves_the_email_and_sms_defaults(guide):
    """Held as an override, not a value.

    Storing the resolved provider would freeze it: a town that picked Google,
    then switched to Azure at the top, would still be looking at SMTP with
    nothing saying why. Holding "has the clerk overridden this?" instead lets
    the default follow the cloud while a deliberate pick stays put.
    """
    assert "emailOverride ?? EMAIL_BY_CLOUD[setupCloud]" in guide
    assert "smsOverride ?? SMS_BY_CLOUD[setupCloud]" in guide
    assert "redactionOverride ?? setupCloud" in guide


def test_every_extra_has_a_chip_and_every_chip_gates_something(guide):
    """A feature in the list with no chip cannot be turned off; a chip that
    gates nothing is a control that does nothing when clicked.

    Both existed. `errors` (crash reporting) had a section that rendered
    unconditionally and no chip at all, so the questionnaire's promise -- "untick
    it to hide the guide again" -- was false for it.
    """
    features = set(re.findall(r"'([a-z]+)'", re.search(r"const ALL_FEATURES = \[(.*?)\]", guide, re.S).group(1)))
    chips = set(re.findall(r"\['([a-z]+)', '[^']+'\]", guide))
    assert features == chips, (
        f"features without a chip: {sorted(features - chips)}; "
        f"chips that are not features: {sorted(chips - features)}"
    )
    ungated = [f for f in features if f"wants('{f}')" not in guide]
    assert not ungated, f"ticking these changes nothing on the page: {sorted(ungated)}"


def test_redaction_is_not_gated_on_the_moderation_tick(guide):
    """They are different decisions and were sharing one switch.

    Unticking "content moderation" silently hid face blurring, and there was no
    way to have blurring without it -- which matters because moderation screens
    what a resident wrote and redaction blurs a bystander who wrote nothing.
    """
    assert "show={wants('redaction')}" in guide, "redaction has no tick of its own"
    assert "redaction: 'redaction'" in guide, "the redaction capability is not mapped to its own feature"
    assert "moderation: 'redaction'" not in guide, "redaction is still riding on the moderation tick"


# ---------------------------------------------------------------------------
# Settings with no card still get boxes
# ---------------------------------------------------------------------------

# Keys the guide used to print as bare environment-variable names in the middle
# of a sentence. That is not an instruction a clerk can act on -- it reads as
# something to hand to IT, and it was the only place on this page that asked
# somebody to go and edit a file.
KEYS_THAT_NEED_A_BOX = (
    "AZURE_CONTENT_SAFETY_ENDPOINT",
    "AZURE_CONTENT_SAFETY_KEY",
    "SENTRY_DSN",
)


def test_settings_without_a_provider_card_still_have_inputs(guide):
    for key in KEYS_THAT_NEED_A_BOX:
        assert f"key: '{key}'" in guide, f"{key} is named in the guide but has no box to type it into"


def test_the_guide_does_not_tell_anyone_to_set_an_environment_variable(guide):
    """MODERATION_PROVIDER was printed as something to "set", with no box and no
    explanation of where. It is derived from the cloud answer, so nobody should
    be asked to set it at all."""
    assert "MODERATION_PROVIDER" not in guide
