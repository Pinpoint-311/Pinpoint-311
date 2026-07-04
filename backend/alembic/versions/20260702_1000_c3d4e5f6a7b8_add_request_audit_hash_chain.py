"""add request audit log hash chain (immutable/tamper-evident)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('request_audit_logs', sa.Column('previous_hash', sa.String(length=64), nullable=True))
    op.add_column('request_audit_logs', sa.Column('entry_hash', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('request_audit_logs', 'entry_hash')
    op.drop_column('request_audit_logs', 'previous_hash')
