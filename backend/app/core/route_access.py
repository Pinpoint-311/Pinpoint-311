"""Who may call each route, read off the route's own dependencies.

Used to label every operation in the OpenAPI schema (see app.main) and to
generate the route table in docs/API.md, so the documented access rule is the
enforced one rather than a second copy someone has to remember to update.

The label comes from the dependency chain FastAPI actually resolves. The
exceptions are routes that verify something inside the handler instead of in a
dependency; those are listed by endpoint name below, each with the reason, and
tests/test_route_access.py fails if a new unauthenticated route appears that
is neither listed nor deliberately public.
"""

from typing import Iterable, Optional

ADMIN = "admin"
STAFF = "staff"  # staff or admin
RESEARCHER = "researcher"  # researcher or admin
SIGNED_IN = "signed-in"  # any active account
ORCHESTRATOR = "orchestrator-token"
UPDATER = "updater-token"
PUBLIC = "public"

DESCRIPTIONS = {
    ADMIN: "Admin JWT.",
    STAFF: "Staff or admin JWT. Request-level reads and writes are scoped to the caller's departments (admins see all).",
    RESEARCHER: "Researcher or admin JWT, and the Research Suite module must be enabled.",
    SIGNED_IN: "Any signed-in account (JWT).",
    ORCHESTRATOR: "Hosting-panel shared secret (X-Provisioning-Token / X-Panel-Token header); 404 when not configured.",
    UPDATER: ("Host updater token only (Authorization: Bearer, hashed at rest, constant-time compare). "
              "Internal: Caddy answers 404 for /api/internal/* and the backend refuses proxied requests; "
              "the updater calls the backend's loopback port. 404 in managed mode."),
    PUBLIC: "Public, no authentication.",
}

# Handlers that take a JWT for any account but then enforce a stricter role.
_INLINE_ROLE = {
    # every app.api.setup route checks `current_user.role != "admin"` itself
    "get_setup_status": ADMIN,
    "configure_gcp": ADMIN,
    "configure_auth0": ADMIN,
    "verify_setup": ADMIN,
    "generate_backup_key": ADMIN,
    "storage_status": ADMIN,
    "reencrypt_pii": ADMIN,
}

# Unauthenticated at the dependency level, verified inside the handler.
_VERIFIED_IN_HANDLER = {
    "generate_bootstrap_token": "Public; first-run only, closed once an identity provider is configured, rate limited.",
    "auto_bootstrap": "Public; first-run only, closed once an identity provider is configured.",
    "verify_bootstrap": "Public; requires the bootstrap secret, rate limited with lockout.",
    "use_bootstrap_token": "Public; requires a one-time bootstrap token.",
    "redeem_onboarding_token": "Public; requires a single-use signed onboarding token.",
    "exchange_login_code": "Public; requires the single-use, 60-second code the sign-in callback issued.",
    "exchange_break_glass": "Managed mode only; requires a panel-signed break-glass token.",
    "integration_webhook": "Public URL; requires the integration's webhook token in the path.",
    "create_request_open311": "Requires a valid, unrevoked Open311 `api_key` in the body, unless an admin allowed anonymous Open311 submissions. Rate limited per key (anonymous: per client).",
    "create_request": "Public, first-party only: the town's resident portal. Same-origin browser submissions (Fetch Metadata / Origin), 10/minute per client.",
    "accela_oauth_callback": "Public URL; requires a signed, time-limited OAuth state.",
    "delete_comment": "Any signed-in account; only the comment's author or an admin succeeds.",
    "logout": "Any signed-in account.",
    "public_layer_outlines": "Public; only for a polygon layer an admin put on the resident portal (404 otherwise). Simplified geometry only, no properties or ids; capped per request, rate limited.",
}


def _dependency_names(dependant) -> Iterable[str]:
    for dep in dependant.dependencies:
        if dep.call is not None:
            yield getattr(dep.call, "__name__", "")
        yield from _dependency_names(dep)


def route_access(route) -> str:
    """The access class of one APIRoute: one of the constants above."""
    name = route.endpoint.__name__
    if name in _INLINE_ROLE:
        return _INLINE_ROLE[name]
    deps = set(_dependency_names(route.dependant))
    if "get_current_admin" in deps:
        return ADMIN
    if "get_current_researcher" in deps:
        return RESEARCHER
    if "get_current_staff" in deps:
        return STAFF
    if "get_current_user" in deps:
        return SIGNED_IN
    if deps & {"require_provisioning_token", "require_panel_token"}:
        return ORCHESTRATOR
    if "require_updater_token" in deps:
        return UPDATER
    return PUBLIC


def access_note(route) -> str:
    """One sentence for humans: who may call this route."""
    special: Optional[str] = _VERIFIED_IN_HANDLER.get(route.endpoint.__name__)
    return special or DESCRIPTIONS[route_access(route)]
