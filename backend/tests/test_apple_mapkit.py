"""Tests for the Apple MapKit token.

Apple is the only map provider that cannot use a static key. MapKit JS wants an
ES256-signed JWT, and the .p8 that signs it grants map access for the whole
developer team, is downloadable exactly once, and must never reach a browser.

The two things worth pinning hardest: the key stays server-side, and a broken
configuration degrades to "not configured" rather than 500ing an endpoint that
every page load calls.
"""

import time

import pytest

am = pytest.importorskip("app.services.apple_mapkit")
# apple_mapkit imports PyJWT lazily inside the signing call, so the module-level
# guard above passes without it and the tests would fail at call time instead.
pytest.importorskip("jwt")

# ES256 needs a real EC key; without cryptography installed there is nothing to
# sign with and the signing tests cannot run.
crypto = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402


@pytest.fixture(scope="module")
def p8_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture(autouse=True)
def _clear():
    am.clear_cache()
    yield
    am.clear_cache()


# ---- claims ----------------------------------------------------------------

def test_claims_carry_the_team_and_an_expiry():
    claims = am.build_claims("TEAM123456", now=1_000_000)
    assert claims["iss"] == "TEAM123456"
    assert claims["iat"] == 1_000_000
    assert claims["exp"] == 1_000_000 + am.TOKEN_TTL_SECONDS


def test_tokens_are_short_lived():
    """Apple permits up to a year. A leaked short token expires on its own, and
    re-minting costs one cheap request."""
    assert am.TOKEN_TTL_SECONDS <= 60 * 60


def test_no_origin_claim_is_pinned():
    """`origin` ties a token to one hostname, and a self-hosted deployment
    behind Caddy or a town's CDN cannot reliably know its own public host.
    Betting map loading on that is worse than a short expiry."""
    assert "origin" not in am.build_claims("TEAM123456")


# ---- surviving however the .p8 was pasted ----------------------------------

@pytest.mark.parametrize("mangle", [
    lambda k: k.replace("\n", "\\n"),          # pasted through a form or env var
    lambda k: k.replace("\n", "\r\n"),          # Windows line endings
    lambda k: k.replace("\n", ""),              # newlines stripped entirely
    lambda k: "  " + k + "\n\n",                # stray whitespace
    lambda k: "\n".join("  " + ln for ln in k.split("\n")),  # indented paste
])
def test_any_reasonable_paste_of_a_p8_still_signs(p8_key, mangle):
    """Signing fails cryptically on all of these, and a clerk has no way to
    debug whitespace. Every form must canonicalise to the same working key."""
    repaired = am.normalize_private_key(mangle(p8_key))
    assert repaired == am.normalize_private_key(p8_key)
    assert am.sign_token("TEAM123456", "KEY1234567", repaired)


def test_normalizing_is_idempotent(p8_key):
    once = am.normalize_private_key(p8_key)
    assert am.normalize_private_key(once) == once


def test_empty_key_normalizes_to_empty():
    assert am.normalize_private_key("") == ""
    assert am.normalize_private_key(None) == ""


# ---- signing ---------------------------------------------------------------

def test_a_signed_token_carries_the_key_id_in_its_header(p8_key):
    """MapKit looks up which key to verify with from the `kid` header."""
    import jwt as jwt_lib

    token = am.sign_token("TEAM123456", "KEY1234567", p8_key)
    assert jwt_lib.get_unverified_header(token)["kid"] == "KEY1234567"
    assert jwt_lib.get_unverified_header(token)["alg"] == "ES256"


def test_signing_without_a_key_raises_rather_than_producing_junk(p8_key):
    with pytest.raises(ValueError):
        am.sign_token("TEAM123456", "KEY1234567", "")
    with pytest.raises(ValueError):
        am.sign_token("", "KEY1234567", p8_key)
    with pytest.raises(ValueError):
        am.sign_token("TEAM123456", "", p8_key)


# ---- fetching --------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_token_is_minted_when_everything_is_configured(p8_key):
    async def secrets(name):
        return {am.TEAM_ID_KEY: "TEAM123456", am.KEY_ID_KEY: "KEY1234567",
                am.PRIVATE_KEY_KEY: p8_key}[name]

    assert await am.get_token(secrets)


@pytest.mark.asyncio
async def test_an_unconfigured_town_gets_none_not_an_exception():
    """Apple simply not being set up is the normal case for almost every town.
    It must not 500 an endpoint every page load calls."""
    async def secrets(name):
        return None

    assert await am.get_token(secrets) is None


@pytest.mark.asyncio
async def test_a_malformed_key_gets_none_not_an_exception():
    """Usually a truncated paste or an RSA key where an EC key was needed. The
    admin console should say "not configured", not show a stack trace."""
    async def secrets(name):
        return {am.TEAM_ID_KEY: "TEAM123456", am.KEY_ID_KEY: "KEY1234567",
                am.PRIVATE_KEY_KEY: "-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----"}[name]

    assert await am.get_token(secrets) is None


@pytest.mark.asyncio
async def test_an_unreachable_secret_store_gets_none_not_an_exception():
    async def secrets(name):
        raise RuntimeError("secret manager down")

    assert await am.get_token(secrets) is None


@pytest.mark.asyncio
async def test_the_token_is_cached_between_calls(p8_key):
    """Signing is cheap, but reading a .p8 out of a cloud Secret Manager is a
    network round trip on every page load that shows a map."""
    calls = []

    async def secrets(name):
        calls.append(name)
        return {am.TEAM_ID_KEY: "TEAM123456", am.KEY_ID_KEY: "KEY1234567",
                am.PRIVATE_KEY_KEY: p8_key}[name]

    first = await am.get_token(secrets)
    reads = len(calls)
    second = await am.get_token(secrets)

    assert first == second
    assert len(calls) == reads, "cached token should not re-read the private key"


@pytest.mark.asyncio
async def test_clearing_the_cache_forces_a_re_mint(p8_key):
    """Rotating the key must take effect without a restart."""
    async def secrets(name):
        return {am.TEAM_ID_KEY: "TEAM123456", am.KEY_ID_KEY: "KEY1234567",
                am.PRIVATE_KEY_KEY: p8_key}[name]

    await am.get_token(secrets)
    am.clear_cache()
    assert await am.get_token(secrets)


@pytest.mark.asyncio
async def test_a_nearly_expired_cached_token_is_replaced(p8_key, monkeypatch):
    """Re-mint early so a token never expires mid-page-load."""
    async def secrets(name):
        return {am.TEAM_ID_KEY: "TEAM123456", am.KEY_ID_KEY: "KEY1234567",
                am.PRIVATE_KEY_KEY: p8_key}[name]

    await am.get_token(secrets)
    # Pretend we are inside the refresh margin.
    monkeypatch.setattr(am, "_cache", ("stale-token", time.time() + am.REFRESH_MARGIN_SECONDS - 1))
    assert await am.get_token(secrets) != "stale-token"
