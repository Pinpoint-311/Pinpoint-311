"""Add client_error_log.

Browser crashes were only ever written to the application log, which for a
self-hosted town means the error screen's promise of a report resolved to
nowhere. Persisted so the admin console can show them.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "client_error_log" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "client_error_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("component_stack", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    # Both hot paths: dedupe looks up by fingerprint, the admin list and the
    # pruner both order by last_seen_at.
    op.execute("CREATE INDEX IF NOT EXISTS ix_client_error_fingerprint "
               "ON client_error_log (fingerprint)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_client_error_last_seen "
               "ON client_error_log (last_seen_at)")


def downgrade() -> None:
    op.drop_table("client_error_log")
