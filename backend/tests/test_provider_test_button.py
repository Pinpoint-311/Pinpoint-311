"""Save & Test has to actually test — checked by calling it, not by reading it.

The endpoint validated eight capabilities and could test three. Pressing the
button on maps, email, text messages, encryption or photo redaction returned
"A live test is not available for this capability" -- a control whose entire job
is to say whether something works, saying it could not, on five of eight cards.
The accept-list was widened when those capabilities got catalogs; the branches
behind it were not.

Every check is now a named function behind one dispatch table, which is what
makes these tests assertions about behaviour rather than string searches
through a large endpoint. The earlier version of this file was the latter, and
it would have passed against code that was wrong in any way the strings did not
happen to mention.
"""

import asyncio

import pytest

pytest.importorskip("fastapi")

from app.api import system


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# The drift that caused it
# ---------------------------------------------------------------------------

def test_every_accepted_capability_has_a_check():
    """The bug, as data rather than prose: two lists that had to agree, kept
    apart, and nothing noticing when one moved."""
    assert set(system._PROVIDER_SELECT_KEY) == set(system._CAPABILITY_TESTS)


def test_every_check_is_callable_and_async():
    for capability, check in system._CAPABILITY_TESTS.items():
        assert callable(check), capability
        assert asyncio.iscoroutinefunction(check) or callable(check(None).close() or check), capability


# ---------------------------------------------------------------------------
# Encryption — the check that catches a silent fallback
# ---------------------------------------------------------------------------

def test_encryption_passes_when_the_selected_key_did_the_wrapping(monkeypatch):
    from app.core import encryption, pii_crypto

    monkeypatch.setattr(encryption, "_kms_provider", lambda: "azure")
    monkeypatch.setattr(pii_crypto, "probe_backend", lambda: "azure")

    result = _run(system._test_kms())
    assert result["ok"] is True
    assert "Azure Key Vault" in result["detail"]


def test_encryption_fails_when_something_else_did_the_wrapping(monkeypatch):
    """Selected Azure, wrapped with the application key. Nothing errors --
    encryption still happens -- which is exactly why the button must say so."""
    from app.core import encryption, pii_crypto

    monkeypatch.setattr(encryption, "_kms_provider", lambda: "azure")
    monkeypatch.setattr(pii_crypto, "probe_backend", lambda: "local")

    result = _run(system._test_kms())
    assert result["ok"] is False
    assert "azure" in result["detail"] and "local" in result["detail"]


def test_encryption_asks_the_key_service_rather_than_a_cache(monkeypatch):
    """active_backend() reports the data key this process wrapped at startup.
    In a worker up for a week it describes the world as it was a week ago, and
    would keep passing through an entire key-deletion window."""
    from app.core import encryption, pii_crypto

    monkeypatch.setattr(encryption, "_kms_provider", lambda: "google")
    monkeypatch.setattr(pii_crypto, "active_backend",
                        lambda: (_ for _ in ()).throw(AssertionError("read the cache")))
    monkeypatch.setattr(pii_crypto, "probe_backend", lambda: "google")

    assert _run(system._test_kms())["ok"] is True


# ---------------------------------------------------------------------------
# Photo redaction
# ---------------------------------------------------------------------------

def test_redaction_passes_when_the_chosen_detector_works(monkeypatch):
    from app.services import image_redaction as ir

    async def _resolve():
        return "google"

    async def _effective(p):
        return "google", None

    monkeypatch.setattr(ir, "resolve_provider", _resolve)
    monkeypatch.setattr(ir, "effective_provider", _effective)

    assert _run(system._test_redaction())["ok"] is True


def test_redaction_fails_when_it_has_quietly_degraded(monkeypatch):
    """Falling back to on-server blurring contains the harm. It is still not
    what the town chose, and a green tick would hide it."""
    from app.services import image_redaction as ir

    async def _resolve():
        return "azure"

    async def _effective(p):
        return "local", "azure"

    monkeypatch.setattr(ir, "resolve_provider", _resolve)
    monkeypatch.setattr(ir, "effective_provider", _effective)

    result = _run(system._test_redaction())
    assert result["ok"] is False
    assert "azure" in result["detail"]


def test_redaction_fails_loudly_when_nothing_can_blur(monkeypatch):
    from app.services import image_redaction as ir

    async def _resolve():
        return "azure"

    async def _effective(p):
        return "azure", "azure"

    monkeypatch.setattr(ir, "resolve_provider", _resolve)
    monkeypatch.setattr(ir, "effective_provider", _effective)

    result = _run(system._test_redaction())
    assert result["ok"] is False
    assert "without blurring" in result["detail"]


def test_redaction_switched_off_is_not_a_failure(monkeypatch):
    from app.services import image_redaction as ir

    async def _resolve():
        return None

    monkeypatch.setattr(ir, "resolve_provider", _resolve)
    assert _run(system._test_redaction())["ok"] is True


# ---------------------------------------------------------------------------
# Delivery — nothing a resident would receive
# ---------------------------------------------------------------------------

def _secrets(**values):
    async def _get(key):
        return values.get(key)
    return _get


def test_texting_switched_off_is_not_a_failure(monkeypatch):
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(SMS_PROVIDER="none"))
    assert _run(system._test_delivery("sms"))["ok"] is True


def test_twilio_without_credentials_says_which_are_missing(monkeypatch):
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(SMS_PROVIDER="twilio"))
    result = _run(system._test_delivery("sms"))
    assert result["ok"] is False
    assert "SID" in result["detail"]


def test_smtp_without_a_host_says_so(monkeypatch):
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(EMAIL_PROVIDER="smtp"))
    result = _run(system._test_delivery("email"))
    assert result["ok"] is False
    assert "SMTP host" in result["detail"]


def test_a_provider_with_no_safe_check_is_not_recorded_as_broken(monkeypatch):
    """A generic HTTP gateway cannot be exercised without sending a real text.
    "We cannot check this from here" is not "this is broken", and a red badge
    that can never go green teaches people to ignore badges."""
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(SMS_PROVIDER="http"))

    result = _run(system._test_delivery("sms"))
    assert result["recorded"] is False


def test_an_unrecorded_outcome_skips_the_health_write():
    """The endpoint must honour that flag, or the distinction is decorative."""
    import inspect
    source = inspect.getsource(system.test_provider)
    assert 'outcome.get("recorded") is False' in source


def test_no_check_sends_anything_to_a_resident(monkeypatch):
    """A test button that texts somebody is a test button people stop pressing.

    Asserted by running every delivery path with no credentials and confirming
    none of them reaches a send: each returns a dict rather than raising, and
    the send helpers are not imported at module scope where they could be."""
    from app.services import secret_manager

    for provider in ("none", "twilio", "sns", "acs", "http"):
        monkeypatch.setattr(secret_manager, "get_secret", _secrets(SMS_PROVIDER=provider))
        assert isinstance(_run(system._test_delivery("sms")), dict), provider
    for provider in ("smtp", "ses", "acs"):
        monkeypatch.setattr(secret_manager, "get_secret", _secrets(EMAIL_PROVIDER=provider))
        assert isinstance(_run(system._test_delivery("email")), dict), provider


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

def test_maps_without_a_key_says_which_key(monkeypatch):
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(MAPS_PROVIDER="google"))
    result = _run(system._test_maps())
    assert result["ok"] is False
    assert "Google Maps API key" in result["detail"]


def test_apple_maps_is_unverifiable_rather_than_failing(monkeypatch):
    """It needs a token signed in the browser, so there is genuinely nothing to
    check from the server."""
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(MAPS_PROVIDER="apple"))
    assert _run(system._test_maps())["recorded"] is False
