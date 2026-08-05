""""Connected" has to mean the credentials were accepted.

Only the Accela connector authenticated. The other three probed endpoints that
answer anonymous requests -- `/services.json` on an Open311 server, the public
`/issues` feed on SeeClickFix, a generic vendor's list endpoint with auth headers
attached only if a key happened to be saved. So an integration with every
credential field blank, or a mistyped password, or an expired CivicPlus token,
all came back green and said "Connected".

That is worse than no check. A clerk who presses the button and sees "Connected"
stops looking, and the next thing to discover otherwise is a resident whose
report never reached the county.

Where a platform does have an endpoint a bad credential fails, these now hit it.
Where one genuinely does not -- GeoReport v2 has no authenticated read at all --
the result says so rather than implying otherwise.
"""

import httpx
import pytest

import app.integrations.base as base
from app.integrations.registry import build_connector


@pytest.fixture
def vendor(monkeypatch):
    """Serve scripted responses to whatever the connector requests.

    Returns the recorded request list so a test can assert on what was actually
    sent -- which is the whole question here: was a credential on the wire.
    """
    monkeypatch.setattr(base, "_assert_public_url", lambda url: None)
    seen = []

    def serve(handler):
        async def transport(self, request):
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(base.httpx.AsyncHTTPTransport,
                            "handle_async_request", transport)
        return seen

    return serve


def json_ok(payload):
    return lambda request: httpx.Response(200, json=payload, request=request)


# ---------------------------------------------------------------------------
# Open311: no authenticated endpoint exists, so say that
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open311_reports_that_it_could_not_check_the_key(vendor):
    """GeoReport v2's only authenticated operation is the POST that files a
    record, and a connection check must not file one. So the honest answer is
    "reachable, key unexercised" -- not "Connected"."""
    vendor(json_ok([{"service_code": "1"}, {"service_code": "2"}]))
    conn = build_connector("open311", {"base_url": "https://city.test/open311/v2"},
                           {"api_key": "k"})
    result = await conn.test_connection()
    assert result["ok"] is True
    assert result["verified"] is False
    assert "2 service type(s)" in result["detail"]
    assert "only exercised on the first push" in result["detail"]


@pytest.mark.asyncio
async def test_open311_with_no_key_warns_that_pushes_will_be_refused(vendor):
    """A blank api_key used to be indistinguishable from a working one."""
    vendor(json_ok([]))
    conn = build_connector("open311", {"base_url": "https://city.test/open311/v2"}, {})
    result = await conn.test_connection()
    assert result["verified"] is False
    assert "No API key is saved" in result["detail"]


@pytest.mark.asyncio
async def test_open311_still_fails_loudly_on_a_bad_address(vendor):
    """The check is weaker about credentials, not about everything. A typo'd
    base URL is the most common setup mistake and must still surface."""
    vendor(lambda request: httpx.Response(404, text="no such endpoint", request=request))
    conn = build_connector("open311", {"base_url": "https://city.test/wrong"}, {})
    with pytest.raises(base.ConnectorError):
        await conn.test_connection()


@pytest.mark.asyncio
async def test_tyler_inherits_the_same_honesty(vendor):
    """Tyler is an Open311 endpoint behind a vendor name; it cannot verify a key
    any better than the standard it speaks."""
    vendor(json_ok([]))
    conn = build_connector("tyler", {"base_url": "https://town.tylerapp.com/open311/v2"},
                           {"api_key": "k"})
    assert (await conn.test_connection())["verified"] is False


# ---------------------------------------------------------------------------
# SeeClickFix: /profile is the call a bad credential fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seeclickfix_signs_in_rather_than_reading_the_public_feed(vendor):
    seen = vendor(json_ok({"name": "Springfield DPW"}))
    conn = build_connector("civicplus", {"place_url": "springfield"},
                           {"api_key": "token"})
    result = await conn.test_connection()

    assert result["verified"] is True
    assert "Springfield DPW" in result["detail"]
    assert str(seen[-1].url).endswith("/profile"), "probed the public feed again"
    assert seen[-1].headers["Authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_seeclickfix_rejects_a_bad_password(vendor):
    """The case that used to return "Connected": credentials that the vendor
    does not accept. `/issues` never looked at them."""
    vendor(lambda request: httpx.Response(401, text="unauthorized", request=request))
    conn = build_connector("civicplus", {}, {"username": "clerk", "password": "wrong"})
    with pytest.raises(base.ConnectorError):
        await conn.test_connection()


@pytest.mark.asyncio
async def test_seeclickfix_with_no_credentials_says_so(vendor):
    seen = vendor(json_ok({"issues": []}))
    conn = build_connector("civicplus", {}, {})
    result = await conn.test_connection()

    assert result["verified"] is False
    assert "no sign-in details are saved" in result["detail"]
    # Reachability is still worth confirming, so a mistyped api_base is caught.
    assert "/issues" in str(seen[-1].url)


# ---------------------------------------------------------------------------
# generic_rest: did we actually send anything?
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generic_rest_confirms_the_key_was_sent_and_accepted(vendor):
    seen = vendor(json_ok([]))
    conn = build_connector("generic_rest", {"base_url": "https://api.test/v1"},
                           {"api_key": "k"})
    result = await conn.test_connection()

    assert result["verified"] is True
    assert seen[-1].headers["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_generic_rest_admits_when_no_credential_was_sent(vendor):
    """`_request_kwargs` attaches auth only when the credential exists, so a
    blank save sends a plain anonymous GET. A vendor that allows anonymous reads
    then answers 200 and the old check called that success."""
    seen = vendor(json_ok([]))
    conn = build_connector("generic_rest", {"base_url": "https://api.test/v1"}, {})
    result = await conn.test_connection()

    assert result["ok"] is True and result["verified"] is False
    assert "no credentials are saved" in result["detail"]
    assert "Authorization" not in seen[-1].headers


@pytest.mark.asyncio
async def test_generic_rest_basic_auth_counts_as_a_credential(vendor):
    vendor(json_ok([]))
    conn = build_connector("generic_rest",
                           {"base_url": "https://api.test/v1", "auth_style": "basic"},
                           {"username": "clerk", "password": "pw"})
    assert (await conn.test_connection())["verified"] is True


@pytest.mark.asyncio
async def test_generic_rest_basic_auth_with_no_username_is_unverified(vendor):
    """An api_key saved against auth_style=basic is never sent, so claiming it
    was verified would be claiming something that did not happen."""
    vendor(json_ok([]))
    conn = build_connector("generic_rest",
                           {"base_url": "https://api.test/v1", "auth_style": "basic"},
                           {"api_key": "unused-here"})
    assert (await conn.test_connection())["verified"] is False


# ---------------------------------------------------------------------------
# Accela already authenticated; the field is stated so the UI can rely on it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accela_states_that_it_verified(vendor):
    def handler(request):
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json={"access_token": "t"}, request=request)
        return httpx.Response(200, json={"result": []}, request=request)

    vendor(handler)
    conn = build_connector(
        "accela", {"agency_name": "SPRINGFIELD", "record_type": "SR/General/Complaint/NA"},
        {"client_id": "i", "client_secret": "s", "username": "u", "password": "p"})
    result = await conn.test_connection()
    assert result["ok"] is True and result["verified"] is True


@pytest.mark.asyncio
async def test_every_connector_answers_the_verified_question(vendor):
    """The UI branches on `verified`, so a connector that omits it would fall
    back to whatever the default rendering is -- which is how "Connected" got
    shown for an unverified connection in the first place."""
    vendor(json_ok([]))
    for platform, config, creds in (
        ("open311", {"base_url": "https://c.test/v2"}, {"api_key": "k"}),
        ("tyler", {"base_url": "https://c.test/v2"}, {"api_key": "k"}),
        ("civicplus", {}, {}),
        ("generic_rest", {"base_url": "https://api.test/v1"}, {"api_key": "k"}),
    ):
        result = await build_connector(platform, config, creds).test_connection()
        assert "verified" in result, platform
