"""Let an administrator mute alerts for a connector they already know about.

Without this the only way to stop a daily reminder about a known problem is to
fix it or to filter the sender, and the second takes the next unrelated alert
with it.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "connector_health"
COLUMNS = (
    ("alert_muted_until", lambda: sa.Column("alert_muted_until", sa.DateTime(timezone=True), nullable=True)),
    ("alert_muted_level", lambda: sa.Column("alert_muted_level", sa.String(length=16), nullable=True)),
)


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    existing = _columns()
    if not existing:
        return  # fresh install: created from the models, already complete
    for name, make in COLUMNS:
        if name not in existing:
            op.add_column(TABLE, make())


def downgrade() -> None:
    existing = _columns()
    for name, _ in reversed(COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
