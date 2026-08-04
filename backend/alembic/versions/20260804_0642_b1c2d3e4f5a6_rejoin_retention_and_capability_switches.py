"""Rejoin the two migration lines that grew off c5d6e7f8a9b0.

Empty on purpose. Nothing to add, alter or backfill -- this exists only so
`alembic upgrade head` has one head to reach.

Two sessions each wrote a migration whose parent was `c5d6e7f8a9b0`:

    d6e7f8a9b0c1   the town sets its own retention period and fields
    f1a2b3c4d5e6   capability switches (and a2b3c4d5e6f7 behind it)

Each branch is coherent alone, and neither could fix this by itself. The
capability-switches one tried, and had to undo it: parenting onto
`d6e7f8a9b0c1` made that branch unable to migrate at all on its own, because
`upgrade head` cannot resolve a down_revision that is not in the tree. Its
docstring says so, and says the second one in adds a merge revision. This is
that revision.

They touch different columns of `system_settings` -- `retention_*` on one side,
`capability_switches` and `setup_completed_at` on the other -- so the order they
are applied in does not matter, which is what makes an empty merge the whole of
the fix rather than the start of one.

Worth knowing when deploying: this server's database was stamped
`d6e7f8a9b0c1` from the retention branch before either was merged, so alembic
run against it from the capability-switches side alone reports "Can't locate
revision identified by 'd6e7f8a9b0c1'" and refuses to do anything. From here it
resolves, because here both parents exist.

Revision ID: b1c2d3e4f5a6
Revises: d6e7f8a9b0c1, a2b3c4d5e6f7
"""
from typing import Sequence, Union

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = ("d6e7f8a9b0c1", "a2b3c4d5e6f7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Nothing. See the module docstring."""


def downgrade() -> None:
    """Nothing to undo. Splitting the history back into two heads is not a thing
    a downgrade should arrange."""
