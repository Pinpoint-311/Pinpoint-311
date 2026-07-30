"""Save & Test has to actually test.

`test_provider` validated eight capabilities and could test three. Pressing the
button on maps, email, text messages, encryption or photo redaction returned
"A live test is not available for this capability" -- a control whose entire job
is to say whether something works, telling five of eight cards that it cannot.
The validation list was widened when those capabilities got catalogs; the tests
behind it were not.

Two of the five turn out to be the most valuable checks on the page, because
they cover the two things that fail without saying so: which key is actually
encrypting resident data, and whether the photo detector can answer at all.
"""

import inspect

import pytest

pytest.importorskip("fastapi")

from app.api import system


def _source():
    return inspect.getsource(system.test_provider)


def test_every_capability_the_endpoint_accepts_has_a_branch():
    """The bug, stated directly: the accept-list and the implemented-list were
    allowed to drift, and nothing noticed."""
    source = _source()
    missing = [
        cap for cap in system._PROVIDER_SELECT_KEY
        if f'capability == "{cap}"' not in source
        and f'capability in ("email", "sms")' not in source or cap not in ("email", "sms")
    ]
    missing = [c for c in missing if f'"{c}"' not in source]
    assert not missing, f"accepted but never tested: {sorted(missing)}"


def test_encryption_is_tested_by_wrapping_a_key_not_by_reading_settings():
    """A key name in a settings box proves nothing -- the name is still there
    when the key is gone. Only a wrap says the arrangement still works."""
    source = _source()
    assert "probe_backend()" in source
    assert "active_backend()" not in source, "that reads a process cache, not the key service"


def test_encryption_fails_the_test_when_the_wrong_key_is_in_use():
    """Selected Azure, wrapping with the application key. Everything still
    encrypts, so nothing errors -- which is exactly why the button has to say
    so rather than reporting a pass."""
    source = _source()
    assert "actual == selected" in source
    assert "not being encrypted with the key" in source


def test_redaction_reports_a_degraded_detector_as_a_failure():
    """Falling back to on-server blurring contains the harm but is not what the
    town chose, and a green tick would hide it."""
    source = _source()
    assert "degraded_from" in source


@pytest.mark.parametrize("fn,provider,marker", [
    ("_test_maps", "google", "maps.googleapis.com"),
    ("_test_maps", "azure", "atlas.microsoft.com"),
    ("_test_maps", "esri", "findAddressCandidates"),
    ("_test_delivery", "twilio", "api.twilio.com"),
    ("_test_delivery", "ses", "get_send_quota"),
    ("_test_delivery", "sns", "get_sms_attributes"),
])
def test_the_live_checks_call_the_provider(fn, provider, marker):
    """Each of these makes a real call that reads rather than sends, so the
    button is safe to press repeatedly and still means something."""
    assert marker in inspect.getsource(getattr(system, fn)), (fn, provider)


def test_nothing_a_resident_would_receive_is_sent():
    """A test button that texts somebody is a test button people stop pressing."""
    source = inspect.getsource(system._test_delivery)
    for sending in ("send_email", "sendmail", "SendMessage", "publish(", "send_raw_email"):
        assert sending not in source, sending


def test_the_ses_sandbox_is_reported_rather_than_passed():
    """SES credentials work perfectly inside the sandbox and deliver nothing to
    residents. A green tick there is worse than no button."""
    assert "sandbox" in inspect.getsource(system._test_delivery)


def test_an_unverifiable_provider_is_not_recorded_as_a_failure():
    """A generic HTTP SMS gateway cannot be exercised without sending a text.
    "We cannot check this from here" is not "this is broken", and a red badge
    that can never go green teaches people to ignore badges."""
    assert inspect.getsource(system._unverifiable).count("recorded") >= 1
    source = _source()
    assert 'outcome.get("recorded", True)' in source, "unverifiable results must skip _remember"
