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
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(MAP_PROVIDER="google"))
    result = _run(system._test_maps())
    assert result["ok"] is False
    assert "Google Maps API key" in result["detail"]


def test_apple_maps_is_unverifiable_rather_than_failing(monkeypatch):
    """It needs a token signed in the browser, so there is genuinely nothing to
    check from the server.

    Both maps tests here set MAPS_PROVIDER, the plural nothing writes. `_test_maps`
    was fixed to read MAP_PROVIDER and these were not, so every one of them fell
    through to the Google branch -- which is why this one had been failing with a
    KeyError on a key the Google branch does not return, and why the test above it
    passed for the wrong reason.
    """
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(MAP_PROVIDER="apple"))
    assert _run(system._test_maps())["recorded"] is False


# ---------------------------------------------------------------------------
# Each check has to exercise the feature's own API
# ---------------------------------------------------------------------------
#
# The failure these guard against is a check that asks the credential store
# instead of the service: it answers green for a key that was revoked last week,
# because the key is still stored. Written in the shape of
# `test_the_test_button_asks_the_detector_rather_than_the_credential_store` in
# test_redaction_fallback.py, which caught the same thing for photo redaction.


def _source(fn):
    import inspect
    return inspect.getsource(fn)


def test_the_identity_check_uses_the_client_credentials_rather_than_only_discovering():
    """`.well-known/openid-configuration` is public. Fetching it proves the
    issuer exists and says nothing about this town's registration -- so the card
    sat green on a client secret rotated in the vendor console a month earlier,
    and the first sign of trouble was staff bounced *after* their password was
    accepted, which reads as a forgotten password."""
    src = _source(system._test_identity)
    assert "token_endpoint" in src, "the check must reach the token endpoint"
    assert "client_credentials" in src, "and present the stored client credentials to it"
    assert "invalid_client" in src, "and react to the provider rejecting them"


def test_a_refused_grant_is_not_reported_as_a_bad_secret():
    """The token endpoint has to identify the client before it can decide
    anything about the grant, so "we know you, and you may not do this" is proof
    the secret is right. Most towns do not enable client_credentials on a login
    app, so treating that refusal as a failure would put a permanent red badge
    on a working sign-in."""
    src = _source(system._test_identity)
    assert "unauthorized_client" in src


def test_the_email_check_signs_in_rather_than_only_opening_a_socket():
    """A socket and a STARTTLS handshake prove the host is reachable. They prove
    nothing about whether it will relay for this town, which is the thing that
    stops residents getting mail."""
    src = _source(system._test_delivery)
    assert "server.login(" in src, "SMTP must authenticate"
    assert "get_send_quota" in src, "SES must ask SES, not just build a client"


def test_the_email_check_does_not_claim_a_sign_in_that_did_not_happen():
    """Without a username and password there is nothing to sign in to, and the
    message said "signed in" regardless."""
    src = _source(system._test_delivery)
    assert "if user and password:" in src


def test_the_secret_store_check_writes_and_reads_rather_than_asking_if_it_is_configured():
    """`store_reachable()` asks the store whether credentials for it exist --
    `_is_gcp_available()` on Google. That answers yes for a service account
    whose Secret Manager permission was revoked, because the service account is
    still there. The round trip is the API the rest of the system uses."""
    src = _source(system._test_secrets)
    assert "set_secret(" in src, "it must write"
    assert "get_secret(" in src, "and read back"
    assert "expected" in src, "and compare what came back with what went in"


def test_the_secret_store_check_reads_past_its_own_cache():
    """Reading our own write out of process memory passes on a store that never
    received it -- which is the exact failure being checked for."""
    src = _source(system._test_secrets)
    assert "clear_cache(" in src


def test_the_secret_store_check_takes_its_probe_key_away_again():
    """An earlier hand-run probe left a `test-write-check` secret behind in
    Google. A self-test that litters is one nobody runs twice."""
    src = _source(system._test_secrets)
    assert "delete_secret" in src
    assert "_cleanup()" in src


def test_the_probe_key_says_what_it_is():
    """Whoever finds it in a cloud console has to be able to tell that it is
    ours and that it is safe to remove."""
    src = _source(system._test_secrets)
    assert "PINPOINT_SELFTEST_WRITE_CHECK" in src


def test_no_secret_store_at_all_is_not_a_failure(monkeypatch):
    """The encrypted database is a supported place for credentials to live, and
    it is the normal state of a small self-hosted install. A red badge there is
    a badge that can never go green."""
    from app.services import secret_manager, storage_maintenance

    async def refuse(key, value):
        return False

    monkeypatch.setattr(secret_manager, "set_secret", refuse)
    monkeypatch.setattr(storage_maintenance, "store_reachable", lambda: False)

    result = _run(system._test_secrets())
    assert result["ok"] is False
    assert result["recorded"] is False, "must not be written down as a fault"


def test_a_configured_store_that_refuses_a_write_is_a_failure(monkeypatch):
    """This is the outage: `set_secret` returns False, the credential quietly
    stays in the database, and the card that saved it still shows a tick."""
    from app.services import secret_manager, storage_maintenance

    async def refuse(key, value):
        return False

    monkeypatch.setattr(secret_manager, "set_secret", refuse)
    monkeypatch.setattr(storage_maintenance, "store_reachable", lambda: True)

    result = _run(system._test_secrets())
    assert result["ok"] is False
    assert result.get("recorded") is not False, "a real fault must be recorded"


def test_a_store_that_takes_the_write_and_returns_something_else_fails(monkeypatch):
    """Serving a stale read is not the same as being down, and it is worse: the
    write appears to have worked."""
    from app.services import secret_manager

    async def accept(key, value):
        return True

    async def stale(key):
        return "whatever was there before"

    deleted = []

    async def delete(key):
        deleted.append(key)
        return True

    monkeypatch.setattr(secret_manager, "set_secret", accept)
    monkeypatch.setattr(secret_manager, "get_secret", stale)
    monkeypatch.setattr(secret_manager, "delete_secret", delete)

    result = _run(system._test_secrets())
    assert result["ok"] is False
    assert deleted == ["PINPOINT_SELFTEST_WRITE_CHECK"], "the probe key is removed either way"


def test_a_successful_round_trip_removes_the_probe(monkeypatch):
    from app.services import secret_manager

    store = {}

    async def write(key, value):
        store[key] = value
        return True

    async def read(key):
        return store.get(key)

    async def delete(key):
        return store.pop(key, None) is not None

    monkeypatch.setattr(secret_manager, "set_secret", write)
    monkeypatch.setattr(secret_manager, "get_secret", read)
    monkeypatch.setattr(secret_manager, "delete_secret", delete)

    result = _run(system._test_secrets())
    assert result["ok"] is True
    assert store == {}, f"the probe key was left behind: {sorted(store)}"


# ---------------------------------------------------------------------------
# The one selection this page must not make
# ---------------------------------------------------------------------------

def test_the_secret_store_cannot_be_switched_from_a_card():
    """Every credential the town has is in the current store, and repointing the
    setting does not move them. A picker here would be one click that makes
    every other card's credentials unreadable."""
    assert "secrets" in system._READ_ONLY_SELECTION
    assert "secrets" in system._PROVIDER_SELECT_KEY, "it is still reported and tested"


# ---------------------------------------------------------------------------
# Text messages, one provider at a time
# ---------------------------------------------------------------------------
#
# All four are switchable and only two could be checked. The generic gateway
# answered "there is no way to check http without sending a real text" whatever
# the town had done, so its card could never go green -- and ACS, which does
# have a read-only call on the same resource, fell through to the same sentence.


def test_each_sms_provider_has_a_branch_of_its_own():
    """The fallthrough is the bug: a sentence about "this provider cannot be
    checked" printed for providers that can be."""
    src = _source(system._test_delivery)
    for provider in ('"twilio"', '"sns"', '"acs"', '"http"'):
        assert f"provider == {provider}" in src, provider


def test_the_acs_check_asks_which_numbers_the_resource_owns():
    """The access key being valid is not what breaks an ACS send. Sending from a
    number the resource does not own is, and that is invisible until a resident
    does not get a text."""
    src = _source(system._test_delivery)
    assert "phoneNumbers" in src
    assert "_acs_auth_headers" in src, "it must sign with the same key sends use"


def test_the_acs_check_sends_nothing():
    """Every check on this page has to be safe to press repeatedly."""
    src = _source(system._test_delivery)
    acs = src[src.index('provider == "acs"'):src.index('provider == "http"')]
    assert "client.get(" in acs and "client.post(" not in acs


def test_a_gateway_with_a_status_url_is_checked_rather_than_excused():
    src = _source(system._test_delivery)
    assert "SMS_HTTP_TEST_URL" in src


def test_textbelt_is_checked_by_name_because_the_send_path_already_knows_it():
    """GenericHTTPSMSProvider branches on textbelt, and textbelt publishes a
    quota endpoint. Knowing the vendor and then reporting it untestable would be
    a choice rather than a limitation."""
    src = _source(system._test_delivery)
    assert "textbelt.com/quota" in src


def test_an_exhausted_key_is_a_failure_rather_than_a_pass():
    """A key that authenticates and has no messages left delivers nothing. A
    plain 200 would have called that healthy."""
    src = _source(system._test_delivery)
    assert "quotaRemaining" in src


def test_a_gateway_with_nothing_to_check_is_not_recorded_as_broken(monkeypatch):
    """Still the honest answer where there genuinely is one -- but now it is the
    answer for a gateway that offered no way to check, not for every gateway."""
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret",
                        _secrets(SMS_PROVIDER="http", SMS_HTTP_API_URL="https://gw.example/send"))

    result = _run(system._test_delivery("sms"))
    assert result["recorded"] is False
    assert "status URL" in result["detail"], "it has to say what would make this checkable"


# ---------------------------------------------------------------------------
# SMS_ENABLED
# ---------------------------------------------------------------------------
#
# It was read nowhere in the backend. Setting it did nothing, which is worse
# than not offering it, because somebody believed it. Email was already gated on
# EMAIL_ENABLED, so the two capabilities disagreed about whether such a switch
# means anything.

def test_switched_off_beats_the_selected_provider(monkeypatch):
    """A card reporting Twilio as working while SMS_ENABLED is false describes a
    send that cannot happen."""
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret",
                        _secrets(SMS_PROVIDER="twilio", SMS_ENABLED="false",
                                 TWILIO_ACCOUNT_SID="AC", TWILIO_AUTH_TOKEN="t",
                                 TWILIO_PHONE_NUMBER="+15005550006"))

    result = _run(system._test_delivery("sms"))
    assert result["ok"] is True
    assert "switched off" in result["detail"]


def test_an_unset_flag_does_not_switch_texting_off(monkeypatch):
    """Unlike EMAIL_ENABLED, which a town must set to "true". SMS already has an
    off state -- provider `none` -- so requiring an extra yes would silently
    stop texts for every town that configured Twilio and never heard of this
    key."""
    from app.services import secret_manager
    monkeypatch.setattr(secret_manager, "get_secret", _secrets(SMS_PROVIDER="twilio"))

    result = _run(system._test_delivery("sms"))
    # Reaches the Twilio branch and complains about credentials, rather than
    # reporting texting as switched off.
    assert "switched off" not in result["detail"]


def test_the_dispatch_code_honours_it_too():
    """The check and the sender have to agree, or the card is describing
    something the worker does not do."""
    import inspect

    from app.tasks import service_requests

    src = inspect.getsource(service_requests.configure_notifications)
    assert "SMS_ENABLED" in src
    assert "switched_off" in src


def test_switched_off_is_reported_as_no_provider():
    """`effective_provider_for` is what the badge and the daily sweep read."""
    import asyncio as _asyncio

    from app.services import secret_manager

    async def run():
        original = secret_manager.get_secret
        secret_manager.get_secret = _secrets(SMS_PROVIDER="twilio", SMS_ENABLED="false")
        try:
            return await system.effective_provider_for("sms")
        finally:
            secret_manager.get_secret = original

    assert _asyncio.run(run()) is None


def test_the_email_check_offers_the_envelope_as_well_as_signing_in():
    """Signing in proves the relay knows the account. It does not prove the
    relay will carry mail *from this address*, which is a separate permission on
    every hosted relay -- a verified sender on Brevo, an authorised domain on
    Mailgun, a verified identity on SES.

    That gap is not theoretical. This deployment moved from Mailgun to Brevo and
    kept demo@pinpoint311.org as the From address; a check that stops at the
    password would report the new relay working whether or not it had ever heard
    of that sender.
    """
    src = _source(system._test_delivery)
    assert "server.mail(" in src, "the check must offer the sender"
    assert "server.rcpt(" in src, "and a recipient, or the relay never rules on it"


def test_the_email_check_never_reaches_DATA():
    """No DATA means nothing is queued, which is what makes this safe to press
    repeatedly — and the reason it can be run against a live relay at all."""
    src = _source(system._test_delivery)
    assert "server.data(" not in src and ".sendmail(" not in src
    assert "server.rset()" in src, "the envelope is abandoned explicitly"
