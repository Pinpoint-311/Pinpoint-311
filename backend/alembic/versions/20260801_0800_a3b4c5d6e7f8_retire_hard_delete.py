"""Retire hard deletion; the strongest retention mode clears every field.

`delete` called `db.delete(record)` while `request_audit_logs` and
`request_comments` hold NOT NULL foreign keys back to it with no cascade. The
flush failed on every record -- submitting a request writes an audit entry, so
every record has one -- and each failure was caught per record, leaving the run
to report success with nothing archived. A town on a delete policy was told
retention was running, and nothing was ever removed.

Making it succeed meant deleting the audit rows, and those form a hash chain
the compliance page advertises as tamper-evident. Removing rows from the middle
makes the verify endpoint report tampering, correctly, for a deletion that was
entirely legitimate.

`purge` clears every field instead. The personal data is gone, the row survives
as a shell that still counts in statistics, and the audit chain stays whole.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "system_settings"


def _has(column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return False
    return column in {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    if not _has("retention_mode"):
        return
    # A town set to `delete` asked for the strongest available option, and gets
    # it. What changes is that it now works.
    op.execute(
        sa.text(
            f'UPDATE "{TABLE}" SET retention_mode = :new '  # nosec B608 - fixed identifier
            f"WHERE retention_mode = :old"
        ).bindparams(new="purge", old="delete")
    )


def downgrade() -> None:
    if not _has("retention_mode"):
        return
    op.execute(
        sa.text(
            f'UPDATE "{TABLE}" SET retention_mode = :old '  # nosec B608 - fixed identifier
            f"WHERE retention_mode = :new"
        ).bindparams(new="purge", old="delete")
    )
