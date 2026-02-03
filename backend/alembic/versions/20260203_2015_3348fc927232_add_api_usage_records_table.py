"""add_api_usage_records_table

Revision ID: 3348fc927232
Revises: 2237fb926131
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3348fc927232'
down_revision: Union[str, None] = '2237fb926131'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'api_usage_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('service_name', sa.String(length=100), nullable=False),
        sa.Column('operation', sa.String(length=100), nullable=True),
        sa.Column('tokens_input', sa.Integer(), nullable=True, default=0),
        sa.Column('tokens_output', sa.Integer(), nullable=True, default=0),
        sa.Column('characters', sa.Integer(), nullable=True, default=0),
        sa.Column('api_calls', sa.Integer(), nullable=True, default=1),
        sa.Column('request_id', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_api_usage_records_id'), 'api_usage_records', ['id'], unique=False)
    op.create_index(op.f('ix_api_usage_records_service_name'), 'api_usage_records', ['service_name'], unique=False)
    op.create_index(op.f('ix_api_usage_records_request_id'), 'api_usage_records', ['request_id'], unique=False)
    op.create_index(op.f('ix_api_usage_records_created_at'), 'api_usage_records', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_api_usage_records_created_at'), table_name='api_usage_records')
    op.drop_index(op.f('ix_api_usage_records_request_id'), table_name='api_usage_records')
    op.drop_index(op.f('ix_api_usage_records_service_name'), table_name='api_usage_records')
    op.drop_index(op.f('ix_api_usage_records_id'), table_name='api_usage_records')
    op.drop_table('api_usage_records')
