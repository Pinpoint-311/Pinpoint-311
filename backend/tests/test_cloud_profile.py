"""Cloud-environment profile invariants.

The hybrid "one choice" cloud selector fans a single pick out to the AI,
translation and secret-store providers. These tests guard the two ways that
mapping can silently rot: a profile pointing at a provider that doesn't exist in
its catalog (so a switch would select nothing), and the derive logic that tells
the UI whether the current selections match a named profile or are a custom mix.
"""
import pytest

# The profiles live in the system API module, which needs the app stack. Skip
# cleanly where FastAPI isn't installed; CI installs requirements and runs these.
pytest.importorskip("fastapi")

from app.api.system import CLOUD_PROFILES, _derive_cloud_profile  # noqa: E402
from app.services.ai.registry import AI_CATALOG  # noqa: E402
from app.services.translation_providers import TRANSLATION_CATALOG  # noqa: E402
from app.services.identity import IDENTITY_CATALOG  # noqa: E402


_STORES = ("google", "azure", "aws")
_EMAIL = ("smtp", "ses", "acs")
_SMS = ("", "twilio", "http", "sns", "acs")


def test_every_profile_references_real_providers():
    assert set(CLOUD_PROFILES) == {"google", "azure", "aws"}
    for pid, p in CLOUD_PROFILES.items():
        assert p["ai"] in AI_CATALOG, f"{pid}: AI provider {p['ai']} missing from catalog"
        assert p["translation"] in TRANSLATION_CATALOG, f"{pid}: translation {p['translation']} missing"
        assert p["secrets"] in _STORES, f"{pid}: bad secret store {p['secrets']}"
        assert p["kms"] in _STORES, f"{pid}: bad KMS {p['kms']}"
        assert p["email"] in _EMAIL, f"{pid}: bad email provider {p['email']}"
        assert p["sms"] in _SMS, f"{pid}: bad SMS provider {p['sms']}"
        assert p["identity_recommended"] in IDENTITY_CATALOG, f"{pid}: IdP {p['identity_recommended']} missing"
        # Every profile must carry a human-facing compliance boundary label.
        assert p.get("boundary")


def test_derive_matches_named_profiles():
    for pid, p in CLOUD_PROFILES.items():
        assert _derive_cloud_profile(p["ai"], p["translation"], p["secrets"], p["kms"]) == pid


def test_partial_match_is_mixed():
    g, a = CLOUD_PROFILES["google"], CLOUD_PROFILES["azure"]
    # AI on Azure but translation/secrets on Google is a custom mix, not a profile.
    assert _derive_cloud_profile(a["ai"], g["translation"], g["secrets"]) == "mixed"
    # KMS mismatch alone (google core but aws KMS) is also a mix.
    assert _derive_cloud_profile(g["ai"], g["translation"], g["secrets"], "aws") == "mixed"
