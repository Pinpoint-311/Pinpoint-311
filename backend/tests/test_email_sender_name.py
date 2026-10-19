"""A sender name with a comma still produces one, correct sender address.

Unquoted, "Springfield, IL Pilot <x@y>" is two addresses to an email parser, and
smtplib sent MAIL FROM:<Springfield>. Live, every email failed with 501.
"""
from email.utils import getaddresses

import pytest

notifications = pytest.importorskip("app.services.notifications")


def test_a_comma_in_the_sender_name_keeps_the_address(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    provider = notifications.EmailProvider(
        smtp_host="smtp.example.org", smtp_port=587, smtp_user="u", smtp_password="p",
        from_email="pilot@example.org", from_name="Springfield, IL Pilot - Pinpoint 311",
        use_tls=True,
    )

    assert provider.send_email("resident@example.org", "Hello", "<p>Hi</p>") is True
    addresses = getaddresses([sent[0]["From"]])
    assert addresses == [("Springfield, IL Pilot - Pinpoint 311", "pilot@example.org")]
