"""Add the connector_health table.

One row per integration, updated in place: this is operational state, not
history. Per-call history belongs in the audit log and would grow without
bound here for no added answer.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "connector_health" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "connector_health",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connector", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_successes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    # Unique, because two rows for one connector would mean two answers to
    # "is this working" and no way to choose.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_connector_health_connector "
               "ON connector_health (connector)")


def downgrade() -> None:
    op.drop_table("connector_health")
