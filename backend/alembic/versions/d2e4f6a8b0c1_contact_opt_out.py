"""Contact opt-out on requests.

Revision ID: d2e4f6a8b0c1
Revises: c7d9e1f3a5b6
Create Date: 2026-10-18

service_requests.contact_opt_out, NOT NULL default false: every existing
   report keeps getting notifications exactly as before.

Additive only. Records where `flagged` merely mirrored a legal hold (the old
admin control wrote both) are recognized in the UI -- on hold, flagged, no
flag_reason -- rather than rewritten here, so this stays an expand migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e4f6a8b0c1"
down_revision = "c7d9e1f3a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_requests",
        sa.Column("contact_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("service_requests", "contact_opt_out")
