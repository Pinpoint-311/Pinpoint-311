"""Report the town's situation, not a fact about the vendor.

Reported directly: "the texts thing was saying not testable when I never
entered text credentials." Both halves of the delivery test ended in a
fallthrough that described the *provider* -- "there is no way to check http
without sending a real text message" -- without first asking whether anything
had been saved. True about a generic HTTP gateway, and useless to a clerk whose
actual situation is that the boxes are empty.
"""

from app.services.delivery_providers import (
    EMAIL_CATALOG, SMS_CATALOG, describe_missing, missing_keys, required_keys,
)


def test_a_generic_gateway_needs_its_url():
    assert required_keys(SMS_CATALOG["http"]) == ["SMS_HTTP_API_URL"]


def test_an_optional_key_is_not_required():
    """The API key on a generic gateway is optional -- some accept an
    unauthenticated POST from an allow-listed address."""
    assert "SMS_HTTP_API_KEY" not in required_keys(SMS_CATALOG["http"])


def test_nothing_saved_is_reported_as_nothing_saved():
    assert missing_keys(SMS_CATALOG["http"], {}) == ["SMS_HTTP_API_URL"]
    assert missing_keys(SMS_CATALOG["http"], {"SMS_HTTP_API_URL": "https://gw"}) == []


def test_whitespace_is_not_a_credential():
    assert missing_keys(SMS_CATALOG["http"], {"SMS_HTTP_API_URL": "   "}) == ["SMS_HTTP_API_URL"]


def test_acs_email_is_checked_too():
    """The same fallthrough exists on the email side."""
    missing = missing_keys(EMAIL_CATALOG["acs"], {})
    assert missing, "ACS reports untestable before checking whether it is configured"


def test_the_message_uses_the_words_on_the_form():
    """Not the environment-variable names. Those are ours; a clerk has never
    seen them and cannot map them back to a box."""
    text = describe_missing(SMS_CATALOG["http"], ["SMS_HTTP_API_URL"])
    assert "POST URL" in text
    assert "SMS_HTTP_API_URL" not in text


def test_several_missing_boxes_are_listed_readably():
    entry = EMAIL_CATALOG["acs"]
    text = describe_missing(entry, missing_keys(entry, {}))
    assert " and " in text
    assert "_" not in text, f"raw key names leaked into the message: {text}"


def test_nothing_missing_says_nothing():
    assert describe_missing(SMS_CATALOG["http"], []) == ""


def test_every_delivery_provider_can_answer_the_question():
    """A provider whose catalog entry has no required fields would be reported
    as configured however empty it is -- that is the vacuous-truth case, and it
    is worth knowing which providers are in it."""
    for name, catalog in (("email", EMAIL_CATALOG), ("sms", SMS_CATALOG)):
        for provider, entry in catalog.items():
            keys = required_keys(entry)
            assert isinstance(keys, list), f"{name}:{provider}"
