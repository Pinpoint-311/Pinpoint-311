"""separate the legal hold from the content-moderation flag

`ServiceRequest.flagged` carried two unrelated meanings at once. Content
moderation sets it when mild profanity turns up -- including profanity in a
PUBLIC COMMENT, which is an unauthenticated endpoint by design. Retention read
the same column as "under legal hold" and skipped those rows forever, and the
admin console listed them as records somebody had placed a hold on.

The result was that any anonymous visitor could permanently exempt another
resident's name, email, phone and address from the town's retention policy by
posting a rude comment on their report -- and could do it to any report on the
public map, one comment at a time.

`legal_hold` is the hold; `flagged` goes back to meaning only "a human should
look at this".

Existing rows: every currently-flagged row is copied to legal_hold. That is
deliberately the conservative direction. Some of those holds were placed by an
administrator and some are moderation noise, and this migration cannot tell
them apart -- but a record wrongly held is a record an admin can release with
one click, while a record wrongly released may already have been scrubbed by
the next retention run, and nothing brings that back.

Additive with a server default, so the previous build runs against this schema
unchanged (expand; MIN_DB_REVISION stays where it is).

Revision ID: a1c2e3f4b5d6
Revises: f6b4d8e2a3c5
Create Date: 2026-08-19 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c2e3f4b5d6'
down_revision: Union[str, None] = 'b8c4d2e6f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'service_requests',
        sa.Column('legal_hold', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_index(
        'ix_service_requests_legal_hold', 'service_requests', ['legal_hold']
    )
    # Carry every existing hold across, erring toward keeping records.
    op.execute(
        "UPDATE service_requests SET legal_hold = true WHERE flagged = true"
    )


def downgrade() -> None:
    op.drop_index('ix_service_requests_legal_hold', table_name='service_requests')
    op.drop_column('service_requests', 'legal_hold')
