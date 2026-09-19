"""One answer to "which address is this call actually coming from".

Every deployment runs behind Caddy on a compose network, so
``request.client.host`` is Caddy's container address -- 172.19.0.x, identical
for every resident in town. Reading it directly is what made the rate limits
one town-wide bucket (one script filing reports blocked the whole town) and
what made the audit trail useless (every admin action recorded the same IP).

The obvious fix -- "take the first entry of X-Forwarded-For" -- is worse than
the bug. Caddy *appends* to whatever header the client sent, and no
``trusted_proxies`` is configured, so a client sending
``X-Forwarded-For: 8.8.8.8`` puts 8.8.8.8 in the leftmost position. Trusting
that entry lets an attacker write any address they like into admin audit rows
and mint a fresh, unlimited rate-limit bucket per forged address.

So this module resolves the caller the only way that is sound:

  * If the immediate peer is NOT a trusted proxy, the connection is direct and
    X-Forwarded-For is unverifiable hearsay. It is ignored entirely and the
    peer address is the caller.
  * If the peer IS a trusted proxy, then the rightmost entries of
    X-Forwarded-For were written by proxies we trust. With one proxy in front
    (the default), the LAST entry is the address Caddy itself observed -- the
    real client -- and everything to its left is client-supplied and ignored.

THE ASSUMPTION, stated plainly: the trusted set below must contain only
addresses that cannot be reached directly by an untrusted client. The default
set is loopback plus the RFC1918/ULA ranges the compose network lives in, which
holds as long as the container port is not published straight onto the public
internet. A deployment that fronts the app with something else sets:

  TRUSTED_PROXY_CIDRS  comma-separated CIDRs (or bare addresses) to trust
  TRUSTED_PROXY_HOPS   how many trusted proxies append a hop (default 1)

Set TRUSTED_PROXY_CIDRS to an empty string to trust nothing, which makes every
caller their peer address and forfeits per-resident keying rather than
accepting a forgeable one.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

# Loopback, RFC1918, and the IPv6 unique-local range. These are where a reverse
# proxy on the same host or the same docker network lives; none of them is
# routable from the public internet.
DEFAULT_TRUSTED_PROXY_CIDRS = (
    "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
)

# Caddy is the single hop in front of the app.
DEFAULT_TRUSTED_PROXY_HOPS = 1

# An address written into an audit column; the columns are sized for one.
_MAX_LEN = 64


def _parse_address(value: str) -> Optional[ipaddress._BaseAddress]:
    """An IP address from one X-Forwarded-For element, or None if it isn't one.

    Handles the shapes proxies actually emit: a bare address, a bracketed IPv6
    literal, an ``addr:port`` pair, and a zone-suffixed IPv6 address. Anything
    else -- an obfuscated identifier, "unknown", a hostname, a junk string an
    attacker pushed in -- is not an address and is dropped rather than
    propagated into an audit row.
    """
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("["):
        # [2001:db8::1]:443
        closing = text.find("]")
        if closing == -1:
            return None
        text = text[1:closing]
    elif text.count(":") == 1:
        # IPv4:port. A bare IPv6 address has more than one colon, so this
        # cannot strip a real address's tail.
        text = text.split(":", 1)[0]
    text = text.split("%", 1)[0]  # fe80::1%eth0
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _parse_networks(raw: str) -> List[ipaddress._BaseNetwork]:
    networks: List[ipaddress._BaseNetwork] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            networks.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            logger.warning("ignoring unparseable TRUSTED_PROXY_CIDRS entry: %r", chunk)
    return networks


def trusted_proxy_networks() -> Sequence[ipaddress._BaseNetwork]:
    """The networks whose X-Forwarded-For header is believed.

    Read from the environment on every call rather than cached at import: this
    is not hot enough to matter (a handful of CIDRs, parsed per request) and a
    cache would make the setting untestable and un-reloadable.
    """
    raw = os.environ.get("TRUSTED_PROXY_CIDRS")
    if raw is None:
        raw = DEFAULT_TRUSTED_PROXY_CIDRS
    return _parse_networks(raw)


def trusted_proxy_hops() -> int:
    """How many trusted proxies append to X-Forwarded-For. At least one."""
    raw = os.environ.get("TRUSTED_PROXY_HOPS")
    if not raw:
        return DEFAULT_TRUSTED_PROXY_HOPS
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("TRUSTED_PROXY_HOPS is not a number: %r", raw)
        return DEFAULT_TRUSTED_PROXY_HOPS


def is_trusted_proxy(address: Optional[str]) -> bool:
    """Whether a connection from this address may speak for someone else."""
    parsed = _parse_address(address or "")
    if parsed is None:
        return False
    return any(parsed in network for network in trusted_proxy_networks())


def resolve_client_ip(
    peer: Optional[str], forwarded_for: Optional[str]
) -> Optional[str]:
    """The caller's address, given the socket peer and the raw header.

    Split out from `client_ip` so the rule can be tested without conjuring a
    Request, and so the two callers that already had a Request-free shape can
    use it.
    """
    peer_address = _parse_address(peer or "")
    peer_text = str(peer_address) if peer_address is not None else None

    if peer_address is None or not is_trusted_proxy(peer):
        # Direct connection (or an unparseable peer). Nothing has vouched for
        # the header, so it says nothing.
        return peer_text

    entries = [
        parsed
        for parsed in (_parse_address(part) for part in (forwarded_for or "").split(","))
        if parsed is not None
    ]
    if not entries:
        # Trusted proxy that forwarded no header. Its own address is the only
        # thing we know.
        return peer_text

    index = len(entries) - trusted_proxy_hops()
    if index < 0:
        # Fewer hops recorded than there are trusted proxies in front of us:
        # the header did not come through the path we were told to expect, so
        # every entry in it is unattributable. Fail closed to the peer rather
        # than promote a client-supplied value.
        logger.warning(
            "X-Forwarded-For has %d entries but %d trusted hops are configured; "
            "ignoring the header",
            len(entries),
            trusted_proxy_hops(),
        )
        return peer_text

    return str(entries[index])[:_MAX_LEN]


def client_ip(request) -> Optional[str]:
    """The caller's address for a Starlette/FastAPI request.

    The parameter is named `request` on purpose and must stay that way: slowapi
    inspects a key function's signature and passes the Request only when the
    parameter carries that exact name (slowapi/extension.py __evaluate_limits).
    Rename it and every limit silently starts keying on a TypeError.
    """
    peer = request.client.host if getattr(request, "client", None) else None
    return resolve_client_ip(peer, request.headers.get("X-Forwarded-For"))


def rate_limit_key(request) -> str:
    """slowapi key function: the caller's address, never empty.

    slowapi skips a limit whose key is falsy ("Skipping limit ... Empty value
    found in parameters"), so an unresolvable caller must land in a shared
    bucket rather than in no bucket at all.
    """
    return client_ip(request) or "unknown-client"
