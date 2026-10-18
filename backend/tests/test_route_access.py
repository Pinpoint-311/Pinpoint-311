"""Every route's access rule is known, and nothing becomes public by accident.

app/core/route_access derives who may call a route from its dependency chain;
the OpenAPI schema and docs/API.md are labelled from it. This pins two things:

  * the PUBLIC set is exactly the list below. A new route that forgot its
    `Depends(get_current_staff)` lands here as "public" and fails this test,
    instead of shipping as an open endpoint nobody noticed. Adding a genuinely
    public route means adding it here, deliberately.
  * every operation in the generated schema carries `x-pinpoint-access` and a
    tag, so the docs cannot silently omit the access rule.
"""

import pytest

pytest.importorskip("fastapi.routing")
main = pytest.importorskip("app.main")

from fastapi.routing import APIRoute  # noqa: E402

from app.core.route_access import PUBLIC, route_access  # noqa: E402


EXPECTED_PUBLIC = {
    ('GET', '/'),
    ('GET', '/api/auth/bootstrap/auto'),
    ('GET', '/api/auth/bootstrap/{token}'),
    ('GET', '/api/auth/callback'),
    ('GET', '/api/auth/login'),
    ('GET', '/api/auth/status'),
    ('GET', '/api/deploy-templates/{cloud}/{filename}'),
    ('GET', '/api/docs'),
    ('GET', '/api/gis/boundaries'),
    ('GET', '/api/gis/boundaries/{name}'),
    ('GET', '/api/gis/check-boundary'),
    ('GET', '/api/gis/config'),
    ('GET', '/api/gis/geocode'),
    ('GET', '/api/gis/providers'),
    ('GET', '/api/gis/reverse-geocode'),
    ('GET', '/api/health'),
    ('GET', '/api/health/quick'),
    ('GET', '/api/health/version'),
    ('GET', '/api/integrations/accela/oauth/callback'),
    ('GET', '/api/map-layers/'),
    ('GET', '/api/map-layers/{layer_id}'),
    ('GET', '/api/open311/v2/discovery.json'),
    ('GET', '/api/open311/v2/public/requests'),
    ('GET', '/api/open311/v2/public/requests/{request_id}'),
    ('GET', '/api/open311/v2/public/requests/{request_id}/audit-log'),
    ('GET', '/api/open311/v2/public/requests/{request_id}/comments'),
    ('GET', '/api/open311/v2/services.json'),
    ('GET', '/api/open311/v2/services/{service_code}.json'),
    ('GET', '/api/open311/v2/tokens/{service_request_id}.json'),
    ('GET', '/api/sentry-debug'),
    ('GET', '/api/services/'),
    ('GET', '/api/services/{service_id}'),
    ('GET', '/api/system/config'),
    ('GET', '/api/system/settings'),
    ('GET', '/api/system/translate/languages'),
    ('POST', '/api/auth/bootstrap'),
    ('POST', '/api/auth/bootstrap/verify'),
    ('POST', '/api/auth/onboarding/redeem'),
    ('POST', '/api/feedback/platform'),
    ('POST', '/api/integrations/webhook/{platform}/{token}'),
    ('POST', '/api/open311/v2/photos/screen'),
    ('POST', '/api/open311/v2/public/requests/{request_id}/comments'),
    ('POST', '/api/open311/v2/requests.json'),
    ('POST', '/api/provisioning/break-glass'),
    ('POST', '/api/road-check'),
    ('POST', '/api/system/client-errors'),
    ('POST', '/api/system/disclaimer/acknowledge'),
    ('POST', '/api/system/translate/batch'),
}


def _routes():
    return [r for r in main.app.routes if isinstance(r, APIRoute)]


def test_the_public_surface_is_exactly_the_reviewed_list():
    public = {
        (method, route.path)
        for route in _routes()
        if route_access(route) == PUBLIC
        for method in route.methods
    }
    unexpected = public - EXPECTED_PUBLIC
    assert not unexpected, (
        f"routes with no auth dependency that are not on the reviewed public list: "
        f"{sorted(unexpected)} -- add the missing Depends(), or add them here on purpose"
    )
    assert not EXPECTED_PUBLIC - public, "a public route was removed or gained auth; update the list"


def test_every_operation_is_labelled_and_tagged():
    main.app.openapi_schema = None
    schema = main.app.openapi()
    operations = [op for path in schema["paths"].values() for op in path.values()]
    assert operations
    assert all("x-pinpoint-access" in op for op in operations)
    assert all(op["description"].startswith("**Access:**") for op in operations)
    assert all(op.get("tags") for op in operations)


def test_admin_routes_are_labelled_admin():
    users = [r for r in _routes() if r.path == "/api/users/" and "GET" in r.methods]
    assert users and route_access(users[0]) == "admin"


def test_inline_admin_routes_are_not_documented_as_any_signed_in_user():
    setup = [r for r in _routes() if r.path.startswith("/api/setup/")]
    assert setup and all(route_access(r) == "admin" for r in setup)
