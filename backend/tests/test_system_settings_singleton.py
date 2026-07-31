"""The settings row a save writes must be the row the next read returns.

Regression test for a reported bug -- "the state I choose for the retention
policy isn't persisting" -- whose cause was not in the retention code at all.
"""

from app.services.system_settings import merge_into_canonical, pick_canonical


class Row:
    def __init__(self, id, **kw):
        self.id = id
        for k, v in kw.items():
            setattr(self, k, v)
    def __repr__(self):
        return f"Row({self.id})"


COLUMNS = ("retention_state_code", "retention_mode", "retention_days_override", "public_origin")


def row(id, **kw):
    base = {c: None for c in COLUMNS}
    base.update(kw)
    return Row(id, **base)


def test_the_same_row_comes_back_whatever_order_the_database_offers():
    """The bug in one line. An unordered LIMIT 1 lets PostgreSQL return
    whichever row is cheapest, and UPDATE moves a row in the heap -- so the
    read after a write could legitimately return a different row."""
    rows = [row(1), row(2), row(3)]
    assert pick_canonical(rows).id == 1
    assert pick_canonical(list(reversed(rows))).id == 1
    assert pick_canonical([rows[1], rows[2], rows[0]]).id == 1


def test_no_rows_is_not_an_error():
    assert pick_canonical([]) is None


def test_the_oldest_row_wins_not_the_newest():
    """The first row is the one the deployment has been reading its whole life,
    so it holds what the town configured. A duplicate created later by a racing
    request holds defaults, and preferring it would swap real configuration for
    an empty row."""
    configured = row(1, retention_state_code="NJ", retention_mode="delete")
    empty = row(2)
    assert pick_canonical([empty, configured]) is configured


def test_merging_keeps_every_value_somebody_typed():
    """Deleting duplicates without folding them in would discard configuration
    that is, from the town's point of view, simply saved."""
    canonical = row(1, retention_state_code="NJ")
    stray = row(2, retention_mode="delete", public_origin="https://town.gov")
    winner, spare = merge_into_canonical([canonical, stray], COLUMNS)
    assert winner is canonical
    assert winner.retention_state_code == "NJ"
    assert winner.retention_mode == "delete"
    assert winner.public_origin == "https://town.gov"
    assert [r.id for r in spare] == [2]


def test_merging_never_overwrites_an_answer_that_is_already_there():
    canonical = row(1, retention_mode="anonymize")
    stray = row(2, retention_mode="delete")
    winner, _ = merge_into_canonical([canonical, stray], COLUMNS)
    assert winner.retention_mode == "anonymize"


def test_the_earlier_duplicate_wins_a_tie():
    canonical = row(1)
    second = row(2, retention_mode="delete")
    third = row(3, retention_mode="anonymize")
    winner, spare = merge_into_canonical([third, canonical, second], COLUMNS)
    assert winner.retention_mode == "delete"
    assert sorted(r.id for r in spare) == [2, 3]


def test_a_single_row_merges_to_itself_with_nothing_spare():
    only = row(1, retention_state_code="NY")
    winner, spare = merge_into_canonical([only], COLUMNS)
    assert winner is only and spare == []


def test_every_read_of_the_settings_row_is_ordered():
    """The module-level guarantee. A new `select(SystemSettings).limit(1)`
    anywhere reintroduces the bug, so the accessor has to be the only way in.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "system_settings.py":
            continue
        text = path.read_text()
        for m in re.finditer(r"select\(SystemSettings\)([^\n]*)", text):
            tail = m.group(1)
            if "order_by" not in tail:
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(root)}:{line}")
    assert not offenders, (
        "unordered reads of the settings singleton -- these can return a "
        "different row than the one just written:\n  " + "\n  ".join(offenders)
    )
