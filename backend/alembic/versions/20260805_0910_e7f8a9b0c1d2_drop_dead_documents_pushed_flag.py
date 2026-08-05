"""drop integration_links.documents_pushed, which nothing has ever read

Written in two places by the document push and read in none -- not by a task,
not by an endpoint, not by the admin UI. `documents_pushed_count` says
everything it said and more: the boolean cannot distinguish "no photos on this
report" from "three photos, all attached", and the count is what the push path
actually resolves against.

Deliberately a separate revision from d6e7f8a9b0c1. A drop_column is classified
DESTRUCTIVE by app/db/migrate.py, so it halts the container until an operator
sets PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION=1. Bundling it with the
documents_pushed_count fix would have held the urgent correctness change --
document pushes raising UndefinedColumn on every Alembic-only deployment --
behind that manual step. The fix applies unattended; this tidy-up waits for
somebody to say yes, which for a column drop is the right way round.

Nothing is lost that anything can miss: no code path has ever read the value.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("integration_links", "documents_pushed")


def downgrade() -> None:
    op.add_column(
        "integration_links",
        sa.Column("documents_pushed", sa.Boolean(), nullable=True,
                  server_default=sa.text("false")),
    )
