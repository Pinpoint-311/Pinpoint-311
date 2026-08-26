"""Signing in on a provider that is not Auth0.

A deployment switched to Microsoft Entra ID failed in two ways at once, and
neither was visible from the other end:

  * Every login already in flight died on a backend restart. The CSRF state
    token lived in a module-level dict, so a deploy that landed while the
    operator was typing their password turned a successful Microsoft sign-in
    into "Invalid or expired state token".

  * Status was always reported against Auth0. `check_status` read the AUTH0_*
    secrets whatever the selected provider was, and `/auth/status` returned the
    literal string "auth0". On this box that merely mislabelled the login page.
    On a fresh Entra-only install -- which the deployment template produces, and
    which has no AUTH0_* secrets at all -- it meant `initiate_login` refused
    with "Authentication not configured" and nobody could ever sign in.
"""

import pytest

# login_state is pure stdlib, so it imports anywhere. auth0_service pulls in
# fastapi / PyJWT / SQLAlchemy, which CI's pytest job does not install -- guard
# those tests individually rather than skipping this whole file, which would
# silently drop the login-state regression coverage in CI.
from app.services import login_state


def _needs_app():
    pytest.importorskip("fastapi.routing")
    pytest.importorskip("jwt.api_jwt")
    pytest.importorskip("sqlalchemy.orm")
    from app.services.auth0_service import Auth0Service
    return Auth0Service


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch):
    """No Redis in the unit suite: exercise the in-memory fallback path, and
    never leak a token between tests."""
    monkeypatch.setattr(login_state, "_client", lambda: None)
    login_state._memory.clear()
    yield
    login_state._memory.clear()


class TestLoginStateSurvives:
    @pytest.mark.asyncio
    async def test_state_round_trips(self):
        await login_state.remember("abc", "https://town.example/login")
        assert await login_state.consume("abc") == "https://town.example/login"

    @pytest.mark.asyncio
    async def test_state_is_single_use(self):
        """A redeemed state token must not open a second callback."""
        await login_state.remember("abc", "https://town.example/login")
        await login_state.consume("abc")
        assert await login_state.consume("abc") is None

    @pytest.mark.asyncio
    async def test_unknown_state_is_rejected(self):
        assert await login_state.consume("never-issued") is None

    @pytest.mark.asyncio
    async def test_expired_state_is_rejected(self, monkeypatch):
        await login_state.remember("abc", "https://town.example/login")
        now = __import__("time").time()
        monkeypatch.setattr(login_state.time, "time",
                            lambda: now + login_state.TTL_SECONDS + 1)
        assert await login_state.consume("abc") is None

    @pytest.mark.asyncio
    async def test_state_outlives_a_restart_when_redis_holds_it(self, monkeypatch):
        """The actual regression. Redis keeps the token; the process losing its
        memory mid-login must no longer invalidate the round-trip.

        Reverting to the module-level dict fails here, because the dict is
        exactly what gets cleared."""
        store = {}

        class FakeRedis:
            async def setex(self, key, ttl, value):
                store[key] = value

            async def get(self, key):
                return store.get(key)

            async def delete(self, key):
                store.pop(key, None)

        monkeypatch.setattr(login_state, "_client", lambda: FakeRedis())

        await login_state.remember("abc", "https://town.example/login")

        # The restart: every in-process structure is gone.
        login_state._memory.clear()

        assert await login_state.consume("abc") == "https://town.example/login"

    @pytest.mark.asyncio
    async def test_redis_failure_falls_back_rather_than_breaking_login(self, monkeypatch):
        """A cache outage must not be an outage of staff sign-in."""
        class BrokenRedis:
            async def setex(self, *a, **k):
                raise RuntimeError("redis down")

            async def get(self, *a, **k):
                raise RuntimeError("redis down")

        monkeypatch.setattr(login_state, "_client", lambda: BrokenRedis())

        await login_state.remember("abc", "https://town.example/login")
        assert await login_state.consume("abc") == "https://town.example/login"


def _secrets(mapping):
    async def fake_get_secret(key, *a, **k):
        return mapping.get(key)
    return fake_get_secret


class TestStatusFollowsTheSelectedProvider:
    @pytest.mark.asyncio
    async def test_entra_only_install_is_configured(self, monkeypatch):
        """No AUTH0_* secrets exist. This previously reported "not_configured",
        which made `initiate_login` refuse and left the town locked out."""
        Auth0Service = _needs_app()
        import app.services.secret_manager as sm
        import app.services.identity as identity

        monkeypatch.setattr(sm, "get_secret", _secrets({
            "IDENTITY_PROVIDER": "entra",
            "ENTRA_TENANT_ID": "42affcd0-98cd-4c54-8e94-5ae059ac29c7",
            "ENTRA_CLIENT_ID": "b1c2d3e4-0000-1111-2222-333344445555",
            "ENTRA_CLIENT_SECRET": "shh",
        }))
        monkeypatch.setattr(identity, "get_oidc_metadata", _meta_ok)

        result = await Auth0Service.check_status(db=None)

        assert result["status"] == "configured"
        assert result["provider"] == "entra"
        assert "Entra" in result["message"]

    @pytest.mark.asyncio
    async def test_unreachable_entra_tenant_is_an_error_not_a_success(self, monkeypatch):
        Auth0Service = _needs_app()
        import app.services.secret_manager as sm
        import app.services.identity as identity

        monkeypatch.setattr(sm, "get_secret", _secrets({
            "IDENTITY_PROVIDER": "entra",
            "ENTRA_TENANT_ID": "42affcd0-98cd-4c54-8e94-5ae059ac29c7",
            "ENTRA_CLIENT_ID": "b1c2d3e4-0000-1111-2222-333344445555",
            "ENTRA_CLIENT_SECRET": "shh",
        }))

        async def boom(config):
            raise RuntimeError("discovery unreachable")
        monkeypatch.setattr(identity, "get_oidc_metadata", boom)

        result = await Auth0Service.check_status(db=None)

        assert result["status"] == "error"
        assert result["provider"] == "entra"

    @pytest.mark.asyncio
    async def test_entra_selected_but_unconfigured_names_entra(self, monkeypatch):
        """The message a half-finished setup shows must name the provider the
        operator chose, not the one they moved away from."""
        Auth0Service = _needs_app()
        import app.services.secret_manager as sm

        monkeypatch.setattr(sm, "get_secret", _secrets({
            "IDENTITY_PROVIDER": "entra",
            "AUTH0_DOMAIN": "stale.us.auth0.com",
            "AUTH0_CLIENT_ID": "old",
            "AUTH0_CLIENT_SECRET": "old",
        }))

        result = await Auth0Service.check_status(db=None)

        assert result["status"] == "not_configured"
        assert result["provider"] == "entra"
        assert "Entra" in result["message"]
        assert "Auth0" not in result["message"]


async def _meta_ok(config):
    return {
        "authorization_endpoint": f"{config['issuer_base']}/oauth2/v2.0/authorize",
        "token_endpoint": f"{config['issuer_base']}/oauth2/v2.0/token",
        "jwks_uri": f"{config['issuer_base']}/discovery/v2.0/keys",
        "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
        "issuer": config["issuer_base"],
    }


class TestEmailClaimFallback:
    """Entra work accounts often carry no `email` claim. The callback refuses a
    login without one, so a valid sign-in was rejected as "Email not provided
    by identity provider"."""

    def _fn(self):
        pytest.importorskip("jwt.api_jwt")
        pytest.importorskip("fastapi.routing")
        from app.services.identity import _with_email
        return _with_email

    def test_email_claim_is_left_alone_when_present(self):
        claims = self._fn()({"email": "clerk@town.gov", "preferred_username": "other@town.gov"})
        assert claims["email"] == "clerk@town.gov"

    def test_preferred_username_fills_in_for_entra(self):
        claims = self._fn()({"preferred_username": "clerk@town.gov", "sub": "abc"})
        assert claims["email"] == "clerk@town.gov"

    def test_upn_is_accepted_when_preferred_username_is_absent(self):
        claims = self._fn()({"upn": "clerk@town.gov"})
        assert claims["email"] == "clerk@town.gov"

    def test_a_bare_username_is_not_treated_as_an_email(self):
        """Some directories issue a UPN with no domain. Matching that against
        the staff table would sign in the wrong person, or nobody."""
        claims = self._fn()({"preferred_username": "jsmith"})
        assert "email" not in claims

    def test_the_original_claims_are_not_mutated(self):
        original = {"preferred_username": "clerk@town.gov"}
        self._fn()(original)
        assert "email" not in original
