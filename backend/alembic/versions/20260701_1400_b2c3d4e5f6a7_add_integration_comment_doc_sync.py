"""add integration comment/document sync tracking

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('request_comments', sa.Column('external_ref', sa.String(length=200), nullable=True))
    op.create_index(op.f('ix_request_comments_external_ref'), 'request_comments', ['external_ref'], unique=False)
    op.add_column('integration_links', sa.Column('pushed_comment_ids', sa.JSON(), nullable=True))
    op.add_column('integration_links', sa.Column('documents_pushed', sa.Boolean(), nullable=True, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('integration_links', 'documents_pushed')
    op.drop_column('integration_links', 'pushed_comment_ids')
    op.drop_index(op.f('ix_request_comments_external_ref'), table_name='request_comments')
    op.drop_column('request_comments', 'external_ref')
