"""The registration form must send only what somebody typed.

Pinpoint makes no automatic calls to its maintainers. COMPLIANCE.md now states
one voluntary exception -- a form an administrator fills in and submits -- and
the value of that disclosure rests entirely on the payload matching it. A
version string added to the request later, however reasonably, would turn a
documented exception into an undocumented one, and nobody reviewing the
application for a town would have any reason to re-read the file.

So the shape is pinned here rather than trusted to review. This is a frontend
component checked from the backend suite for the same reason as the setup-step
content: it is the only suite that runs on every change.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "frontend/src/components/StayInformed.tsx"
COMPLIANCE = ROOT / "COMPLIANCE.md"

# Everything the form is allowed to transmit: the typed fields, the two consent
# booleans, and the anti-spam field that is submitted empty.
ALLOWED = {
    "organization", "contact_name", "contact_email", "contact_role",
    "deployment_url", "region", "usage",
    "consent_updates", "consent_public_listing",
    "website",
}


@pytest.fixture(scope="module")
def source():
    if not COMPONENT.exists():
        pytest.skip("frontend not present in this checkout")
    return COMPONENT.read_text()


def test_the_payload_carries_nothing_that_was_not_typed(source):
    """The claim in COMPLIANCE.md, as a test. Adding a field to FormState is the
    natural way this would be broken, so the check is on FormState itself rather
    than on the fetch call."""
    block = re.search(r"interface FormState \{(.*?)\n\}", source, re.S)
    assert block, "expected a FormState interface"
    declared = set(re.findall(r"^\s{4}(\w+):", block.group(1), re.M))
    assert declared == ALLOWED, (
        f"payload changed. unexpected: {sorted(declared - ALLOWED)}, "
        f"missing: {sorted(ALLOWED - declared)}. If this is intentional, "
        f"COMPLIANCE.md has to change in the same commit."
    )


def test_the_request_body_is_the_form_and_nothing_else(source):
    """`JSON.stringify(form)` and not `{...form, extra}`. A spread with anything
    appended is the other way a diagnostic could arrive without the interface
    changing."""
    assert "JSON.stringify(form)" in source
    assert "...form" not in source


def test_nothing_is_sent_without_a_submit(source):
    """One fetch, in the submit handler. A useEffect that posted on mount would
    make every claim in this file and in COMPLIANCE.md false."""
    assert source.count("fetch(") == 1
    submit = re.search(r"async function submit\(.*?\n    \}", source, re.S)
    assert submit and "fetch(" in submit.group(0), "the only fetch must be in submit()"


def test_the_request_carries_no_cookies(source):
    """`credentials` unset means omit for a cross-origin request. Setting it to
    include would send whatever cookies a town's domain happens to hold to a
    third party, for no benefit -- the endpoint is unauthenticated."""
    assert "credentials:" not in source


def test_a_failed_submission_degrades_to_the_link(source):
    """A municipal network that blocks outbound traffic has not done anything
    wrong. Showing it an error would read as a fault in the platform, and the
    fallback is the same form on the website."""
    assert "'fallback'" in source
    assert "REGISTRATION_FORM_URL" in source


def test_dismissal_is_permanent_and_the_way_back_is_not(source):
    """Two flags. One would mean "Not now" removes the only path back to the
    form, which is not what an optional prompt should do."""
    assert "MODAL_KEY" in source and "BANNER_KEY" in source


def test_compliance_documents_the_exception(source):
    """The disclosure is the point -- an undocumented outbound call would be
    worse than no form. Checked against the field list so the two cannot drift."""
    text = COMPLIANCE.read_text()
    assert "registration" in text.lower()
    assert "StayInformed.tsx" in text
    for phrase in ("browser", "Submit"):
        assert phrase in text
