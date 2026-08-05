"""integration_links.documents_pushed_count, and one integration per platform

Two schema facts the models asserted and the migration chain did not.

`documents_pushed_count` has been on the model since photos-added-after-the-push
started syncing, and it is written and read on every document push. It reached
the chain only through the ad-hoc `ALTER TABLE ... IF NOT EXISTS` list in
init_db.py, which a deployment that migrates rather than create_all()s never
runs. Those deployments got UndefinedColumn on the first photo attached to a
work order -- and because the push path catches and logs its own errors, the
photo simply never arrived and the sync log said so where nobody was looking.

`platform` was indexed but not uniquely, while the create endpoint does a
SELECT-then-INSERT. Two admins connecting Accela at the same time produced two
enabled rows for one platform, and from then on every resident report was pushed
to the county twice, as two records, with two work orders opened against them.

A pre-existing duplicate makes the unique index fail rather than being resolved
here: which of two integration rows a town keeps -- with its credentials, its
webhook token and the links hanging off it -- is not a decision a migration
should make at 3am. If this revision stops on a duplicate, find them with

    SELECT platform, count(*) FROM integration_configs
    GROUP BY platform HAVING count(*) > 1;

delete the row with no integration_links, and re-run.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default matches the model's default=0 so rows written before this
    # revision read as "no documents pushed yet" rather than NULL, which the
    # push path would otherwise have to treat as zero anyway.
    op.add_column(
        "integration_links",
        sa.Column("documents_pushed_count", sa.Integer(), nullable=True,
                  server_default=sa.text("0")),
    )

    op.drop_index(op.f("ix_integration_configs_platform"), table_name="integration_configs")
    op.create_index(
        op.f("ix_integration_configs_platform"), "integration_configs", ["platform"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_integration_configs_platform"), table_name="integration_configs")
    op.create_index(
        op.f("ix_integration_configs_platform"), "integration_configs", ["platform"],
        unique=False,
    )
    op.drop_column("integration_links", "documents_pushed_count")
