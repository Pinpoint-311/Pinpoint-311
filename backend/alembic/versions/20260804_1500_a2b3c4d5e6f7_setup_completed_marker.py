"""Record that somebody finished setting this town up.

Nothing detected a fresh install. `SetupIntegrationsPage` is a tab inside the
admin console and it opened its guide when sign-in or maps happened to be
unconfigured -- which is a proxy for "is everything set up", and wrong in the
direction that matters. A town that deliberately switches most things off never
satisfies it, so the guide would greet it on every login forever, and a banner
that never goes away is one people stop reading. In the other direction, an
install where those two happen to be pre-seeded gets no guide at all.

Being finished is a thing a person says. NULL means nobody has said it.

Backfilled for towns that are plainly past setup, so this does not open a guide
at a deployment that has been running for a year. The evidence is that somebody
has already used the thing: a stored credential, or a report taken. A fresh
install has neither -- `init_db` seeds every secret row with
`is_configured=False`, so a configured one is always something a person entered.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    conn = op.get_bind()
    # Not the row's age. `updated_at` was the first thing tried here and it
    # measures the wrong thing -- it moves whenever anything on the settings row
    # changes, so a town that has been running for a year and adjusted a setting
    # this morning reads as brand new. Tested against a copy of a live database,
    # where it did exactly that.
    #
    # Evidence that somebody has used this deployment, then: a credential
    # entered, or a report taken. Timestamped from `updated_at` where there is
    # one, because a real date beats NOW() for a thing that happened earlier.
    conn.execute(sa.text("""
        UPDATE system_settings
           SET setup_completed_at = COALESCE(updated_at, NOW())
         WHERE EXISTS (SELECT 1 FROM system_secrets WHERE is_configured IS TRUE)
            OR EXISTS (SELECT 1 FROM service_requests)
    """))


def downgrade() -> None:
    op.drop_column("system_settings", "setup_completed_at")
