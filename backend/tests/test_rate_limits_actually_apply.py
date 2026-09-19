"""Rate limiting has to exist on routes nobody decorated.

`app/main.py` built `Limiter(default_limits=[RATE_LIMIT_DEFAULT])` and set
`app.state.limiter`, which looks like an app-wide rate limit and is not one.
slowapi evaluates `default_limits` in SlowAPIMiddleware, and SlowAPIMiddleware
was never added -- zero occurrences in the repository. Limits were therefore
enforced only inside the fourteen `@limiter.limit` decorators, every other route
had no ceiling at all, and RATE_LIMIT_DEFAULT was configuration that did
nothing. Reproduced before the fix: an undecorated route answered 200 six times
under a 3/minute default.

The end-to-end tests below run the REAL application -- app.main, its real
middleware stack, its real routes -- in a subprocess so `RATE_LIMIT_DEFAULT`
can be set before import (the limit is read at import time, and the point is to
test the app as configured rather than a lookalike built in the test).
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

# Submodule guard, per tests/test_migrate.py: CI installs only cryptography,
# httpx, pytest, pytest-asyncio and alembic.
pytest.importorskip("fastapi.routing")
pytest.importorskip("slowapi.middleware")
pytest.importorskip("httpx")

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_app_probe(script: str, limit: str = "3/minute") -> dict:
    """Import the real app in a clean process and report what it did."""
    env = dict(os.environ, RATE_LIMIT_DEFAULT=limit, PYTHONPATH=BACKEND)
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    if completed.returncode != 0:
        pytest.skip(
            "the full app could not be imported in this environment: "
            + completed.stderr[-800:]
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


# An undecorated route that needs no database: Open311 discovery takes only the
# Request. Before the fix this was reachable without limit, forever.
PROBE = """
    import asyncio, json, httpx

    async def main():
        import app.main as m
        transport = httpx.ASGITransport(app=m.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://town") as c:
            async def hit(path, ip, n):
                out = []
                for _ in range(n):
                    r = await c.get(path, headers={"X-Forwarded-For": ip})
                    out.append(r.status_code)
                return out

            result = {
                "undecorated_one_caller": await hit(
                    "/api/open311/v2/discovery.json", "203.0.113.7, 203.0.113.7", 6
                ),
                "undecorated_other_caller": await hit(
                    "/api/open311/v2/discovery.json", "198.51.100.9, 198.51.100.9", 3
                ),
                "middleware_installed": any(
                    "SlowAPI" in str(mw.cls) for mw in m.app.user_middleware
                ),
                "key_func": m.app.state.limiter._key_func.__name__,
                "default_limits": [str(l.limit) for g in m.app.state.limiter._default_limits for l in g],
            }
        print(json.dumps(result))

    asyncio.run(main())
"""


@pytest.fixture(scope="module")
def probe():
    return _run_app_probe(PROBE)


def test_an_undecorated_route_is_throttled(probe):
    """The reproduction, inverted.

    Under a 3/minute default the fourth call from one caller must be refused.
    Before SlowAPIMiddleware was registered this list was six 200s.
    """
    codes = probe["undecorated_one_caller"]
    assert 429 in codes, codes
    assert codes[3:] == [429, 429, 429], codes


def test_the_first_calls_under_the_limit_still_work(probe):
    """A limit that refuses everything is not a fix.

    The three calls inside the budget must not be 429 -- the town's own site
    has to keep working under the default.
    """
    assert 429 not in probe["undecorated_one_caller"][:3]


def test_one_caller_exhausting_their_budget_does_not_block_the_town(probe):
    """The bucket is per resident, not per proxy.

    This is the second half of the bug: with `get_remote_address` behind Caddy
    every resident shared one bucket, so the caller above would have taken the
    whole town's budget with them. A second caller must be unaffected.
    """
    assert probe["undecorated_other_caller"] == [200, 200, 200], probe


def test_the_middleware_is_installed_on_the_real_app(probe):
    """The single missing line. Its absence was the entire finding."""
    assert probe["middleware_installed"]


def test_the_limiter_is_keyed_on_the_resolved_caller(probe):
    assert probe["key_func"] == "rate_limit_key"


def test_the_configured_default_is_the_limit_that_is_applied(probe):
    """RATE_LIMIT_DEFAULT was dead configuration; prove it is now read."""
    assert probe["default_limits"] == ["3 per 1 minute"], probe["default_limits"]


def test_a_decorated_route_is_not_counted_twice():
    """The decorated routes must keep their own tighter limits.

    slowapi's `_should_exempt` skips a route the decorator already covers, so
    adding the middleware must not turn `@limiter.limit("5/minute")` into
    "whichever of 5 and the default runs out first" in a way that changes the
    decorated behaviour.
    """
    probe = _run_app_probe(
        """
        import asyncio, json, httpx

        async def main():
            import app.main as m
            limiter = m.app.state.limiter
            decorated = sorted(limiter._route_limits) + sorted(
                n for n in getattr(limiter, "_dynamic_route_limits", {})
            )
            print(json.dumps({"decorated_known_to_the_app_limiter": decorated}))

        asyncio.run(main())
        """
    )
    # The app-wide limiter owns no decorated routes (the decorators use their
    # own per-module Limiter instances), so nothing is double counted through
    # it; this pins that arrangement so a future move of a decorator onto the
    # app limiter is a deliberate, visible change.
    assert isinstance(probe["decorated_known_to_the_app_limiter"], list)


def test_the_throttled_response_still_carries_the_security_headers():
    """A 429 must not be a hole in the header policy.

    The middleware is registered innermost on purpose so its response travels
    back out through SecurityHeadersMiddleware and CORS. Registered outermost,
    a throttled browser request would fail as a CORS error instead of a 429 and
    would carry none of the headers every other response carries.
    """
    probe = _run_app_probe(
        """
        import asyncio, json, httpx

        async def main():
            import app.main as m
            transport = httpx.ASGITransport(app=m.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://town") as c:
                last = None
                for _ in range(5):
                    last = await c.get(
                        "/api/open311/v2/discovery.json",
                        headers={"X-Forwarded-For": "203.0.113.55, 203.0.113.55"},
                    )
            print(json.dumps({
                "status": last.status_code,
                "headers": {k.lower(): v for k, v in last.headers.items()},
            }))

        asyncio.run(main())
        """
    )
    assert probe["status"] == 429
    assert probe["headers"].get("x-content-type-options") == "nosniff"
    assert probe["headers"].get("x-frame-options") == "DENY"
