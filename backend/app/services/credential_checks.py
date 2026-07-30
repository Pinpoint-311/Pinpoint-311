"""Catch a wrong credential at the moment it is pasted, not days later.

Two different jobs, with very different confidence levels, kept apart on
purpose.

`inspect_value` checks shape. A Google Maps key starts with AIza and is 39
characters; an Auth0 domain is a hostname, not a URL; an ArcGIS key is a JWT. All
of that is documented, stable and cheap to verify offline, and it catches the
single most common setup mistake: the right value pasted into the wrong field.
Client ID and Client Secret sit next to each other, look alike behind password
dots, and produce an authentication error days later that names neither.

`explain_error` reads a provider's rejection and says what to change. That one is
pattern matching against error strings, and error strings are not a contract --
vendors reword them. So it is strictly additive: it appends a suggestion to the
provider's own message and never replaces it. If the pattern misses, the clerk
still sees exactly what the vendor said, which is what they would have seen
anyway. That asymmetry is the reason this is safe to ship without having
observed every message first-hand.

Nothing here ever blocks a save. A shape rule is a heuristic about someone
else's format, and a vendor is free to change it tomorrow; refusing a credential
that would actually have worked is a worse failure than accepting one that will
not, because the second is discoverable and the first is a dead end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

SEVERITY_ERROR = "error"     # near-certainly wrong; still saved
SEVERITY_WARN = "warn"       # suspicious
SEVERITY_INFO = "info"


@dataclass
class Finding:
    key: str
    severity: str
    message: str


# Shape rules, keyed by the secret name the catalogs already use.
#
# Each entry is (predicate, message). The message says what the value looks like
# it is, when that is knowable, because "this is not a Client ID" is much less
# useful than "this looks like your Domain".
_JWT = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_URLISH = re.compile(r"^https?://", re.I)
_HOSTNAME = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.I)


def _google_maps_key(v: str) -> Optional[str]:
    if not v.startswith("AIza"):
        if _URLISH.match(v):
            return "This is a web address. A Maps key is a long string beginning with “AIza”."
        if _JWT.match(v):
            return "This looks like an ArcGIS key, not a Google one. Google Maps keys begin with “AIza”."
        return "Google Maps keys begin with “AIza”. Check you copied the API key and not the project id."
    if len(v) != 39:
        return (f"Google Maps keys are 39 characters; this is {len(v)}. "
                "It may have been cut off when copying.")
    return None


def _auth0_domain(v: str) -> Optional[str]:
    if _URLISH.match(v):
        return "Enter just the hostname, with no https:// — for example yourorg.us.auth0.com."
    if v.endswith("/"):
        return "Remove the trailing slash."
    if not _HOSTNAME.match(v):
        return "This should be a hostname like yourorg.us.auth0.com."
    return None


def _arcgis_key(v: str) -> Optional[str]:
    if v.startswith("AIza"):
        return "This is a Google Maps key, not an ArcGIS one."
    if not _JWT.match(v):
        return "ArcGIS keys are long tokens in three dot-separated parts. This does not look like one."
    return None


def _issuer_url(v: str) -> Optional[str]:
    if not _URLISH.match(v):
        return "The issuer must be a full web address starting with https://."
    if "/.well-known" in v:
        return ("Enter the issuer itself, without /.well-known/openid-configuration — "
                "that path is added automatically.")
    return None


def _private_key(v: str) -> Optional[str]:
    if "PRIVATE KEY" not in v.upper():
        return ("Paste the whole .p8 file including the "
                "-----BEGIN PRIVATE KEY----- and -----END PRIVATE KEY----- lines.")
    return None


def _service_account_json(v: str) -> Optional[str]:
    import json
    try:
        parsed = json.loads(v)
    except Exception:
        return "This should be the contents of the downloaded .json key file."
    if parsed.get("type") != "service_account":
        return "This JSON is not a service account key."
    if not parsed.get("private_key"):
        return "This service account file has no private_key in it."
    return None


_RULES = {
    "GOOGLE_MAPS_API_KEY": _google_maps_key,
    "AUTH0_DOMAIN": _auth0_domain,
    "ARCGIS_API_KEY": _arcgis_key,
    "OKTA_ISSUER": _issuer_url,
    "OIDC_ISSUER": _issuer_url,
    "APPLE_MAPKIT_PRIVATE_KEY": _private_key,
    "VERTEX_AI_SERVICE_ACCOUNT_KEY": _service_account_json,
}

# Values that are almost certainly a different field's content, checked across
# every key. Catches the Client ID / Client Secret swap regardless of provider.
_WHITESPACE = re.compile(r"\s")


def inspect_value(key: str, value: str) -> Optional[Finding]:
    """One finding for one credential, or None if nothing looks wrong."""
    v = (value or "").strip()
    if not v:
        return None

    rule = _RULES.get(key)
    if rule:
        message = rule(v)
        if message:
            return Finding(key, SEVERITY_ERROR, message)

    # Generic: a secret with spaces in it is nearly always a pasted sentence,
    # a name, or a description that landed in the wrong box. Private keys and
    # JSON legitimately contain whitespace, so they are exempt.
    if _WHITESPACE.search(v) and not any(
        token in key.upper() for token in ("PRIVATE_KEY", "JSON", "KEY_FILE", "ACCOUNT_KEY")
    ):
        return Finding(key, SEVERITY_WARN,
                       "This contains spaces or line breaks, which most credentials do not.")

    return None


def inspect_settings(settings: dict) -> List[Finding]:
    """Every finding across a save, worst first."""
    findings = [f for f in (inspect_value(k, v) for k, v in (settings or {}).items()) if f]
    order = {SEVERITY_ERROR: 0, SEVERITY_WARN: 1, SEVERITY_INFO: 2}
    return sorted(findings, key=lambda f: (order.get(f.severity, 9), f.key))


# --------------------------------------------------------------------------
# interpreting what a provider said
# --------------------------------------------------------------------------

# (pattern, what to actually do). Matched case-insensitively against the
# provider's message. Ordered: the first match wins, so put the specific ones
# first.
#
# Everything here is a suggestion appended to the vendor's own text, never a
# replacement, because these strings are not a contract and vendors reword them.
_HINTS: List[tuple] = [
    (r"api key not valid|invalid api key|API_KEY_INVALID",
     "The key itself was rejected. Check you pasted the whole thing and that it belongs to this project."),
    (r"this api project is not authorized|has not been used in project|is disabled",
     "The key is real but the API is not switched on for it. Enable the service in the provider console, then try again."),
    (r"referer|referrer|not authorized to use this api|requests from this|blocked",
     "The key works but is restricted to other websites. Add this site's address to the key's allowed referrers."),
    (r"billing|BILLING_NOT_ENABLED|account is not active",
     "Billing is not enabled on the account. Most providers refuse to serve even free-tier traffic without a payment method on file."),
    (r"quota|rate ?limit|429|too many requests",
     "You are over the provider's rate limit or quota, not misconfigured. It should recover on its own."),
    (r"access denied|forbidden|403|insufficient|permission|not authorized|unauthorized_client",
     "The credential is valid but lacks a permission this needs. Check the roles or scopes granted to it."),
    (r"401|unauthenticated|invalid_client|invalid client|signature",
     "Authentication failed. Usually the secret is wrong, truncated, or belongs to a different application."),
    (r"sandbox",
     "The account is still in the provider's sandbox, which only allows verified recipients. Request production access."),
    (r"unverified|not verified",
     "The destination address or number has not been verified with the provider yet."),
    (r"could not resolve|name or service not known|dns|getaddrinfo",
     "The address could not be looked up. Check the endpoint for a typo."),
    (r"timeout|timed out",
     "The provider did not answer in time. If it keeps happening the service may be down rather than misconfigured."),
    (r"certificate|ssl|tls",
     "The secure connection failed. This is usually a proxy or a corporate firewall inspecting traffic."),
]


def explain_error(message: str) -> Optional[str]:
    """A plain-language next step for a provider's rejection, or None.

    Returning None is a perfectly good outcome: the caller shows the provider's
    own message, which is what it would have shown anyway.
    """
    if not message:
        return None
    text = str(message)
    for pattern, hint in _HINTS:
        if re.search(pattern, text, re.I):
            return hint
    return None


def describe_failure(message: str) -> str:
    """The provider's message, plus a suggestion when we recognise it.

    The vendor's words always come first and are never edited. A clerk who
    searches the web for their error needs the actual string, and the person
    they escalate to needs to see what the provider really said.
    """
    base = (str(message) if message else "").strip() or "The provider rejected the request."
    hint = explain_error(base)
    return f"{base} — {hint}" if hint else base
