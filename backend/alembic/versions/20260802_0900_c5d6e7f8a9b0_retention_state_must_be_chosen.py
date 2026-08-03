"""Stop defaulting records retention to New Jersey.

``retention_state_code`` defaulted to ``NJ``, so a town that never opened the
compliance tab ran a seven-year OPRA schedule regardless of which state it is
in. That is not cosmetic: it decides when resident records are anonymised or
purged, and which public-records law is cited for doing it.

The judgement call is what to do with rows that already say ``NJ``. There is no
way to tell a town that chose New Jersey from one that inherited it, so:

  * The stored value is left exactly as it is. Nothing breaks, no town loses a
    setting it deliberately made, and the console can still show what is there
    in order to ask about it.
  * A new ``retention_state_confirmed`` column starts ``false`` for every
    existing row. Until an administrator confirms the state, retention pauses —
    nothing is archived, nothing is deleted — and the console reports the
    capability as not configured.

The cost is that towns legitimately in New Jersey also pause until somebody
clicks confirm. That is a visible, reversible pause on a screen that explains
itself, weighed against records already being destroyed on the wrong state's
schedule in every town outside New Jersey. Fresh installs are unaffected: they
have no state at all and were always going to have to choose one.

Also backfills ``retention_mode``. It is NULL on rows written before that column
gained its default; every read already routes through ``normalise_mode``, which
reads NULL as ``redact``, so this only makes the stored value agree with the
behaviour rather than changing it.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "system_settings"
COLUMN = "retention_state_confirmed"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return  # fresh install: created from the models, already complete

    cols = {c["name"]: c for c in inspector.get_columns(TABLE)}

    if COLUMN not in cols:
        # Not null with a server default, so the flag is never ambiguous: every
        # row is either confirmed or explicitly not, and there is no third
        # state to guess at later.
        op.add_column(TABLE, sa.Column(
            COLUMN, sa.Boolean(), nullable=False, server_default=sa.text("false"),
        ))

    # The Python-side default never reached the database, but a server default
    # would keep re-applying NJ to rows this migration is trying to make honest.
    if "retention_state_code" in cols:
        op.alter_column(TABLE, "retention_state_code",
                        existing_type=sa.String(length=2),
                        server_default=None,
                        nullable=True)

    if "retention_mode" in cols:
        op.execute(
            sa.text(
                f'UPDATE "{TABLE}" SET retention_mode = :mode '  # nosec B608 - fixed identifier
                f"WHERE retention_mode IS NULL"
            ).bindparams(mode="redact")
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return
    cols = {c["name"] for c in inspector.get_columns(TABLE)}

    if COLUMN in cols:
        op.drop_column(TABLE, COLUMN)

    # Restoring the default is the point of the downgrade — it is what the old
    # code expects to be there. Rows with no state get one back, because the
    # code being reverted to cannot cope with NULL.
    if "retention_state_code" in cols:
        op.execute(
            sa.text(
                f'UPDATE "{TABLE}" SET retention_state_code = :code '  # nosec B608 - fixed identifier
                f"WHERE retention_state_code IS NULL"
            ).bindparams(code="NJ")
        )
