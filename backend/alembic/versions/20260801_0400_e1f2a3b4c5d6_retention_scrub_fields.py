"""Let a town choose what a retention run removes.

The list was fixed in code -- names, email, phone, description, staff notes and
photos, always. A town's retention obligations come from its own counsel and its
state's records law, and this decided for them.

NULL means never configured, which is read as the old fixed list, so the first
run after this migration removes exactly what the last run before it did.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "system_settings"
COLUMN = "retention_scrub_fields"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return  # fresh install: created from the models, already complete
    if COLUMN in {c["name"] for c in inspector.get_columns(TABLE)}:
        return
    op.add_column(TABLE, sa.Column(COLUMN, sa.JSON(), nullable=True))

    # `anonymize` is not what this does. It clears the description and the
    # staff notes, which is redaction; anonymising means removing what ties
    # data to a person, and the difference matters when it is what a town tells
    # a judge. The value is migrated rather than only relabelled so that the
    # database and the screen agree.
    #
    # The code still reads `anonymize` for anyone who skips this.
    if COLUMN in {c["name"] for c in inspector.get_columns(TABLE)} or True:
        cols = {c["name"] for c in inspector.get_columns(TABLE)}
        if "retention_mode" in cols:
            op.execute(
                sa.text(
                    f'UPDATE "{TABLE}" SET retention_mode = :new '  # nosec B608 - fixed identifier
                    f"WHERE retention_mode = :old"
                ).bindparams(new="redact", old="anonymize")
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns(TABLE)}
    if "retention_mode" in cols:
        op.execute(
            sa.text(
                f'UPDATE "{TABLE}" SET retention_mode = :old '  # nosec B608 - fixed identifier
                f"WHERE retention_mode = :new"
            ).bindparams(new="redact", old="anonymize")
        )
    if COLUMN in cols:
        op.drop_column(TABLE, COLUMN)
