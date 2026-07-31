"""Remember which connector alerts have already been sent.

The daily sweep knew when an integration broke and told nobody, because there
was nowhere to record that a message had gone out -- so the only safe options
were silence or the same email every morning. These two columns are what make
"say it when it changes, and at most weekly after that" possible.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "connector_health"


def _columns() -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    existing = _columns()
    if not existing:
        # The table itself is created from the models on a fresh install, and
        # will already carry both columns.
        return
    if "alerted_level" not in existing:
        op.add_column(TABLE, sa.Column("alerted_level", sa.String(length=16), nullable=True))
    if "alerted_at" not in existing:
        op.add_column(TABLE, sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    existing = _columns()
    if "alerted_at" in existing:
        op.drop_column(TABLE, "alerted_at")
    if "alerted_level" in existing:
        op.drop_column(TABLE, "alerted_level")
