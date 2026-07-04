"""add govtech integration tables

Revision ID: a1b2c3d4e5f6
Revises: 3348fc927232
Create Date: 2026-07-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '3348fc927232'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'integration_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('platform', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('credentials', sa.Text(), nullable=True),
        sa.Column('sync_direction', sa.String(length=20), nullable=False, server_default='push'),
        sa.Column('webhook_token', sa.String(length=64), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(length=20), nullable=True),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('webhook_token'),
    )
    op.create_index(op.f('ix_integration_configs_id'), 'integration_configs', ['id'], unique=False)
    op.create_index(op.f('ix_integration_configs_platform'), 'integration_configs', ['platform'], unique=False)
    op.create_index(op.f('ix_integration_configs_webhook_token'), 'integration_configs', ['webhook_token'], unique=False)

    op.create_table(
        'integration_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('integration_id', sa.Integer(), nullable=False),
        sa.Column('service_request_id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(length=200), nullable=False),
        sa.Column('external_status', sa.String(length=50), nullable=True),
        sa.Column('direction', sa.String(length=10), nullable=True, server_default='pushed'),
        sa.Column('last_pushed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_pulled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['integration_id'], ['integration_configs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_request_id'], ['service_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_integration_links_id'), 'integration_links', ['id'], unique=False)
    op.create_index(op.f('ix_integration_links_integration_id'), 'integration_links', ['integration_id'], unique=False)
    op.create_index(op.f('ix_integration_links_service_request_id'), 'integration_links', ['service_request_id'], unique=False)
    op.create_index(op.f('ix_integration_links_external_id'), 'integration_links', ['external_id'], unique=False)

    op.create_table(
        'integration_sync_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('integration_id', sa.Integer(), nullable=False),
        sa.Column('operation', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('request_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['integration_id'], ['integration_configs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_integration_sync_logs_id'), 'integration_sync_logs', ['id'], unique=False)
    op.create_index(op.f('ix_integration_sync_logs_integration_id'), 'integration_sync_logs', ['integration_id'], unique=False)
    op.create_index(op.f('ix_integration_sync_logs_created_at'), 'integration_sync_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('integration_sync_logs')
    op.drop_table('integration_links')
    op.drop_table('integration_configs')
