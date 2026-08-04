"""No endpoint hands out an admin session to whoever asks.

`GET /api/auth/demo-login` did. It looked up the first active admin, minted a
JWT for that account, and returned a page whose inline script wrote the token to
localStorage and redirected to /staff. No password, no SSO, no one-time link --
the account with the highest privileges in the system, to any caller.

The one thing standing in the way was `if not settings.demo_mode: 404`. That
gate was correctly written and it still was not enough, because its input was an
environment variable. `DEMO_MODE: "true"` was sitting in a compose file in this
repository, and a town copying the wrong file, an operator reusing a demo `.env`,
or a provisioning template inheriting one line would have published anonymous
admin access with nothing else to stop it. A single flag was the entire defence,
and it defended a feature nobody needed in production.

So the endpoint is gone rather than better-gated, and demo mode along with it.

Two things are asserted here, because deleting code is not what makes it stay
deleted:

  * nothing reintroduces a demo flag. A route path or a setting named for demo
    mode is the shape the old endpoint arrived in.
  * every handler that mints a token names the secret its caller has to present.
    This is the part that generalises: the risk was never the word "demo", it
    was a token-minting endpoint that asked for nothing. A new one has to be
    added to the inventory below, which is the moment someone has to write down
    what it checks -- and if the answer is "nothing", it is visible in review
    instead of in production.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "backend/app/api"
APP = ROOT / "backend/app"

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# Handler -> the secret its caller must present before a token is issued.
# Adding an entry is a deliberate act; every value here has to be something an
# anonymous caller cannot guess.
TOKEN_MINTERS = {
    "verify_bootstrap": "the deploy-time INITIAL_ADMIN_PASSWORD, and only while no IdP is configured",
    "use_bootstrap_token": "a one-time bootstrap token, and only while no IdP is configured",
    "auth0_callback": "an authorization code the IdP issued for this state",
    "redeem_onboarding_token": "a signed onboarding token",
    "bootstrap_township": "the orchestrator's provisioning token",
    "exchange_break_glass": "a panel-signed break-glass token, in managed mode only",
}


def _handlers():
    """(file, path, function) for every route handler under app/api."""
    for py in sorted(API.glob("*.py")):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                if dec.func.attr not in HTTP_METHODS:
                    continue
                route = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else "?"
                yield py.name, route, node


def test_no_route_is_named_for_demo_mode():
    for filename, route, fn in _handlers():
        assert "demo" not in route.lower(), (
            f"{filename}:{fn.lineno} serves {route}. demo-login was deleted because a "
            f"credential-free admin session guarded by one env var is not defensible. "
            f"If this route needs to exist, it needs an authentication check, not a flag."
        )


def test_no_demo_flag_is_read_anywhere():
    """The setting and the env var both go, so a stray DEMO_MODE=true is inert."""
    offenders = []
    for py in sorted(APP.rglob("*.py")):
        for lineno, line in enumerate(py.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # prose about the removal is fine; reading the flag is not
            if "DEMO_MODE" in line or "demo_mode" in line:
                offenders.append(f"{py.relative_to(ROOT)}:{lineno}: {stripped}")
    assert not offenders, (
        "demo mode is back as a flag:\n  " + "\n  ".join(offenders)
        + "\nA deployment must not be able to unlock a login path with an env var."
    )


def test_every_token_minting_handler_requires_a_secret():
    found = {}
    for filename, route, fn in _handlers():
        mints = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "create_access_token"
            for n in ast.walk(fn)
        )
        if mints:
            found[fn.name] = f"{filename}:{fn.lineno} {route}"

    new = sorted(set(found) - set(TOKEN_MINTERS))
    assert not new, (
        "a new endpoint issues a session token: "
        + ", ".join(f"{n} ({found[n]})" for n in new)
        + ".\nAdd it to TOKEN_MINTERS naming the secret its caller must present. "
        "If it does not require one, it is demo-login again and must not ship."
    )

    gone = sorted(set(TOKEN_MINTERS) - set(found))
    assert not gone, (
        f"TOKEN_MINTERS lists handlers that no longer mint tokens: {gone}. "
        "Drop them, so the inventory keeps meaning something."
    )
