"""The setup guide asks a questionnaire; the cards read a catalog. Same ids.

The guide turns four answers -- which cloud, which identity provider, which
map, and three overrides -- into plan items carrying `(capability, provider)`.
The page then looks each one up in `/providers/status` to decide whether it is
already done:

    providerStatus?.[item.cap]?.configured?.[item.provider] === true

A provider id the guide emits and the catalog does not have resolves to
`undefined`, which reads as "not set up" -- so the guide would walk a town
through configuring something and then keep insisting it was unfinished, with
no way to tell from the screen which of the two was wrong.

Nothing checked this in either direction. The ids are written out twice, in a
TypeScript component and in a Python catalog, and they only agree by hand.
"""

import pathlib
import re

import pytest

pytest.importorskip("fastapi")

from app.api.system import _PROVIDER_SELECT_KEY

FRONTEND = pathlib.Path("../frontend/src/components")


def _catalog_ids(capability: str) -> set:
    import asyncio

    from app.api.system import providers_for

    return {p["provider"] for p in asyncio.run(providers_for(capability))}


def _literal_set(source: str, pattern: str) -> set:
    """Every quoted id inside the first match of `pattern`."""
    m = re.search(pattern, source)
    assert m, f"could not find {pattern} — the questionnaire moved"
    return set(re.findall(r"'([a-z0-9_]+)'", m.group(1)))


@pytest.fixture(scope="module")
def page() -> str:
    path = FRONTEND / "SetupIntegrationsPage.tsx"
    if not path.exists():
        pytest.skip("frontend sources not present in this checkout")
    return path.read_text()


@pytest.fixture(scope="module")
def plan() -> str:
    path = FRONTEND / "setupPlan.ts"
    if not path.exists():
        pytest.skip("frontend sources not present in this checkout")
    return path.read_text()


def test_the_cloud_answer_maps_onto_real_ai_providers(page):
    """AI_BY_CLOUD turns "we are an AWS town" into an AI provider id."""
    assert _literal_set(page, r"AI_BY_CLOUD = \{([^}]*)\}") <= _catalog_ids("ai") | {
        "google", "azure", "aws"}  # the keys are clouds, the values providers
    values = set(re.findall(r"AI_BY_CLOUD = \{([^}]*)\}", page)[0].split(","))
    ids = {v.split(":")[1].strip().strip("'") for v in values if ":" in v}
    assert ids <= _catalog_ids("ai"), ids - _catalog_ids("ai")


def test_the_cloud_answer_maps_onto_real_email_providers(page):
    values = re.findall(r"EMAIL_BY_CLOUD = \{([^}]*)\}", page)[0].split(",")
    ids = {v.split(":")[1].strip().strip("'") for v in values if ":" in v}
    assert ids <= _catalog_ids("email"), ids - _catalog_ids("email")


def test_the_cloud_answer_maps_onto_real_sms_providers(page):
    values = re.findall(r"SMS_BY_CLOUD = \{([^}]*)\}", page)[0].split(",")
    ids = {v.split(":")[1].strip().strip("'") for v in values if ":" in v}
    assert ids <= _catalog_ids("sms"), ids - _catalog_ids("sms")


def _questionnaire_options(page: str) -> dict:
    """{onChange handler: [provider ids it offers]}.

    Read out of the JSX rather than duplicated here, so this stays a comparison
    between the two real lists rather than between the catalog and a third copy
    of the ids maintained in a test.
    """
    out = {}
    for m in re.finditer(r"onChange=\{(.*?)\}\s*options=\{\[(.*?)\]\}\s*/>", page, re.S):
        handler = " ".join(m.group(1).split())
        out[handler] = re.findall(r"\['([a-z0-9_]+)',", m.group(2))
    return out


@pytest.mark.parametrize("capability,handler", [
    ("email", "setEmailOverride"),
    ("sms", "setSmsOverride"),
    ("redaction", "setRedactionOverride"),
    ("maps", "(v) => setSetupMaps(v as typeof setupMaps)"),
    ("identity", "(v) => setSetupIdp(v as typeof setupIdp)"),
])
def test_every_option_the_questionnaire_offers_exists(page, capability, handler):
    """An option a town can pick that the catalog has never heard of walks them
    through a setup the cards cannot then represent, and leaves the checklist
    permanently unfinished."""
    options = _questionnaire_options(page)
    assert handler in options, f"the {capability} question moved; found {sorted(options)}"
    offered = set(options[handler])
    real = _catalog_ids(capability)
    assert offered <= real, f"{capability}: offered but not in the catalog: {offered - real}"


def test_the_questionnaire_is_not_hiding_a_provider_a_town_could_want(page):
    """The other direction, reported rather than enforced for SMS: `none` is a
    catalog entry the questionnaire deliberately does not offer, because "do
    you want text messages" is asked earlier as a feature tick."""
    options = _questionnaire_options(page)
    assert set(_catalog_ids("sms")) - set(options["setSmsOverride"]) == {"none"}


def test_the_identity_answers_exist():
    """Declared as a TypeScript union rather than an options array."""
    path = FRONTEND / "setupPlan.ts"
    if not path.exists():
        pytest.skip("frontend sources not present in this checkout")
    source = path.read_text()
    offered = _literal_set(source, r"export type Idp = ([^;]*);")
    assert offered == _catalog_ids("identity"), offered ^ _catalog_ids("identity")


def test_the_map_answers_exist():
    path = FRONTEND / "setupPlan.ts"
    if not path.exists():
        pytest.skip("frontend sources not present in this checkout")
    source = path.read_text()
    offered = _literal_set(source, r"export type MapProvider = ([^;]*);")
    assert offered == _catalog_ids("maps"), offered ^ _catalog_ids("maps")


def test_every_capability_the_plan_names_is_one_the_backend_serves(plan):
    """`cap:` in a plan item is the key the page indexes /providers/status
    with. One the backend does not serve is permanently "not set up"."""
    named = set(re.findall(r"cap: '([a-z]+)'", plan))
    assert named, "no plan items found — the file moved"
    assert named <= set(_PROVIDER_SELECT_KEY), named - set(_PROVIDER_SELECT_KEY)


def test_the_cloud_answers_are_the_ones_the_kms_and_secret_catalogs_offer(plan):
    """The guide passes the raw cloud id straight through as a provider for
    key management and for the secret store."""
    clouds = _literal_set(plan, r"export type Cloud = ([^;]*);")
    for capability in ("kms", "secrets", "translation"):
        real = _catalog_ids(capability)
        assert clouds <= real, f"{capability}: {clouds - real}"
