"""add legal_hold and managed_policy to system_settings

Instance-wide legal hold (suspends all retention purging) and the state-pushed
managed policy marker, so the hosting control plane's retention/legal-hold
policy actually takes effect and locks the matching town settings.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-03 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'system_settings',
        sa.Column('legal_hold', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.add_column(
        'system_settings',
        sa.Column('managed_policy', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('system_settings', 'managed_policy')
    op.drop_column('system_settings', 'legal_hold')
