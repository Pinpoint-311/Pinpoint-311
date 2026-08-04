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
at a deployment that has been running for a year: a settings row older than a
day with any credential stored is not a fresh install. A town in its first day
gets the guide, which is what it is for.

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
    # `updated_at` is the only age this table carries. A row that has never been
    # written since creation has NULL there, which reads as "new" -- the safe
    # direction, because the cost of being wrong is a guide somebody dismisses.
    conn.execute(sa.text("""
        UPDATE system_settings
           SET setup_completed_at = COALESCE(updated_at, NOW())
         WHERE updated_at < NOW() - INTERVAL '1 day'
           AND EXISTS (SELECT 1 FROM system_secrets WHERE is_configured IS TRUE)
    """))


def downgrade() -> None:
    op.drop_column("system_settings", "setup_completed_at")
