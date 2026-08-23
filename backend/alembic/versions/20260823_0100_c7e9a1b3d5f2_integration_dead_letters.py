"""a failed outbound sync is kept, not logged and forgotten

A push to a connected govtech platform that failed wrote one row to
`integration_sync_logs` and stopped there. That table is an audit trail --
nothing reads it back and nothing retries from it -- so a resident's report
that could not reach the county during a twenty-minute vendor outage simply
never arrived, and the only trace was a line in a drawer nobody opens.

`integration_dead_letters` is the backlog: one open row per piece of work that
still needs to go out, with the attempt count, the scrubbed error, and when to
try again. Rows leave it two ways -- the replay succeeds, or an administrator
decides it should not be sent -- and never by being quietly dropped, which is
the failure the table exists to prevent.

The unique constraint is load-bearing rather than tidiness: the push path and
the retry loop can both be inserting for the same failure at the same moment,
and without it the same report appears in the backlog twice and is pushed
twice when the vendor recovers.

No PII is stored. Replay re-reads the ServiceRequest and rebuilds the payload,
so this table holds identifiers and a status note -- not a second copy of a
resident's name and phone with its own retention story.

Purely additive: one new table, nothing existing is touched, so a town can run
the new image before or after this applies. The push path treats a missing
table as "no backlog available" and falls back to the old log-only behaviour
rather than failing the sync.

Revision ID: c7e9a1b3d5f2
Revises: b8c4d2e6f0a1
Create Date: 2026-08-23 01:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7e9a1b3d5f2'
down_revision: Union[str, None] = 'b8c4d2e6f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'integration_dead_letters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('integration_id', sa.Integer(), nullable=False),
        sa.Column('operation', sa.String(length=30), nullable=False),
        sa.Column('service_request_id', sa.Integer(), nullable=True),
        sa.Column('comment_id', sa.Integer(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('first_failed_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=True),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution', sa.String(length=20), nullable=True),
        sa.Column('resolved_by', sa.String(length=100), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['integration_id'], ['integration_configs.id'],
                                ondelete='CASCADE'),
        # Both cascade: a deleted request or comment takes its backlog with it.
        # A row whose subject is gone can never be replayed, and leaving it
        # would show the town a backlog item with nothing behind it.
        sa.ForeignKeyConstraint(['service_request_id'], ['service_requests.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['comment_id'], ['request_comments.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('integration_id', 'operation', 'service_request_id',
                            'comment_id', name='uq_dead_letter_subject'),
    )
    op.create_index(op.f('ix_integration_dead_letters_id'),
                    'integration_dead_letters', ['id'])
    op.create_index(op.f('ix_integration_dead_letters_integration_id'),
                    'integration_dead_letters', ['integration_id'])
    op.create_index(op.f('ix_integration_dead_letters_service_request_id'),
                    'integration_dead_letters', ['service_request_id'])
    op.create_index(op.f('ix_integration_dead_letters_comment_id'),
                    'integration_dead_letters', ['comment_id'])
    # The retry loop's only query: open rows whose backoff has elapsed.
    op.create_index(op.f('ix_integration_dead_letters_next_attempt_at'),
                    'integration_dead_letters', ['next_attempt_at'])
    op.create_index(op.f('ix_integration_dead_letters_resolved_at'),
                    'integration_dead_letters', ['resolved_at'])


def downgrade() -> None:
    op.drop_table('integration_dead_letters')
