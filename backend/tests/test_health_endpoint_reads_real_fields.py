"""The health page 500'd on a field that was never on the object.

`alert_muted_until` was added as a column, a migration and a mute endpoint --
but not to the `Health` dataclass that the read path builds. `/connectors/health`
does `h.alert_muted_until` for every row, a dataclass has no such attribute, and
so the endpoint raised AttributeError and returned 500. Every time, for
everyone, from the moment the mute feature landed.

What that looks like on screen is nothing to do with muting: a banner saying
"the status of these services could not be read", and every provider card
falling back to "not checked yet" -- because they all hydrate from that one
response. Two of the three symptoms reported as separate bugs were this.

Nothing caught it because no test reads the endpoint (CI has no database) and
the dataclass and its reader are in different files. So this compares them
directly: every attribute the handler touches has to exist on the object the
handler is given.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

from app.services.connector_health import Health

ROOT = Path(__file__).resolve().parents[1]


def _handler_source(name: str) -> str:
    tree = ast.parse((ROOT / "app/api/system.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.unparse(node)
    pytest.fail(f"{name} is no longer in system.py")


def _known_names() -> set:
    fields = {f.name for f in dataclasses.fields(Health)}
    return fields | {n for n in dir(Health) if not n.startswith("_")}


def test_the_health_endpoint_only_reads_fields_that_exist():
    """One missing attribute takes the entire page down, not one row: the
    comprehension raises on the first connector and nothing is returned."""
    source = _handler_source("connector_health_report")
    tree = ast.parse(source)
    read = {
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == "h"
    }
    missing = read - _known_names()
    assert not missing, (
        f"/connectors/health reads {sorted(missing)} off Health, which does not have it -- "
        f"this returns 500 for every connector on every request"
    )


def test_the_mute_state_survives_the_read():
    """Adding the field but leaving `to_health` alone would fix the crash and
    keep the bug: alerts would report as never muted, however recently somebody
    muted them. A mute that silences the email and leaves no trace on screen is
    indistinguishable from the alerting being broken."""
    from datetime import datetime, timezone

    from app.services.connector_health import to_health

    when = datetime(2026, 8, 9, tzinfo=timezone.utc)

    class Row:
        connector = "sms"
        status = "working"
        provider = "twilio"
        last_success_at = None
        last_error_at = None
        last_error = None
        consecutive_failures = 0
        total_successes = 1
        total_failures = 0
        alert_muted_until = when

    assert to_health(Row()).alert_muted_until == when


def test_a_row_without_the_column_still_reads():
    """Mid-migration, the column may not be there. Degrading to "not muted"
    keeps the page up; raising takes it down for a connector nobody muted."""
    class Row:
        connector = "sms"
        status = "working"

    from app.services.connector_health import to_health

    assert to_health(Row()).alert_muted_until is None
