"""drop integration_links.documents_pushed, which nothing has ever read

Written in two places by the document push and read in none -- not by a task,
not by an endpoint, not by the admin UI. `documents_pushed_count` says
everything it said and more: the boolean cannot distinguish "no photos on this
report" from "three photos, all attached", and the count is what the push path
actually resolves against.

Deliberately a separate revision from 7d73fe63d6e3. A drop_column is classified
DESTRUCTIVE by app/db/migrate.py, so it halts the container until an operator
sets PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION=1. Bundling it with the
documents_pushed_count fix would have held the urgent correctness change --
document pushes raising UndefinedColumn on every Alembic-only deployment --
behind that manual step. The fix applies unattended; this tidy-up waits for
somebody to say yes, which for a column drop is the right way round.

Guarded by inspection: the model no longer carries the column, so a
create_all-provisioned database arrives here without it and an unguarded drop
would fail on a schema that is already correct.

Nothing is lost that anything can miss: no code path has ever read the value.

Revision ID: a7029676a2bc
Revises: 7d73fe63d6e3
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7029676a2bc"
down_revision: Union[str, None] = "7d73fe63d6e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    if "integration_links" not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns("integration_links")}


def upgrade() -> None:
    if "documents_pushed" in _columns():
        op.drop_column("integration_links", "documents_pushed")


def downgrade() -> None:
    if "documents_pushed" not in _columns():
        op.add_column(
            "integration_links",
            sa.Column("documents_pushed", sa.Boolean(), nullable=True,
                      server_default=sa.text("false")),
        )
