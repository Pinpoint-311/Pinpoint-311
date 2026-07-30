"""Using the identity the cloud already attached, instead of asking for a key.

The largest single burden in setup is credentials: a service-account JSON on
Google, an access key on AWS, a client secret on Azure. They are the values most
often mis-copied, the ones that then have to be vaulted, and -- on Azure -- the
one that expires on a date nobody records.

None of them is needed when the application runs on the cloud it is calling.
Every provider attaches an identity to the compute, and the SDKs pick it up with
nothing configured. This is not a shortcut with a security cost: no long-lived
credential exists to be leaked, mailed, committed, or left behind by a departing
employee. It happens to also be the version where a clerk types nothing.

Two of the three already worked here, by accident and unannounced. These tests
cover making it deliberate.
"""

import pytest

from app.services import cloud_identity as ci


@pytest.fixture(autouse=True)
def _clear_cache():
    ci._cache.update({"at": 0.0, "value": None})
    yield
    ci._cache.update({"at": 0.0, "value": None})


def test_no_attached_identity_is_a_clean_negative(monkeypatch):
    """A self-hosted town on its own hardware. Every probe fails, and the
    answer has to be "no" rather than an exception on a settings page."""
    monkeypatch.setattr(ci, "_google", lambda: None)
    monkeypatch.setattr(ci, "_azure", lambda: None)
    monkeypatch.setattr(ci, "_aws", lambda: None)

    result = ci.summary()
    assert result == {"attached": False, "provider": None,
                      "identity": None, "skippable_keys": []}


@pytest.mark.parametrize("provider,keys", [
    ("google", "GCP_SERVICE_ACCOUNT_JSON"),
    ("aws", "AWS_SECRET_ACCESS_KEY"),
    ("azure", "AZURE_KEYVAULT_CLIENT_SECRET"),
])
def test_an_attached_identity_names_the_keys_it_replaces(monkeypatch, provider, keys):
    """The page greys those boxes out and says why. Without the list a clerk
    sees an empty required-looking field and pastes a key anyway, which is the
    situation this is meant to end."""
    monkeypatch.setattr(ci, "_google", lambda: None)
    monkeypatch.setattr(ci, "_azure", lambda: None)
    monkeypatch.setattr(ci, "_aws", lambda: None)
    monkeypatch.setattr(ci, f"_{provider}",
                        lambda: {"provider": provider, "identity": "test"})

    result = ci.summary()
    assert result["attached"] is True
    assert result["provider"] == provider
    assert keys in result["skippable_keys"]


def test_only_the_proof_of_identity_is_skippable():
    """Key names, regions and endpoints identify *which* resource to use. They
    are not credentials and the attached identity does not supply them --
    marking them skippable would leave a town with no key configured at all."""
    everything = {k for keys in ci.SKIPPABLE.values() for k in keys}
    for must_still_be_asked in (
        "KMS_KEY_ID", "KMS_KEY_RING", "KMS_LOCATION", "AWS_REGION",
        "AWS_KMS_KEY_ID", "AZURE_KEYVAULT_URL", "AZURE_KEYVAULT_KEY",
        "GOOGLE_CLOUD_PROJECT",
    ):
        assert must_still_be_asked not in everything, must_still_be_asked


def test_a_probe_that_hangs_does_not_hang_the_page():
    """The probes hit link-local addresses that either answer at once or are
    not there. A generous timeout would stall a settings page for every town
    that is not on a cloud, which is most of them."""
    assert ci._PROBE_TIMEOUT <= 2


def test_detection_is_cached_but_not_forever():
    """Compute does not acquire an identity halfway through an afternoon, so
    probing on every request is waste -- but an operator who attaches one
    should not have to restart the server to be believed."""
    assert 0 < ci._CACHE_TTL <= 3600


def test_the_negative_result_is_cached_too(monkeypatch):
    """The expensive case is the town with no cloud at all: three probes that
    each have to time out. Caching only successes would pay that on every
    page load."""
    calls = []

    def _count():
        calls.append(1)
        return None

    monkeypatch.setattr(ci, "_google", _count)
    monkeypatch.setattr(ci, "_azure", _count)
    monkeypatch.setattr(ci, "_aws", _count)

    ci.detect()
    first = len(calls)
    ci.detect()
    assert len(calls) == first, "a negative result must be cached"


# ---------------------------------------------------------------------------
# Azure was the one that made a secret mandatory
# ---------------------------------------------------------------------------

def test_azure_accepts_a_managed_identity_instead_of_a_client_secret(monkeypatch):
    """is_configured() required tenant + client id + client secret, so a town
    on Azure had to create the worst credential of the three clouds when the
    platform was already offering it the best one."""
    pytest.importorskip("httpx")
    from app.core import azure_keyvault as akv

    monkeypatch.setattr(akv, "_cfg", lambda k: "https://v.vault.azure.net/" if k == "AZURE_KEYVAULT_URL" else None)
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/token")
    assert akv.is_configured() is True


def test_azure_still_requires_a_vault_url(monkeypatch):
    """The identity proves who is asking. It does not say which vault."""
    pytest.importorskip("httpx")
    from app.core import azure_keyvault as akv

    monkeypatch.setattr(akv, "_cfg", lambda k: None)
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/token")
    assert akv.is_configured() is False


def test_azure_without_an_identity_still_needs_the_full_secret(monkeypatch):
    """Off Azure, nothing has changed: the client-credentials flow is the only
    way in, and a partial set must not read as configured."""
    pytest.importorskip("httpx")
    from app.core import azure_keyvault as akv

    monkeypatch.delenv("IDENTITY_ENDPOINT", raising=False)
    monkeypatch.delenv("MSI_ENDPOINT", raising=False)
    values = {"AZURE_KEYVAULT_URL": "https://v.vault.azure.net/",
              "AZURE_TENANT_ID": "t", "AZURE_KEYVAULT_CLIENT_ID": "c"}
    monkeypatch.setattr(akv, "_cfg", lambda k: values.get(k))
    assert akv.is_configured() is False

    values["AZURE_KEYVAULT_CLIENT_SECRET"] = "s"
    assert akv.is_configured() is True
