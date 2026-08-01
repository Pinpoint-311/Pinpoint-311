"""Keep what the last check said, not only when it happened.

A failing check stored its message in `last_error`. A passing one stored a
timestamp and nothing else, so "Twilio credentials accepted, nothing was sent"
or "SES reachable, 12 of 50,000 sent today" was shown once and gone on reload
-- leaving a card that says "checked 6 hours ago" and cannot say what it found.

And a provider that cannot be checked from here at all -- a generic HTTP SMS
gateway needs a real message sent -- recorded nothing, so that answer lived
only in the browser session that produced it. On reload the card reverted to
"not checked yet", which invites somebody to press a button that can never
succeed and makes a genuinely unchecked connector indistinguishable from one
that is unverifiable by nature.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "connector_health"
COLUMNS = (
    ("last_result", lambda: sa.Column("last_result", sa.Text(), nullable=True)),
    ("verifiable", lambda: sa.Column("verifiable", sa.Boolean(), nullable=True)),
)


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    existing = _columns()
    if not existing:
        return  # fresh install: created from the models, already complete
    for name, make in COLUMNS:
        if name not in existing:
            op.add_column(TABLE, make())

    # Backfill the one thing already known: a connector whose last check failed
    # has its message in last_error. NULL stays NULL elsewhere -- inventing a
    # result for a check that never ran would be worse than an empty line.
    if "last_error" in existing:
        op.execute(sa.text(
            f'UPDATE "{TABLE}" SET last_result = last_error '  # nosec B608 - fixed identifier
            f"WHERE last_result IS NULL AND last_error IS NOT NULL"
        ))


def downgrade() -> None:
    existing = _columns()
    for name, _ in reversed(COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
