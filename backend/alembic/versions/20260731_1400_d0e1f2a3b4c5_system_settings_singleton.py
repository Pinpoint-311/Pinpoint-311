"""Collapse duplicate system_settings rows and keep it to one.

The table is a singleton by convention only. Seven code paths create it with a
non-atomic read-then-insert, so two concurrent requests on a fresh deployment
produce two rows -- and from then on an unordered `LIMIT 1` can read a
different row than the one just written. The visible symptom is a saved setting
that reverts on reload.

Ordering every read (done in the same change) makes the behaviour deterministic
even with duplicates present. This closes the other half: existing duplicates
are folded into the oldest row, and a constraint stops new ones appearing.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "system_settings"
INDEX = "uq_system_settings_singleton"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    columns = [c["name"] for c in inspector.get_columns(TABLE)]
    if "id" not in columns:
        return

    # Reflected, so the statements below are built from SQLAlchemy objects
    # rather than from formatted strings. The identifiers here come from the
    # database rather than from a request, but SQL assembled by string
    # formatting is worth avoiding on sight -- it is indistinguishable, to a
    # reader and to a scanner, from the version of this that is a vulnerability.
    table = sa.Table(TABLE, sa.MetaData(), autoload_with=bind)
    value_columns = [c for c in table.columns if c.name != "id"]

    ids = [row[0] for row in bind.execute(sa.select(table.c.id).order_by(table.c.id))]
    if len(ids) > 1:
        keep, drop = ids[0], ids[1:]
        # Carry over anything the duplicates hold that the canonical row does
        # not. A value on a duplicate is still a value somebody typed into this
        # product; deleting the row without this would discard configuration.
        #
        # Oldest duplicate first, so an earlier answer beats a later one --
        # the same tie-break as choosing the row to keep.
        for column in value_columns:
            source = bind.execute(
                sa.select(column)
                .where(sa.and_(table.c.id.in_(drop), column.isnot(None)))
                .order_by(table.c.id)
                .limit(1)
            ).scalar()
            if source is not None:
                bind.execute(
                    sa.update(table)
                    .where(sa.and_(table.c.id == keep, column.is_(None)))
                    .values({column.name: source})
                )
        bind.execute(sa.delete(table).where(table.c.id.in_(drop)))

    # At most one row, enforced by the database rather than by every caller
    # remembering to check. A unique index on a constant expression is the
    # standard way to say "one row" in PostgreSQL.
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{INDEX}" ON "{TABLE}" ((true))'))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {INDEX}")
