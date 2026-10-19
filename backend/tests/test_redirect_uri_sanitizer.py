"""The sign-in flow's redirect destination.

Every error branch of the OIDC callback ends in a RedirectResponse built from
the caller-supplied ``redirect_uri``, so this function is the only thing
standing between a crafted sign-in link and a convincing phishing page: the
victim starts on their own town's real sign-in screen and is handed onward.

The cases below are split into the ones that always held and the four that did
not -- urlparse and a browser disagree about what counts as an authority, and
each of those four left ``netloc`` empty so the allowlist check never ran.
"""

import os

import pytest

from app.api.auth import _sanitize_redirect_uri


@pytest.fixture(autouse=True)
def town_origin(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://town.example.gov")


@pytest.mark.parametrize(
    "value",
    [
        "https://town.example.gov/admin",
        "https://town.example.gov",
        "http://localhost:5173/admin",
        "/admin",
        "/",
    ],
)
def test_destinations_on_this_town_are_kept(value):
    assert _sanitize_redirect_uri(value) == value


@pytest.mark.parametrize(
    "value",
    [
        # Plain foreign host: urlparse and the browser agree, and this was
        # always caught.
        "https://evil.example",
        "https://evil.example/sign-in",
        "//evil.example/sign-in",
        # A near-miss on the allowed host. Matching must be exact, not a
        # suffix -- "town.example.gov.evil.example" ends with the real name.
        "https://town.example.gov.evil.example/admin",
        # Scheme with an authority, but not one a page can live at.
        "ftp://evil.example/x",
    ],
)
def test_foreign_hosts_do_not_survive(value):
    assert _sanitize_redirect_uri(value) in ("/", "/sign-in", "/x", "/admin")
    assert "evil.example" not in _sanitize_redirect_uri(value)


@pytest.mark.parametrize(
    "value",
    [
        # Scheme, no authority. urlparse reports netloc='' and path='evil.example';
        # Chrome resolves it to https://evil.example/.
        "https:evil.example",
        # Browsers fold a backslash to a slash inside the authority, so each of
        # these is //evil.example to the thing that actually follows it.
        "/\\evil.example",
        "\\/evil.example",
        "https:/\\evil.example",
        "\\\\evil.example",
    ],
)
def test_the_shapes_urlparse_does_not_see_as_a_host(value):
    result = _sanitize_redirect_uri(value)
    assert "evil.example" not in result, f"{value!r} escaped as {result!r}"
    assert result.startswith("/")
    assert not result.startswith("//")


def test_rejecting_a_host_does_not_hand_back_another_one():
    # The old fallback returned parsed.path, and the path of this URL is
    # "//evil.example/x" -- protocol-relative, so refusing the host produced a
    # redirect to a host anyway.
    assert _sanitize_redirect_uri("https://blocked.example//evil.example/x") == "/"


@pytest.mark.parametrize("value", ["javascript:alert(1)", "data:text/html,<script>", "", "   "])
def test_schemes_that_are_not_pages(value):
    assert _sanitize_redirect_uri(value) == "/"


def test_an_empty_cors_entry_does_not_allow_everything(monkeypatch):
    # "a,,b".split(",") yields "", and urlparse("").netloc is "" -- which is
    # also what netloc is for a relative URI. Letting "" into the allowlist
    # would be harmless there but not if it ever met a parsed empty authority.
    monkeypatch.setenv("CORS_ORIGINS", "https://town.example.gov,,")
    assert _sanitize_redirect_uri("https://evil.example/x") == "/x"
    assert _sanitize_redirect_uri("https://town.example.gov/x") == "https://town.example.gov/x"
