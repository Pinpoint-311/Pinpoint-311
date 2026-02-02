"""Add translations table for database-cached translations

Revision ID: add_translations_table
Revises: 
Create Date: 2026-02-02
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_translations_table'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create translations table for caching Google Translate API results
    op.create_table(
        'translations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_text', sa.Text(), nullable=False),
        sa.Column('source_lang', sa.String(length=10), nullable=False, server_default='en'),
        sa.Column('target_lang', sa.String(length=10), nullable=False),
        sa.Column('translated_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for faster lookups
    op.create_index('ix_translations_source_text', 'translations', ['source_text'], unique=False)
    op.create_index('ix_translations_target_lang', 'translations', ['target_lang'], unique=False)
    
    # Create composite index for the common lookup pattern
    op.create_index(
        'ix_translations_lookup',
        'translations',
        ['source_text', 'target_lang'],
        unique=False
    )


def downgrade():
    op.drop_index('ix_translations_lookup', table_name='translations')
    op.drop_index('ix_translations_target_lang', table_name='translations')
    op.drop_index('ix_translations_source_text', table_name='translations')
    op.drop_table('translations')
