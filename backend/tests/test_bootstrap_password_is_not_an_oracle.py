"""The first-run admin password must not be guessable at line speed.

`POST /api/auth/bootstrap/verify` takes a password and mints an ADMIN session
on a match. It is open on every deployment with no identity provider -- which is
every town between install and SSO setup, and both live demo instances. The
comparison is constant-time and a weak default is refused, so the remaining gap
was the one that mattered: there was no decorator, no lockout and no delay, so
an anonymous caller could guess as fast as the process could answer.

Two tiers, and each has a failure mode the other would cause:

  * per-address lockout, which must bite hard. Only the guesser is affected,
    because the address is now resolved through the trusted-proxy rule and
    cannot be aimed at somebody else.
  * a deployment-wide throttle for a distributed attacker, which must NEVER
    refuse and must never escalate -- otherwise any stranger on the internet
    could lock the town's real administrator out of their own first-run setup
    by spraying wrong passwords, and the defence becomes the attack.

Also here: the password stopped being a QUERY PARAMETER. uvicorn writes the
query string into every access line, so the deployment's admin password was
sitting in plaintext in the logs and in anything that ships them onward.

No database and no network: the throttle is pure functions over a clock, and
the request-shape checks read the real route's signature.
"""

import pytest

# Submodule guard, per tests/test_migrate.py.
pytest.importorskip("fastapi.routing")

from app.api import auth


@pytest.fixture(autouse=True)
def clean_throttle():
    auth._reset_bootstrap_throttle()
    yield
    auth._reset_bootstrap_throttle()


ATTACKER = "203.0.113.66"
ADMIN = "198.51.100.4"


# ---------------------------------------------------------------------------
# the oracle is closed
# ---------------------------------------------------------------------------


def test_unlimited_guessing_is_over():
    """The reproduction: guess repeatedly and eventually be refused.

    Before the fix this loop could run forever at whatever rate the network
    allowed.
    """
    now = 1000.0
    for _ in range(8):
        auth.note_bootstrap_failure(ATTACKER, now=now)
    assert auth.bootstrap_lockout_seconds(ATTACKER, now=now) > 0


def test_a_few_honest_typos_are_not_punished():
    """An admin fat-fingering a long password twice must not be locked out."""
    now = 1000.0
    for _ in range(auth._BOOTSTRAP_FREE_ATTEMPTS):
        auth.note_bootstrap_failure(ADMIN, now=now)
    assert auth.bootstrap_lockout_seconds(ADMIN, now=now) == 0


def test_the_lockout_escalates_and_is_capped():
    """Escalating makes a script useless; the cap keeps it from being forever."""
    now = 1000.0
    seen = []
    for _ in range(20):
        auth.note_bootstrap_failure(ATTACKER, now=now)
        seen.append(auth.bootstrap_lockout_seconds(ATTACKER, now=now))
    assert seen[4] > 0
    assert seen[6] > seen[5]  # doubling while below the cap
    assert max(seen) <= auth._BOOTSTRAP_MAX_LOCKOUT
    assert seen[-1] == auth._BOOTSTRAP_MAX_LOCKOUT


def test_the_lockout_expires():
    now = 1000.0
    for _ in range(6):
        auth.note_bootstrap_failure(ATTACKER, now=now)
    locked_for = auth.bootstrap_lockout_seconds(ATTACKER, now=now)
    assert locked_for > 0
    assert auth.bootstrap_lockout_seconds(ATTACKER, now=now + locked_for + 1) == 0


def test_the_right_password_clears_the_address():
    now = 1000.0
    for _ in range(6):
        auth.note_bootstrap_failure(ADMIN, now=now)
    assert auth.bootstrap_lockout_seconds(ADMIN, now=now) > 0
    auth.note_bootstrap_success(ADMIN)
    assert auth.bootstrap_lockout_seconds(ADMIN, now=now) == 0


# ---------------------------------------------------------------------------
# and the defence cannot be turned on the administrator
# ---------------------------------------------------------------------------


def test_an_attacker_cannot_lock_out_the_real_admin():
    """The property the whole two-tier design exists for.

    Ten thousand wrong guesses from strangers must leave the administrator's
    own address able to try. A single global counter that refused would have
    handed anyone on the internet a way to block first-run setup.
    """
    now = 1000.0
    for i in range(10000):
        auth.note_bootstrap_failure(f"203.0.113.{i % 254}", now=now)
    assert auth.bootstrap_lockout_seconds(ADMIN, now=now) == 0


def test_the_distributed_throttle_engages_but_only_ever_pauses():
    """It costs an attacker time and costs the admin at most one second."""
    now = 1000.0
    assert auth.bootstrap_global_pause(now=now) == 0
    for i in range(auth._BOOTSTRAP_GLOBAL_TRIGGER):
        auth.note_bootstrap_failure(f"203.0.113.{i}", now=now)
    assert auth.bootstrap_global_pause(now=now) == auth._BOOTSTRAP_GLOBAL_PAUSE


def test_the_distributed_throttle_never_re_arms_or_escalates():
    """Capped by construction: more failures must not make the pause longer.

    A pause that grew with the failure count is a denial of service anyone can
    trigger, which is exactly what must not happen to the endpoint an admin
    needs in order to take control of their own deployment.
    """
    now = 1000.0
    for i in range(5000):
        auth.note_bootstrap_failure(f"203.0.113.{i % 254}", now=now)
    assert auth.bootstrap_global_pause(now=now) == auth._BOOTSTRAP_GLOBAL_PAUSE


def test_the_distributed_throttle_expires_on_its_own():
    now = 1000.0
    for i in range(auth._BOOTSTRAP_GLOBAL_TRIGGER + 5):
        auth.note_bootstrap_failure(f"203.0.113.{i}", now=now)
    assert auth.bootstrap_global_pause(now=now) > 0
    assert auth.bootstrap_global_pause(now=now + auth._BOOTSTRAP_GLOBAL_WINDOW + 1) == 0


# ---------------------------------------------------------------------------
# the endpoints actually consult it
# ---------------------------------------------------------------------------


class _Headers(dict):
    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)


def _async(value, record=None):
    async def _fn(*args, **kwargs):
        if record is not None:
            record.append("gate")
        return value

    return _fn


class _Request:
    def __init__(self, peer="172.19.0.5", forwarded=None):
        self.client = type("C", (), {"host": peer})()
        self.headers = _Headers()
        if forwarded:
            self.headers["x-forwarded-for"] = forwarded


@pytest.mark.asyncio
async def test_a_locked_out_address_is_refused_before_the_password_is_read():
    """The guard runs first, so a locked address cannot even test a guess.

    Checked by watching whether the comparison happens at all: a guard that ran
    *after* the comparison would still be an oracle, just a slower one.
    """
    compared = []

    original = auth._verify_bootstrap_password
    auth._verify_bootstrap_password = lambda supplied: compared.append(supplied)
    try:
        request = _Request(forwarded=f"8.8.8.8, {ATTACKER}")
        for _ in range(10):
            auth.note_bootstrap_failure(auth._bootstrap_client(request))
        with pytest.raises(Exception) as exc:
            await auth._guard_bootstrap_attempt(request)
        assert getattr(exc.value, "status_code", None) == 429
        assert compared == []
    finally:
        auth._verify_bootstrap_password = original


@pytest.mark.asyncio
async def test_the_lockout_follows_the_real_caller_not_the_proxy():
    """Behind Caddy every caller shares one peer address.

    Keyed on the peer, the first attacker to trip the lockout would have locked
    out the entire town including the admin -- the same town-wide-bucket bug as
    the rate limits. Keyed on a naively-trusted forwarded header, an attacker
    would get a fresh allowance per forged value. Neither may happen.
    """
    attacker = _Request(forwarded=f"1.1.1.1, {ATTACKER}")
    admin = _Request(forwarded=f"1.1.1.1, {ADMIN}")

    assert auth._bootstrap_client(attacker) == ATTACKER
    assert auth._bootstrap_client(admin) == ADMIN

    for _ in range(10):
        auth.note_bootstrap_failure(auth._bootstrap_client(attacker))

    with pytest.raises(Exception):
        await auth._guard_bootstrap_attempt(attacker)
    # The admin is untouched: no exception.
    assert await auth._guard_bootstrap_attempt(admin) == ADMIN


def _handler(fn):
    """The handler body, without slowapi's decorator wrapper.

    The decorator is checked separately against slowapi's own registry; these
    tests are about what the handler itself does.
    """
    return getattr(fn, "__wrapped__", fn)


@pytest.mark.asyncio
async def test_the_verify_endpoint_records_every_wrong_password(monkeypatch):
    """Not just that a lockout CAN be computed -- that the endpoint feeds it.

    A guard nothing calls is the same as no guard, and that is the shape the
    original bug had: all the pieces for a safe bootstrap were present except
    anything that counted.
    """
    monkeypatch.setattr(auth, "_bootstrap_gate_open", _async(True))

    def refuse(supplied):
        raise auth.HTTPException(status_code=401, detail="Invalid bootstrap password.")

    monkeypatch.setattr(auth, "_verify_bootstrap_password", refuse)

    request = _Request(forwarded=f"8.8.8.8, {ATTACKER}")
    for _ in range(8):
        await _handler(auth.verify_bootstrap)(request=request, password="guess", db=None)

    assert auth.bootstrap_lockout_seconds(ATTACKER) > 0


@pytest.mark.asyncio
async def test_the_verify_endpoint_refuses_a_locked_address(monkeypatch):
    """And once locked, it answers 429 without consulting the password at all.

    `db=None` is load-bearing: if the handler reached the gate check or the
    comparison it would raise instead of answering, so this only passes when
    the guard runs first.
    """
    touched = []
    monkeypatch.setattr(
        auth, "_bootstrap_gate_open", _async(True, record=touched)
    )
    monkeypatch.setattr(
        auth, "_verify_bootstrap_password", lambda supplied: touched.append("compared")
    )

    request = _Request(forwarded=f"8.8.8.8, {ATTACKER}")
    for _ in range(12):
        auth.note_bootstrap_failure(ATTACKER)

    response = await _handler(auth.verify_bootstrap)(
        request=request, password="guess", db=None
    )
    assert response.status_code == 429
    assert touched == []


@pytest.mark.asyncio
async def test_forging_the_header_does_not_buy_a_fresh_allowance():
    keys = {
        auth._bootstrap_client(_Request(forwarded=f"{forged}, {ATTACKER}"))
        for forged in ("8.8.8.8", "1.1.1.1", "9.9.9.9")
    }
    assert keys == {ATTACKER}


# ---------------------------------------------------------------------------
# the password stops appearing in the access log
# ---------------------------------------------------------------------------


def _route(path, method):
    for route in auth.router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", ()):
            return route
    raise AssertionError(f"no route {method} {path}")


def test_the_bootstrap_password_is_not_a_query_parameter():
    """uvicorn logs the query string of every request, verbatim.

    `POST /bootstrap?password=...` therefore wrote the deployment's admin
    password into the access log in plaintext, where it also reaches the proxy
    log and any log shipper. Its sibling /bootstrap/verify already took a form
    field; this checks the real route's resolved parameters rather than the
    source text, so moving it back would fail here.
    """
    dependant = _route("/bootstrap", "POST").dependant
    query_names = {p.name for p in dependant.query_params}
    assert "password" not in query_names, query_names


def test_the_bootstrap_password_arrives_in_the_body():
    from fastapi.dependencies.utils import get_flat_params  # noqa: F401

    dependant = _route("/bootstrap", "POST").dependant
    body_names = {p.name for p in (dependant.body_params or [])}
    assert "password" in body_names, body_names


def test_both_bootstrap_endpoints_carry_a_rate_limit():
    """The decorator is the ceiling; the lockout is the escalation.

    Read off slowapi's own registry, so removing a decorator fails here.
    """
    registered = set(auth.limiter._route_limits) | set(
        getattr(auth.limiter, "_dynamic_route_limits", {})
    )
    names = {name.rsplit(".", 1)[-1] for name in registered}
    assert {"generate_bootstrap_token", "verify_bootstrap"} <= names, names
