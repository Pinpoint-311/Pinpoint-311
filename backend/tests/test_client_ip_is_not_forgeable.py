"""Who a request is FROM, and why the obvious answer is the wrong one.

Every deployment runs behind Caddy on a compose network. `request.client.host`
is therefore Caddy's container address -- one value for the whole town -- and
three places read the FIRST entry of X-Forwarded-For instead:

  * app/main.py `_client_ip`, which stamps the admin audit trail,
  * app/api/research.py `client_info`, the research access log,
  * app/api/system.py, the disclaimer acknowledgment kept "for legal
    protection".

Caddy APPENDS to whatever X-Forwarded-For the client sent, and no
`trusted_proxies` is configured. So `curl -H 'X-Forwarded-For: 8.8.8.8'` put
8.8.8.8 in the first position and every one of those records believed it. An
audit trail whose contents the subject chooses is worse than none, because it is
trusted.

The same header is now the rate-limit key, which raises the stakes: a forgeable
key is an unlimited supply of fresh buckets, so "trust the first entry" would
have quietly removed the rate limiting it was added to fix.

The rule under test (app/core/client_ip.py): believe the header only from a
trusted peer, and then only the entry the trusted hop itself wrote -- the LAST
one -- never the entries in front of it that the client supplied.

These tests are pure functions over strings; no app, no database, no network.
"""

import pytest

# Guard on a submodule, never a bare package name: CI installs only
# cryptography, httpx, pytest, pytest-asyncio and alembic, and a bare guard on a
# name that resolves as a namespace package passes silently and takes the whole
# file with it. See the header of tests/test_migrate.py.
pytest.importorskip("fastapi.routing")

from app.core.client_ip import (
    DEFAULT_TRUSTED_PROXY_CIDRS,
    client_ip,
    is_trusted_proxy,
    rate_limit_key,
    resolve_client_ip,
)


CADDY = "172.19.0.5"       # a proxy on the compose network
RESIDENT = "203.0.113.7"   # the address Caddy observed
FORGED = "8.8.8.8"         # what the caller asked to be recorded as


class _Headers(dict):
    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)


class _Client:
    def __init__(self, host):
        self.host = host


class _Request:
    """The two attributes the resolver touches."""

    def __init__(self, peer, forwarded=None):
        self.client = _Client(peer) if peer else None
        self.headers = _Headers()
        if forwarded is not None:
            self.headers["x-forwarded-for"] = forwarded


# ---------------------------------------------------------------------------
# the forgery this exists to stop
# ---------------------------------------------------------------------------


def test_a_client_cannot_choose_the_address_that_gets_recorded():
    """The exact reproduction: caller sends 8.8.8.8, Caddy appends the truth."""
    resolved = resolve_client_ip(CADDY, f"{FORGED}, {RESIDENT}")
    assert resolved == RESIDENT
    assert resolved != FORGED


def test_a_whole_chain_of_forged_hops_is_still_ignored():
    """Padding the header does not push the real address out of reach."""
    forged_chain = ", ".join(["8.8.8.8", "1.1.1.1", "9.9.9.9", "10.0.0.1"])
    assert resolve_client_ip(CADDY, f"{forged_chain}, {RESIDENT}") == RESIDENT


def test_each_forged_header_does_not_mint_a_fresh_rate_limit_bucket():
    """The rate-limit key is the property that matters for throttling.

    One attacker rotating the forged prefix must land in ONE bucket. Each
    header below is what Caddy actually forwards: the client's chosen value
    with the observed address appended. If any of them resolved differently the
    limiter would hand that attacker a fresh budget per request, which is the
    whole reason "trust the first entry" is not an acceptable fix.
    """
    keys = {
        rate_limit_key(_Request(CADDY, f"{forged}, {RESIDENT}"))
        for forged in ("8.8.8.8", "1.1.1.1", "203.0.113.9", "junk", "")
    }
    assert keys == {RESIDENT}, keys


def test_two_residents_behind_the_proxy_get_different_buckets():
    """The other half: correct keying must still separate real callers.

    This is the bug the fix is *for* -- one script must not spend the whole
    town's report-submission budget.
    """
    a = rate_limit_key(_Request(CADDY, f"{RESIDENT}"))
    b = rate_limit_key(_Request(CADDY, "203.0.113.99"))
    assert a != b
    assert (a, b) == (RESIDENT, "203.0.113.99")


# ---------------------------------------------------------------------------
# trust boundary
# ---------------------------------------------------------------------------


def test_an_untrusted_peer_is_not_believed_at_all():
    """A direct connection's header is unverifiable hearsay, so it is dropped."""
    assert resolve_client_ip("198.51.100.4", f"{FORGED}, {RESIDENT}") == "198.51.100.4"


def test_the_compose_network_and_loopback_are_the_trusted_set():
    assert is_trusted_proxy("172.19.0.5")
    assert is_trusted_proxy("127.0.0.1")
    assert is_trusted_proxy("10.1.2.3")
    assert is_trusted_proxy("::1")
    assert not is_trusted_proxy("8.8.8.8")
    assert not is_trusted_proxy("203.0.113.7")
    assert not is_trusted_proxy(None)
    assert not is_trusted_proxy("not-an-address")


def test_the_trusted_set_can_be_narrowed_and_emptied(monkeypatch):
    """A deployment that publishes the port straight to the internet can opt out.

    With nothing trusted, every caller is their peer address: per-resident
    keying is forfeited rather than accepting a forgeable one.
    """
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "")
    assert resolve_client_ip(CADDY, f"{FORGED}, {RESIDENT}") == CADDY


def test_a_second_proxy_hop_is_configurable(monkeypatch):
    """Two trusted hops means the address is two from the right, not one."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    assert resolve_client_ip(CADDY, f"{FORGED}, {RESIDENT}, {CADDY}") == RESIDENT


def test_a_header_shorter_than_the_configured_hops_is_refused(monkeypatch):
    """Fail closed: an unexpected chain is unattributable, not a free promotion."""
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "3")
    assert resolve_client_ip(CADDY, f"{FORGED}") == CADDY


# ---------------------------------------------------------------------------
# shapes real proxies emit, and junk attackers emit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header,expected",
    [
        (f"  {RESIDENT}  ", RESIDENT),
        (f"{RESIDENT}:51234", RESIDENT),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("2001:db8::1", "2001:db8::1"),
        ("fe80::1%eth0", "fe80::1"),
    ],
)
def test_addresses_are_normalised(header, expected):
    assert resolve_client_ip(CADDY, header) == expected


@pytest.mark.parametrize("junk", ["unknown", "_hidden", "example.com", "", "   ", ","])
def test_non_addresses_never_reach_an_audit_column(junk):
    """A hostname or an obfuscated identifier is not an address.

    Dropped rather than propagated: these columns are read as addresses by
    whoever is investigating, and a string an attacker chose is not one.
    """
    assert resolve_client_ip(CADDY, junk) == CADDY


def test_a_missing_header_falls_back_to_the_peer():
    assert resolve_client_ip(CADDY, None) == CADDY


def test_a_request_object_resolves_the_same_way():
    assert client_ip(_Request(CADDY, f"{FORGED}, {RESIDENT}")) == RESIDENT
    assert client_ip(_Request(None)) is None


def test_the_rate_limit_key_is_never_empty():
    """slowapi silently SKIPS a limit whose key is falsy.

    An unresolvable caller has to share a bucket; landing in no bucket at all
    would mean no limit at all, which is the bug this file exists under.
    """
    assert rate_limit_key(_Request(None)) == "unknown-client"
    assert rate_limit_key(_Request(CADDY)) == CADDY


def test_the_key_function_parameter_is_still_named_request():
    """slowapi passes the Request only if the parameter is literally `request`.

    `__evaluate_limits` does `if "request" in inspect.signature(key_func)
    .parameters` and otherwise calls `key_func()` with no arguments. Rename the
    parameter and every limit in the app starts raising TypeError inside
    slowapi, which swallows it into a 500-shaped path rather than a 429 -- a
    silent, total loss of rate limiting. Verified by reproduction against the
    installed slowapi 0.1.9.
    """
    import inspect

    for fn in (client_ip, rate_limit_key):
        assert "request" in inspect.signature(fn).parameters, fn.__name__


def test_the_default_trusted_set_contains_no_public_range():
    """The stated assumption, asserted rather than left in a comment.

    Trusting a publicly routable range would let anyone on the internet forge
    the header directly.
    """
    import ipaddress

    for chunk in DEFAULT_TRUSTED_PROXY_CIDRS.split(","):
        network = ipaddress.ip_network(chunk.strip())
        assert network.is_private or network.is_loopback or network.is_link_local, chunk
