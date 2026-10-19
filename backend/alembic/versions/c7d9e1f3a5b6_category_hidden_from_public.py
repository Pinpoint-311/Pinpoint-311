"""A service category can be kept off the public map and list.

Revision ID: c7d9e1f3a5b6
Revises: b3d5f7a9c1e2
Create Date: 2026-10-17

Additive: one boolean column on service_definitions, NOT NULL with a server
default of false, so every existing category stays exactly as public as it was.
The rule is applied at query time in services/public_visibility.py; no report
row is written.
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d9e1f3a5b6"
down_revision = "b3d5f7a9c1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_definitions",
        sa.Column("hidden_from_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("service_definitions", "hidden_from_public")
