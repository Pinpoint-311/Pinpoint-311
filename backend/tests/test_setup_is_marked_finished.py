"""Being finished is a thing a person says.

Nothing detected a fresh install. `SetupIntegrationsPage` is a tab inside the
admin console, and the console opens on Branding -- so on a brand new deployment
the setup guide sat behind a click nobody had a reason to make. The first thing
a town needs was the thing it was least likely to find.

The guide did open itself, on `!signInConfigured || !mapsConfigured`. That is
"is everything set up" wearing a disguise, and it is wrong in both directions: a
town that deliberately switches most things off never satisfies it, so the guide
greets it on every login forever; and an install where those two happen to be
pre-seeded gets no guide at all.

So there is a marker, and only a person sets it.
"""

import asyncio

import pytest

pytest.importorskip("fastapi")

from app.api import system


def _run(coro):
    return asyncio.run(coro)


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Session:
    def __init__(self, row):
        self.row = row
        self.commits = 0

    async def execute(self, _stmt):
        return _Result(self.row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    def add(self, row):
        self.row = row


@pytest.fixture
def quiet_audit(monkeypatch):
    """The audit trail is not what these tests are about, and it wants a real
    session. Recording never blocks the action anyway."""
    async def record(*_a, **_k):
        return True

    monkeypatch.setattr("app.services.admin_audit.record_admin_action", record)


@pytest.fixture
def town():
    from app.models import SystemSettings

    row = SystemSettings()
    row.setup_completed_at = None
    return _Session(row)


def test_a_fresh_town_has_not_finished(town):
    state = _run(system.get_setup_state(db=town, _=None))
    assert state["completed"] is False
    assert state["completed_at"] is None


def test_saying_so_is_what_sets_it(town, quiet_audit):
    state = _run(system.mark_setup_complete(db=town, admin=None))

    assert state["completed"] is True
    assert town.row.setup_completed_at is not None
    assert town.commits == 1


def test_it_is_not_gated_on_anything_being_configured(town, quiet_audit):
    """Two things are actually required before a town can take a report, and the
    page says which. Refusing to let somebody close the guide until a checklist
    is green would make the guide the thing standing between them and the
    console -- and a town that switched everything else off is finished."""
    _run(system.mark_setup_complete(db=town, admin=None))
    assert town.row.setup_completed_at is not None


def test_marking_it_twice_keeps_the_first_date(town, quiet_audit):
    """It is a date somebody may later want to point at, and the guide reopens
    from the tab regardless -- this flag only decides what happens on sign-in."""
    _run(system.mark_setup_complete(db=town, admin=None))
    first = town.row.setup_completed_at

    _run(system.mark_setup_complete(db=town, admin=None))
    assert town.row.setup_completed_at == first
    assert town.commits == 1, "the second call rewrote the row"


def test_a_town_with_no_settings_row_still_gets_an_answer(quiet_audit):
    """The read runs on every admin sign-in, including the first one, and a 500
    there is a console nobody can open."""
    empty = _Session(None)
    assert _run(system.get_setup_state(db=empty, _=None))["completed"] is False


def test_the_marker_is_not_derived_from_the_capabilities():
    """The check that matters, as structure rather than behaviour: nothing in
    either endpoint consults provider status, `ready`, or the switches. If it
    ever does, this is the proxy coming back."""
    import inspect

    for endpoint in (system.get_setup_state, system.mark_setup_complete):
        src = inspect.getsource(endpoint)
        for proxy in ("capability_is_configured", "_configured_map", "providers_for",
                      "capability_switches"):
            assert proxy not in src, f"{endpoint.__name__} derives setup state from {proxy}"
