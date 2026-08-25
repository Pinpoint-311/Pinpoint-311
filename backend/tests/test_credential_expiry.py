"""A credential that runs out on a date nobody is reminded about.

Entra caps a client secret at 24 months and says nothing when one lapses: the
vault stops answering, PII stops decrypting, and it reads as a bug rather than a
date. The setup walk used to say "diary the date", which is an instruction to a
person because the software did not help.
"""
from datetime import date, timedelta

import pytest

pytest.importorskip("app.services.credential_expiry")
from app.services.credential_expiry import check_expiry, parse_expiry  # noqa: E402


TODAY = date(2026, 8, 25)


def test_nothing_recorded_says_nothing():
    """Silence is right for a town on a managed identity: there is no secret,
    so a warning about one would be noise it can never clear."""
    assert check_expiry(None, label="x", today=TODAY) is None
    assert check_expiry("   ", label="x", today=TODAY) is None


def test_a_date_far_off_is_not_a_warning():
    status = check_expiry("2028-01-01", label="The secret", today=TODAY)
    assert status.severity == "info"
    assert status.expired is False


def test_a_month_out_warns():
    soon = (TODAY + timedelta(days=10)).isoformat()
    status = check_expiry(soon, label="The secret", today=TODAY)
    assert status.severity == "warning"
    assert "10 days" in status.message


def test_an_expired_date_says_the_data_is_not_lost():
    """The reassurance is the point. An operator seeing decryption fail assumes
    the worst; the key is still in the vault and nothing has been destroyed."""
    status = check_expiry("2026-08-01", label="The secret", today=TODAY)
    assert status.severity == "error"
    assert status.expired is True
    assert "Nothing is lost" in status.message


def test_an_unreadable_date_says_so_rather_than_going_quiet():
    """Recorded-but-unparseable is worse than blank: the town thinks it is
    covered. Absent means "not recorded"; unreadable means "you recorded
    something and it is doing nothing"."""
    status = check_expiry("next tuesday", label="The secret", today=TODAY)
    assert status is not None
    assert status.days_left is None
    assert "not a date" in status.message


@pytest.mark.parametrize("text", [
    "2027-03-04", "04/03/2027", "4 Mar 2027", "Mar 4, 2027",
    "2027-03-04T00:00:00Z",
])
def test_the_formats_an_operator_actually_pastes(text):
    """Entra shows a date; people paste it in their own format, and refusing
    one that is obviously a date to a human is a box nobody fills in twice."""
    assert parse_expiry(text) == date(2027, 3, 4)


def test_a_saved_expiry_reaches_the_operator():
    """Wired, not merely written: the save path turns it into a finding."""
    checks = pytest.importorskip("app.services.credential_checks")
    findings = checks.inspect_settings(
        {"AZURE_KEYVAULT_CLIENT_SECRET_EXPIRES": "2020-01-01"})
    assert any(f.key == "AZURE_KEYVAULT_CLIENT_SECRET_EXPIRES"
               and f.severity == checks.SEVERITY_ERROR for f in findings)
