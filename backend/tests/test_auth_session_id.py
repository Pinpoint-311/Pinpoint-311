"""Session identity in access tokens.

The audit log stores a session id on every login and logout so a reviewer can
follow one session across events. That only works if the token actually carries
an id -- before this, `create_access_token` never set `jti`, the login path
decoded the token it had just signed looking for one, found nothing, and wrote
session_id="unknown" on every single login. The audit column existed and was
uniformly useless.
"""

import pytest

pytest.importorskip("jwt")
auth = pytest.importorskip("app.core.auth")

import jwt as jwt_lib


def _claims(token: str) -> dict:
    return jwt_lib.decode(token, options={"verify_signature": False})


def test_token_always_carries_a_session_id():
    claims = _claims(auth.create_access_token({"sub": "clerk"}))
    assert claims.get("jti")


def test_session_ids_are_unique_per_token():
    """Two logins must be distinguishable in the audit trail."""
    a = _claims(auth.create_access_token({"sub": "clerk"}))["jti"]
    b = _claims(auth.create_access_token({"sub": "clerk"}))["jti"]
    assert a != b


def test_session_id_is_not_guessable():
    """It identifies a session in an audit record; a counter would leak volume
    and invite forgery of plausible ids."""
    jti = _claims(auth.create_access_token({"sub": "clerk"}))["jti"]
    assert len(jti) >= 32
    int(jti, 16)  # hex


def test_caller_supplied_session_id_is_preserved():
    """The login path mints the id first so it can log it without decoding the
    token back apart; provisioning threads through an existing jti."""
    token = auth.create_access_token({"sub": "ops", "jti": "abc123"})
    assert _claims(token)["jti"] == "abc123"


def test_other_claims_survive():
    claims = _claims(auth.create_access_token({"sub": "clerk", "role": "staff"}))
    assert claims["sub"] == "clerk"
    assert claims["role"] == "staff"
    assert "exp" in claims


def test_token_still_verifies_against_the_signing_key():
    """Adding a claim must not break decoding."""
    token = auth.create_access_token({"sub": "clerk", "role": "admin"})
    assert auth.decode_token(token)["role"] == "admin"
