"""The connectors a town wires up itself report health like everything else.

The monitoring story for govtech integrations was largely fictional. A
`connector_health` row for `govtech:accela` appeared only when a resident
happened to file a report that got pushed; the daily sweep enumerated the eight
built-in capabilities and never looked at `integration_configs` at all.

Two consequences, and the second is the one that sent mail:

  * a town whose Accela credentials expired on Friday found out from a resident,
    because nothing tested the connection on its own;
  * `FRESH_FOR` is three days, justified in `connector_health` by "there is now
    a sweep that actively tests every configured connector once a day". For
    these connectors there wasn't, so three quiet days -- a long weekend --
    aged the last real success into `stale`, and the town got an email saying
    Accela may stop working when nothing was wrong with it.

Nothing here needs a database: the rows, the connector factory and the breaker
are all injected, which is the only reason the sweep is testable at all.
"""

import asyncio

import pytest

from app.services.connector_verification import (
    health_key,
    verify_all,
    verify_integrations,
)


class Row:
    """An `integration_configs` row, as the sweep reads it."""

    def __init__(self, platform, enabled=True):
        self.platform = platform
        self.enabled = enabled
        self.config = {}
        self.credentials = {}


class FakeHealth:
    def __init__(self):
        self.successes, self.failures, self.unverifiable = [], [], []

    async def record_success(self, db, connector, provider=None, detail=None):
        self.successes.append((connector, provider))

    async def record_failure(self, db, connector, error, provider=None):
        self.failures.append((connector, str(error)))

    async def record_unverifiable(self, db, connector, detail, provider=None):
        self.unverifiable.append((connector, detail))

    async def snapshot(self, db):
        return {}


def connector(result=None, raises=None):
    class Connector:
        async def test_connection(self):
            if raises is not None:
                raise raises
            return result

    return Connector()


def sweep(rows, connectors, health=None):
    """Run verify_integrations with a real-signature guard around fake vendors.

    `guard` here has `circuit_breaker.guard`'s signature and its contract:
    record the outcome to health, and let the exception through.
    """
    health = health or FakeHealth()

    async def build(integration):
        built = connectors[integration.platform]
        if isinstance(built, Exception):
            raise built
        return built

    async def guard(name, call, *, db=None, provider=None):
        try:
            out = await call()
        except Exception as exc:
            await health.record_failure(db, name, exc, provider=provider)
            raise
        await health.record_success(db, name, provider=provider)
        return out

    checked = asyncio.run(verify_integrations(
        None, integrations=rows, build=build, guard=guard, health=health))
    return checked, health


# ---------------------------------------------------------------------------
# The gap: nothing tested these at all
# ---------------------------------------------------------------------------

def test_an_enabled_integration_is_tested_and_recorded_as_working():
    checked, health = sweep(
        [Row("accela")],
        {"accela": connector({"ok": True, "verified": True, "detail": "authenticated"})},
    )
    assert checked == {"govtech:accela": "working"}
    assert health.successes == [("govtech:accela", "accela")]


def test_a_vendor_that_is_down_flips_to_failing_with_no_resident_traffic():
    """The acceptance criterion. Before this the only writer of govtech health
    was the push path, so a broken connector stayed whatever it was last time
    somebody filed a report through it."""
    checked, health = sweep(
        [Row("accela")],
        {"accela": connector(raises=RuntimeError("HTTP 401 — invalid_client"))},
    )
    assert checked == {"govtech:accela": "error"}
    assert health.failures == [("govtech:accela", "HTTP 401 — invalid_client")]
    assert health.successes == []


def test_a_healthy_integration_gets_a_success_every_sweep_so_it_never_goes_stale():
    """Why the false "Accela may stop working" email happened: staleness is
    measured from the last success, and for three days nothing recorded one."""
    health = FakeHealth()
    for _ in range(3):
        sweep([Row("accela")], {"accela": connector({"ok": True, "verified": True})},
              health=health)
    assert len(health.successes) == 3
    assert health.failures == []


def test_a_disabled_integration_is_left_alone():
    """Same rule the capability sweep follows: an amber badge on a connection a
    town switched off is the noise that teaches people to ignore badges."""
    called = []

    class Watching:
        async def test_connection(self):
            called.append(True)
            return {"ok": True}

    checked, health = sweep([], {"accela": Watching()})
    assert checked == {} and called == []


def test_only_enabled_rows_are_selected_from_the_database():
    """The filter lives in the query, so a town with ten configured and two
    enabled connections is not billed for ten vendor calls a day."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "app/services/connector_verification.py").read_text()
    block = source[source.index("async def _enabled_integrations"):]
    assert "IntegrationConfig.enabled.is_(True)" in block


# ---------------------------------------------------------------------------
# Failure modes of the sweep itself
# ---------------------------------------------------------------------------

def test_a_connector_that_cannot_even_be_built_is_recorded_as_a_failure():
    """A missing base_url or an unresolvable vault reference never reaches the
    breaker, so nothing would have written that row -- and "we could not build a
    client for this" is just as much a reason the connection does not work."""
    checked, health = sweep(
        [Row("generic_rest")],
        {"generic_rest": RuntimeError("generic_rest: no API base URL configured")},
    )
    assert checked == {"govtech:generic_rest": "error"}
    assert "no API base URL" in health.failures[0][1]


def test_one_broken_integration_does_not_hide_the_others():
    """Aborting on the first raise would leave every connector after it
    unreported, which is the state this replaces."""
    checked, _ = sweep(
        [Row("accela"), Row("civicplus"), Row("open311")],
        {
            "accela": connector(raises=RuntimeError("boom")),
            "civicplus": connector({"ok": True, "verified": True}),
            "open311": connector({"ok": True, "verified": False, "detail": "anonymous"}),
        },
    )
    assert checked == {
        "govtech:accela": "error",
        "govtech:civicplus": "working",
        "govtech:open311": "unverifiable",
    }


def test_reachable_but_unverified_is_not_recorded_as_working():
    """An Open311 server answering /services.json to anybody is evidence the
    host is up and none at all that the key is good. A green tick earned by an
    anonymous request is the exact over-claim this subsystem exists to stop."""
    checked, health = sweep(
        [Row("open311")],
        {"open311": connector({"ok": True, "verified": False,
                               "detail": "Server reachable; credentials unexercised"})},
    )
    assert checked == {"govtech:open311": "unverifiable"}
    assert health.unverifiable == [
        ("govtech:open311", "Server reachable; credentials unexercised")]


def test_a_vendor_the_breaker_has_paused_is_not_recorded_again():
    """The failures that opened the circuit are already in the row. Writing one
    more per sweep for a call we chose not to make would push the count up on no
    new evidence, and the count is what decides "blip" from "outage"."""
    from app.services.circuit_breaker import CircuitOpen

    health = FakeHealth()

    async def build(integration):
        return connector({"ok": True})

    async def guard(name, call, *, db=None, provider=None):
        raise CircuitOpen(name, 42.0)

    checked = asyncio.run(verify_integrations(
        None, integrations=[Row("accela")], build=build, guard=guard, health=health))
    assert checked == {"govtech:accela": "paused"}
    assert health.failures == [] and health.successes == []


# ---------------------------------------------------------------------------
# The Test button
# ---------------------------------------------------------------------------

def press_test(row, built, health=None, breaker=None):
    from app.services.circuit_breaker import Breaker, guard

    health = health or FakeHealth()
    breaker = breaker or Breaker()

    async def build(integration):
        if isinstance(built, Exception):
            raise built
        return built

    async def guarded(name, call, *, db=None, provider=None):
        breaker.check(name)
        try:
            out = await call()
        except Exception as exc:
            breaker.record_failure(name)
            await health.record_failure(db, name, exc, provider=provider)
            raise
        breaker.record_success(name)
        await health.record_success(db, name, provider=provider)
        return out

    from app.services.connector_verification import check_integration_now
    result = asyncio.run(check_integration_now(
        None, row, build=build, guard=guarded, health=health, breaker=breaker))
    return result, health, breaker


def test_pressing_test_records_the_result_against_health():
    """The acceptance criterion for the button: one passing test flips the badge.
    It used to write a sync-log row and leave health untouched."""
    result, health, _ = press_test(
        Row("accela"), connector({"ok": True, "verified": True, "detail": "authenticated"}))
    assert result["ok"] is True
    assert health.successes == [("govtech:accela", "accela")]


def test_a_failing_test_is_recorded_too():
    result, health, _ = press_test(
        Row("accela"), connector(raises=RuntimeError("HTTP 401 — invalid_client")))
    assert result["ok"] is False
    assert "invalid_client" in result["detail"]
    assert len(health.failures) == 1, "recorded the same failure more than once"


def test_a_passing_test_clears_the_cooldown_so_the_next_push_is_attempted():
    """Somebody who has just fixed a credential should not wait out a cooldown
    the broken one earned. `Breaker.reset` was documented for exactly this and
    had no caller outside its own tests."""
    from app.services.circuit_breaker import CLOSED, Breaker

    breaker = Breaker()
    for _ in range(3):
        breaker.record_failure("govtech:accela")
    assert breaker.state("govtech:accela") != CLOSED

    press_test(Row("accela"), connector({"ok": True, "verified": True}), breaker=breaker)
    assert breaker.state("govtech:accela") == CLOSED


def test_an_open_circuit_does_not_refuse_an_explicit_admin_test():
    """An admin test is the sanctioned probe. Returning "calls are paused for
    another 47s" to the one person actively trying to fix it is the least useful
    moment to enforce a latency guard."""
    from app.services.circuit_breaker import Breaker

    breaker = Breaker()
    for _ in range(3):
        breaker.record_failure("govtech:accela")

    result, health, _ = press_test(
        Row("accela"), connector({"ok": True, "verified": True, "detail": "fixed"}),
        breaker=breaker)
    assert result["ok"] is True
    assert health.successes, "the test never reached the vendor"


def test_a_test_that_cannot_build_a_connector_is_still_recorded():
    result, health, _ = press_test(
        Row("generic_rest"), RuntimeError("generic_rest: no API base URL configured"))
    assert result["ok"] is False
    assert health.failures[0][0] == "govtech:generic_rest"


def test_a_reachable_but_unverified_test_does_not_claim_the_key_works():
    result, health, _ = press_test(
        Row("open311"),
        connector({"ok": True, "verified": False, "detail": "Server reachable"}))
    assert result["verified"] is False
    assert health.unverifiable == [("govtech:open311", "Server reachable")]


def test_the_endpoint_delegates_to_the_service():
    """So the button and the sweep cannot drift into two different definitions
    of what testing a connection means."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/integrations.py").read_text()
    block = source[source.index("async def test_integration"):]
    block = block[:block.index("@router.post", 1)] if "@router.post" in block[1:] else block
    assert "check_integration_now" in block
    assert "connector.test_connection()" not in block


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_the_sweep_reports_integrations_alongside_the_capabilities():
    """One summary, one digest. Two separate reporting paths would drift and a
    town would learn which one to trust the hard way."""
    health = FakeHealth()

    async def is_configured(capability):
        return True

    async def ok(db=None):
        return {"ok": True, "detail": "fine"}

    async def build(integration):
        return connector(raises=RuntimeError("HTTP 403"))

    async def guard(name, call, *, db=None, provider=None):
        try:
            return await call()
        except Exception as exc:
            await health.record_failure(db, name, exc, provider=provider)
            raise

    result = asyncio.run(verify_all(
        None, checks={"maps": ok}, is_configured=is_configured,
        health=health, alerts=None, integrations=[Row("accela")]))

    assert result["checked"]["maps"] == "working"
    assert result["checked"]["govtech:accela"] == "error"
    assert "govtech:accela" in result["failing"]


def test_a_sweep_that_cannot_read_the_integrations_still_reports_the_capabilities():
    """It runs unattended. A database hiccup listing one table must not turn a
    completed sweep into no sweep."""
    health = FakeHealth()

    async def is_configured(capability):
        return True

    async def ok(db=None):
        return {"ok": True, "detail": "fine"}

    # db=None, so the IntegrationConfig query raises inside verify_integrations.
    result = asyncio.run(verify_all(
        None, checks={"maps": ok}, is_configured=is_configured, health=health))
    assert result["checked"]["maps"] == "working"


def test_every_path_writes_the_same_row():
    """`govtech:accela`, not `accela` and not `integration:accela`. A second
    naming would give one connector two rows, and the card would show whichever
    code path last ran.

    Asserted through the shared helper rather than a literal: push, pull,
    comments, assets, the admin Test button and the daily sweep all call
    `health_key`, so there is one spelling and nowhere to typo a second one.
    """
    from pathlib import Path

    assert health_key("accela") == "govtech:accela"
    tasks = (Path(__file__).resolve().parents[1] / "app/tasks/integrations.py").read_text()
    assert "from app.services.connector_verification import health_key" in tasks
    assert "health_key(integration.platform)" in tasks
    # And nobody rebuilt it by hand alongside the helper.
    assert 'f"govtech:' not in tasks


def test_the_daily_task_is_what_runs_the_sweep():
    pytest.importorskip("celery")
    from app.core.celery_app import celery_app

    entry = celery_app.conf.beat_schedule.get("daily-connector-check")
    assert entry and entry["task"] == "app.tasks.connector_checks.verify_connectors"


# ---------------------------------------------------------------------------
# Every real call to a vendor is recorded, not only the ones on the push path
# ---------------------------------------------------------------------------

def sync_task_source() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "app/tasks/integrations.py").read_text()


def test_the_scheduled_poll_goes_through_the_breaker_like_a_push():
    """The poll used to call the connector directly.

    So a vendor that had stopped answering failed here every fifteen minutes and
    the only trace was `last_sync_error` -- a column no health surface reads.
    Health went on saying "working" from whatever push last succeeded, the daily
    sweep was the first thing to notice, and until it ran the badge was green
    while nothing came back. Now it is the same guard, the same row and the same
    breaker as a resident's report.
    """
    source = sync_task_source()
    block = source[source.index("def pull_integration_updates("):]
    block = block[:block.index("@celery_app.task", 1)]
    assert "await guard(" in block
    assert "health_key(platform)" in block
    assert "db=db" in block
    assert "await connector.pull_updates(" not in block, "the poll still calls the vendor directly"


def test_a_paused_vendor_is_not_counted_as_a_fresh_poll_failure():
    """`guard` declines the call rather than making it. Counting that as a new
    failure would inflate the number that decides blip from outage, on evidence
    nobody gathered."""
    source = sync_task_source()
    block = source[source.index("def pull_integration_updates("):]
    block = block[:block.index("@celery_app.task", 1)]
    assert "except CircuitOpen" in block
    handler = block[block.index("except CircuitOpen"):]
    handler = handler[:handler.index("except Exception")]
    assert "record_failure" not in handler


@pytest.mark.parametrize("task,operation", [
    ("pull_integration_comments", "pull_comments"),
    ("sync_integration_assets", "sync_assets"),
])
def test_the_other_beat_jobs_record_their_failures_too(task, operation):
    """A connector whose comment poll 404s every fifteen minutes is a connector
    that is not working, and these paths wrote a sync-log line and nothing else."""
    source = sync_task_source()
    block = source[source.index(f"def {task}("):]
    assert "connector_health.record_failure(" in block
    # `health_key(platform)`, from a local read before the try block: the
    # handler runs after a rollback, which expires the ORM instance, and
    # `integration.platform` there raises under the async engine.
    assert "health_key(platform)" in block
    assert "health_key(integration.platform)" not in block


def test_the_pull_loops_do_not_shadow_their_own_task_parameter():
    """Reassigning `integration_id` inside the loop makes the name local to
    the entire closure -- Python scoping, not control flow -- so the
    `if integration_id is not None` filter at the top raised
    UnboundLocalError before the first query. Both pull tasks died on every
    beat tick and every manual "Check for updates", while trigger_sync still
    answered "Sync started". The loop-local must be a different name."""
    import ast
    from pathlib import Path

    source = Path("app/tasks/integrations.py").read_text()
    tree = ast.parse(source)
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in func.args.args}
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                for target in ast.walk(node):
                    if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                        assert target.id != "integration_id" or "integration_id" not in params or func.name in (
                            # top-level rebinding of a parameter before any read is fine;
                            # the bug is rebinding it inside a nested closure that also
                            # reads the outer value first.
                        ), (
                            f"{func.name} rebinds its own `integration_id` parameter -- "
                            "use a different loop-local (see row_id in sync_integration_assets)"
                        )
