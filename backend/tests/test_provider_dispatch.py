"""Dispatch tests for the Azure and AWS provider pathways.

These pathways were wired but never exercised. Here we drive the *real*
selection logic with stubbed secrets/config and assert the right provider
class is constructed for each cloud — no live Azure/AWS calls, but the routing,
credential plumbing, and provider identity are all real.
"""
import importlib

import pytest

tp = importlib.import_module("app.services.translation_providers")
notif = importlib.import_module("app.services.notifications")
sm = importlib.import_module("app.services.secret_manager")


# --------------------------- Translation selection ---------------------------

def _fake_secrets(values):
    async def _get(key):
        return values.get(key)
    return _get


async def test_translation_selects_azure(monkeypatch):
    monkeypatch.setattr(sm, "get_secret", _fake_secrets({
        "TRANSLATION_PROVIDER": "azure",
        "AZURE_TRANSLATOR_KEY": "k",
        "AZURE_TRANSLATOR_REGION": "eastus",
        "AZURE_TRANSLATOR_ENDPOINT": "https://api.cognitive.microsofttranslator.com",
    }))
    provider = await tp.get_translation_provider()
    assert isinstance(provider, tp.AzureTranslationProvider)
    assert provider.provider == "azure"


async def test_translation_selects_aws(monkeypatch):
    monkeypatch.setattr(sm, "get_secret", _fake_secrets({
        "TRANSLATION_PROVIDER": "aws",
        "AWS_REGION": "us-gov-west-1",
        "AWS_ACCESS_KEY_ID": "AKIA",
        "AWS_SECRET_ACCESS_KEY": "secret",
    }))
    provider = await tp.get_translation_provider()
    assert isinstance(provider, tp.AWSTranslateProvider)
    assert provider.region == "us-gov-west-1"


async def test_translation_azure_unconfigured_returns_none(monkeypatch):
    # Azure selected but no key → no provider (rather than a broken one).
    monkeypatch.setattr(sm, "get_secret", _fake_secrets({"TRANSLATION_PROVIDER": "azure"}))
    assert await tp.get_translation_provider() is None


async def test_translation_defaults_to_google(monkeypatch):
    monkeypatch.setattr(sm, "get_secret", _fake_secrets({}))
    provider = await tp.get_translation_provider()
    assert isinstance(provider, tp.GoogleTranslationProvider)


@pytest.mark.parametrize("word", ["none", "off", "disabled"])
async def test_translation_none_is_off_not_the_google_default(monkeypatch, word):
    # A stored "none" used to fall through to Google, so translation ran for a
    # town whose status page reported it off. translate_batch already treats a
    # missing provider as "return the text unchanged", so None is safe here.
    monkeypatch.setattr(sm, "get_secret", _fake_secrets({"TRANSLATION_PROVIDER": word}))
    assert await tp.get_translation_provider() is None


# --------------------------- Notification selection --------------------------

def test_sms_configures_sns():
    svc = notif.NotificationService()
    svc.configure_sms("sns", {"region": "us-gov-west-1", "access_key": "AKIA", "secret_key": "s"})
    assert isinstance(svc._sms_provider, notif.SNSProvider)
    assert svc._sms_provider.region == "us-gov-west-1"


def test_sms_configures_acs():
    svc = notif.NotificationService()
    svc.configure_sms("acs", {"endpoint": "https://x.communication.azure.com",
                              "access_key": "k", "from_number": "+15551234567"})
    assert isinstance(svc._sms_provider, notif.ACSSMSProvider)


def test_email_configures_ses():
    svc = notif.NotificationService()
    svc.configure_email({"region": "us-gov-west-1", "from_email": "no-reply@town.gov",
                         "access_key": "AKIA", "secret_key": "s"}, provider_type="ses")
    assert isinstance(svc._email_provider, notif.SESEmailProvider)


def test_email_configures_acs():
    svc = notif.NotificationService()
    svc.configure_email({"endpoint": "https://x.communication.azure.com",
                         "access_key": "k", "from_email": "no-reply@town.gov"}, provider_type="acs")
    assert isinstance(svc._email_provider, notif.ACSEmailProvider)


def test_email_defaults_to_smtp():
    svc = notif.NotificationService()
    svc.configure_email({"smtp_host": "smtp.town.gov", "from_email": "no-reply@town.gov"})
    assert isinstance(svc._email_provider, notif.EmailProvider)
    assert not isinstance(svc._email_provider, (notif.SESEmailProvider, notif.ACSEmailProvider))


# --------------------------- Secret store routing ----------------------------

import sys
import types


def _fake_store(monkeypatch, name: str, value_for: str, value: str):
    """Stand a fake secret store in for a real one, both ways round.

    `from app.core import azure_keyvault` reads the attribute off the already
    imported `app.core` package before it ever consults sys.modules, so patching
    sys.modules alone only worked while nothing else in the run had imported the
    real module first. That made these two tests pass or fail depending on
    collection order -- they passed for a year because no other test happened to
    import app.core.azure_keyvault, and started failing the day one did.

    Patching both the package attribute and sys.modules makes the substitution
    hold regardless of what ran before.
    """
    import app.core

    fake = types.ModuleType(f"app.core.{name}")
    fake.is_configured = lambda: True
    fake.get_secret = lambda key: value if key == value_for else None
    monkeypatch.setitem(sys.modules, f"app.core.{name}", fake)
    monkeypatch.setattr(app.core, name, fake, raising=False)
    return fake


async def test_get_secret_routes_to_azure_key_vault(monkeypatch):
    _fake_store(monkeypatch, "azure_keyvault", "INTEGRATION_SDL_API_KEY", "azure-value")
    monkeypatch.setattr(sm, "_secrets_provider", lambda: "azure")

    assert await sm.get_secret("INTEGRATION_SDL_API_KEY") == "azure-value"


async def test_get_secret_routes_to_aws_secrets_manager(monkeypatch):
    _fake_store(monkeypatch, "aws_secretsmanager", "INTEGRATION_CITYWORKS_API_KEY", "aws-value")
    monkeypatch.setattr(sm, "_secrets_provider", lambda: "aws")

    assert await sm.get_secret("INTEGRATION_CITYWORKS_API_KEY") == "aws-value"
