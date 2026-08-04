"""Tests for catching a wrong credential when it is pasted.

The setup mistake that costs the most time is the right value in the wrong
field. Client ID and Client Secret sit next to each other, look identical behind
password dots, and produce an authentication error days later that names
neither of them. A shape check catches that in the moment, offline, for free.

The governing rule, asserted at the bottom: none of this blocks a save. A shape
rule is a heuristic about someone else's format and vendors change formats.
Refusing a credential that would actually have worked is a worse failure than
accepting one that will not -- the second is discoverable, the first is a dead
end with no way past it.
"""

import pytest

from app.services import credential_checks as cc


# ---- shape rules --------------------------------------------------------------

def test_a_good_google_maps_key_passes():
    assert cc.inspect_value("GOOGLE_MAPS_API_KEY", "AIza" + "x" * 35) is None


def test_a_google_key_pasted_into_the_arcgis_field_is_identified_as_google():
    """Naming what it *is* beats saying what it is not."""
    finding = cc.inspect_value("ARCGIS_API_KEY", "AIza" + "x" * 35)
    assert finding and "Google" in finding.message


def test_an_arcgis_key_pasted_into_the_google_field_is_identified_as_arcgis():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig"
    finding = cc.inspect_value("GOOGLE_MAPS_API_KEY", jwt)
    assert finding and "ArcGIS" in finding.message


def test_a_truncated_google_key_is_caught_by_length():
    """A short paste still starts with AIza and looks right."""
    finding = cc.inspect_value("GOOGLE_MAPS_API_KEY", "AIzaShort")
    assert finding and "39" in finding.message


def test_a_url_in_the_maps_key_field_says_so():
    finding = cc.inspect_value("GOOGLE_MAPS_API_KEY", "https://console.cloud.google.com")
    assert finding and "web address" in finding.message.lower()


@pytest.mark.parametrize("value,expect", [
    ("https://acme.us.auth0.com", "https://"),
    ("acme.us.auth0.com/", "trailing slash"),
    ("not a domain", "hostname"),
])
def test_auth0_domain_rejects_the_common_mistakes(value, expect):
    finding = cc.inspect_value("AUTH0_DOMAIN", value)
    assert finding and expect in finding.message.lower()


def test_a_plain_auth0_hostname_passes():
    assert cc.inspect_value("AUTH0_DOMAIN", "acme.us.auth0.com") is None


def test_an_issuer_with_the_discovery_path_appended_is_caught():
    """A very common paste: the docs show the .well-known URL, so people copy
    that instead of the issuer."""
    finding = cc.inspect_value("OIDC_ISSUER", "https://x.gov/.well-known/openid-configuration")
    assert finding and "well-known" in finding.message


def test_a_p8_pasted_without_its_header_is_caught():
    # Deliberately not a realistic-looking DER prefix. The check is only
    # "does this contain the words PRIVATE KEY", so the body is irrelevant to
    # the assertion, and a lifelike base64 blob here trips secret scanners for
    # no gain.
    finding = cc.inspect_value("APPLE_MAPKIT_PRIVATE_KEY", "not-a-real-key-body")
    assert finding and "BEGIN PRIVATE KEY" in finding.message


def test_a_real_p8_passes():
    key = "-----BEGIN PRIVATE KEY-----\nMIGTAgEA\n-----END PRIVATE KEY-----"
    assert cc.inspect_value("APPLE_MAPKIT_PRIVATE_KEY", key) is None


def test_a_service_account_file_is_checked_for_being_one():
    assert cc.inspect_value("VERTEX_AI_SERVICE_ACCOUNT_KEY", "not json") is not None
    assert cc.inspect_value("VERTEX_AI_SERVICE_ACCOUNT_KEY", '{"type":"user"}') is not None
    ok = '{"type":"service_account","private_key":"-----BEGIN PRIVATE KEY-----"}'
    assert cc.inspect_value("VERTEX_AI_SERVICE_ACCOUNT_KEY", ok) is None


# ---- the generic rule ---------------------------------------------------------

def test_spaces_in_an_unknown_secret_are_suspicious():
    """Nearly always a name or a sentence that landed in the wrong box."""
    finding = cc.inspect_value("SOME_VENDOR_TOKEN", "Public Works Department")
    assert finding and finding.severity == cc.SEVERITY_WARN


def test_whitespace_is_allowed_where_it_is_legitimate():
    """Private keys and JSON contain newlines by construction; warning about
    them would train people to ignore the warnings."""
    assert cc.inspect_value("APPLE_MAPKIT_PRIVATE_KEY",
                            "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----") is None
    assert cc.inspect_value("VERTEX_AI_SERVICE_ACCOUNT_KEY",
                            '{\n "type": "service_account",\n "private_key": "k"\n}') is None


def test_an_empty_value_is_never_a_finding():
    """Blank means "leave the stored one alone", not "wrong"."""
    for key in ("GOOGLE_MAPS_API_KEY", "AUTH0_DOMAIN", "ANYTHING"):
        assert cc.inspect_value(key, "") is None
        assert cc.inspect_value(key, "   ") is None


def test_an_unknown_key_with_a_sane_value_passes():
    assert cc.inspect_value("BRAND_NEW_VENDOR_KEY", "unrecognised-key-shape") is None


def test_findings_are_ordered_worst_first():
    findings = cc.inspect_settings({
        "SOME_TOKEN": "has spaces here",
        "GOOGLE_MAPS_API_KEY": "wrong",
    })
    assert [f.severity for f in findings] == [cc.SEVERITY_ERROR, cc.SEVERITY_WARN]


def test_a_clean_save_produces_nothing():
    assert cc.inspect_settings({"GOOGLE_MAPS_API_KEY": "AIza" + "x" * 35}) == []
    assert cc.inspect_settings({}) == []


# ---- explaining a provider's rejection ----------------------------------------

@pytest.mark.parametrize("message,expect", [
    ("API key not valid. Please pass a valid API key.", "pasted the whole thing"),
    ("This API project is not authorized to use this API.", "switched on"),
    ("Requests from referer http://x are blocked.", "allowed referrers"),
    ("BILLING_NOT_ENABLED", "Billing"),
    ("429 Too Many Requests", "rate limit"),
    ("403 Forbidden: insufficient permission", "permission"),
    ("401 invalid_client", "Authentication failed"),
    ("Email address is not verified. The following identities failed", "verified"),
    ("Account is in the sandbox", "sandbox"),
    ("Could not resolve host", "typo"),
    ("Read timed out", "did not answer in time"),
    ("SSL: CERTIFICATE_VERIFY_FAILED", "secure connection"),
])
def test_known_rejections_get_a_next_step(message, expect):
    assert expect.lower() in cc.explain_error(message).lower()


def test_an_unrecognised_error_gets_no_invented_advice():
    """Guessing here would be worse than silence -- the clerk would chase the
    wrong thing."""
    assert cc.explain_error("Widget frobnicator returned state 7") is None


def test_the_providers_own_words_always_come_first_and_unedited():
    """A clerk searching the web for their error needs the real string, and
    whoever they escalate to needs to see what the provider actually said."""
    original = "API key not valid. Please pass a valid API key."
    described = cc.describe_failure(original)
    assert described.startswith(original)
    assert len(described) > len(original)


def test_an_unrecognised_error_is_passed_through_untouched():
    assert cc.describe_failure("Widget state 7") == "Widget state 7"


def test_an_empty_error_still_says_something_useful():
    assert cc.describe_failure("") == "The provider rejected the request."
    assert cc.describe_failure(None) == "The provider rejected the request."


# ---- the governing rule -------------------------------------------------------

def test_nothing_here_can_block_a_save():
    """inspect_* returns findings; it has no way to refuse. Asserted structurally
    because the temptation to "just reject the obviously wrong ones" is exactly
    how a town gets locked out by a vendor changing a key format."""
    import inspect as py_inspect
    for fn in (cc.inspect_value, cc.inspect_settings):
        src = py_inspect.getsource(fn)
        assert "raise" not in src, f"{fn.__name__} must not be able to reject a credential"


# ---------------------------------------------------------------------------
# Whitespace around a pasted credential
# ---------------------------------------------------------------------------
#
# SMTP_USER on the live deployment was stored as " a475c9001@smtp-brevo.com".
# The relay answered 535 Authentication failed and no resident email went out,
# and every check on the page said email was fine:
#
#   * `inspect_value` strips before looking for spaces, so it only ever sees
#     the ones in the middle of a value;
#   * `_configured_map` strips before deciding a value is present, so the badge
#     was green;
#   * the value handed to the vendor was the only unstripped one in the chain.
#
# So the fix is at the write, not at each reader: a credential that differs
# depending on who asks for it is what made this invisible.

def test_a_saved_credential_is_stripped_before_it_is_stored():
    import inspect

    import pytest as _pytest
    _pytest.importorskip("fastapi")
    from app.api import system

    src = inspect.getsource(system._persist_secret)
    assert 'value = (value or "").strip()' in src


def test_the_plain_secret_endpoint_strips_too():
    """The setup page's plain fields post here, not through the provider save --
    and this is the path SMTP_USER came in on."""
    import inspect

    import pytest as _pytest
    _pytest.importorskip("fastapi")
    from app.api import system

    src = inspect.getsource(system.create_or_update_secret)
    assert '.strip()' in src


def test_a_credential_that_is_only_whitespace_is_not_configured():
    """" " and "" have to mean the same thing. They did everywhere except at the
    write, which is how a value could be simultaneously "present" for the badge
    and rejected by the vendor."""
    import inspect

    import pytest as _pytest
    _pytest.importorskip("fastapi")
    from app.api import system

    src = inspect.getsource(system._persist_secret)
    # The strip happens before is_configured is derived from the value.
    assert src.index('value = (value or "").strip()') < src.index("is_configured=bool(value)")
