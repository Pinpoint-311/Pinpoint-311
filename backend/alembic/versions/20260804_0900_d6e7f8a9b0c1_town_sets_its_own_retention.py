"""Retire the state columns; the retention period is the town's own number.

The previous migration (c5d6e7f8a9b0) stopped the product from *defaulting* the
state. This one stops it from having an opinion about states at all.

Behind ``retention_state_code`` sat a table of retention periods and public
records statutes for all 51 US jurisdictions that nobody had verified — 41 of
the 51 periods were five years, so one number was wearing 51 different
citations — plus a fallback claiming that towns outside the table were governed
by Federal FOIA, which applies to federal agencies and not to municipal
records. A municipality's retention schedule is approved by its state archives
and its clerk holds the document. We were guessing at it and rendering the
guess as research.

So:

  * ``retention_state_code`` and ``retention_state_confirmed`` are dropped.
    Confirmation had exactly one job — telling a stored ``NJ`` that a human
    chose from one that a column default wrote — and nothing is inherited any
    more for a human to confirm.
  * ``retention_days_override`` becomes ``retention_days``. It was only ever an
    "override" relative to a state minimum that did not exist; the provisioning
    API has always called the same value ``retention_days``.

Every check here inspects first. The two provisioned tenant databases are
behind on migrations and never received ``retention_state_confirmed``, so a
plain ``DROP COLUMN`` fails on them outright and takes the rest of the upgrade
with it.

No data shim is needed for the values themselves. A town whose only stored
retention setting was a state now reads as unconfigured, which is correct and
is the state the setup page and the health dashboard are built to shout about:
until somebody sets a period, resident personal data is kept indefinitely.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "system_settings"
DROPPED = ("retention_state_code", "retention_state_confirmed")
OLD_DAYS = "retention_days_override"
NEW_DAYS = "retention_days"


def _columns() -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    cols = _columns()
    if not cols:
        return  # fresh install: created from the models, already correct

    # Renamed before the drops so that a database missing one of the state
    # columns still gets the rename it does need.
    if OLD_DAYS in cols and NEW_DAYS not in cols:
        op.alter_column(TABLE, OLD_DAYS, new_column_name=NEW_DAYS,
                        existing_type=sa.Integer())

    for column in DROPPED:
        if column in cols:
            op.drop_column(TABLE, column)


def downgrade() -> None:
    cols = _columns()
    if not cols:
        return

    if NEW_DAYS in cols and OLD_DAYS not in cols:
        op.alter_column(TABLE, NEW_DAYS, new_column_name=OLD_DAYS,
                        existing_type=sa.Integer())

    # Restored empty, and deliberately not backfilled with a state. The code
    # being reverted to reads NULL as "not configured" and pauses retention,
    # which is the safe direction; inventing a state on the way back down would
    # restart destruction on a schedule nobody chose, which is the exact
    # failure this whole line of migrations exists to end.
    if "retention_state_code" not in cols:
        op.add_column(TABLE, sa.Column("retention_state_code", sa.String(length=2),
                                       nullable=True))
    if "retention_state_confirmed" not in cols:
        op.add_column(TABLE, sa.Column("retention_state_confirmed", sa.Boolean(),
                                       nullable=False, server_default=sa.text("false")))
