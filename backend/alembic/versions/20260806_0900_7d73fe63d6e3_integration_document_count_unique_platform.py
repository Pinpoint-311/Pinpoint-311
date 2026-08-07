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

Everything is guarded by inspection, because init_db.py also creates the column
and the unique index at startup: a create_all-provisioned database arrives here
with both already in place, and an unguarded add_column would raise
DuplicateColumn on the first `alembic upgrade head` a town ever runs.

A pre-existing duplicate makes the unique index fail rather than being resolved
here: which of two integration rows a town keeps -- with its credentials, its
webhook token and the links hanging off it -- is not a decision a migration
should make at 3am. If this revision stops on a duplicate, find them with

    SELECT platform, count(*) FROM integration_configs
    GROUP BY platform HAVING count(*) > 1;

delete the row with no integration_links, and re-run.

Revision ID: 7d73fe63d6e3
Revises: e7f8a9b0c1d2
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7d73fe63d6e3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "ix_integration_configs_platform"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "integration_links" in tables:
        columns = {c["name"] for c in inspector.get_columns("integration_links")}
        if "documents_pushed_count" not in columns:
            # server_default matches the model's default=0 so rows written
            # before this revision read as "no documents pushed yet" rather
            # than NULL, which the push path would otherwise have to treat as
            # zero anyway.
            op.add_column(
                "integration_links",
                sa.Column("documents_pushed_count", sa.Integer(), nullable=True,
                          server_default=sa.text("0")),
            )

    if "integration_configs" in tables:
        indexes = {i["name"]: i for i in inspector.get_indexes("integration_configs")}
        existing = indexes.get(INDEX)
        if existing is not None and not existing.get("unique"):
            op.drop_index(op.f(INDEX), table_name="integration_configs")
            existing = None
        if existing is None:
            op.create_index(op.f(INDEX), "integration_configs", ["platform"],
                            unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "integration_configs" in tables:
        indexes = {i["name"] for i in inspector.get_indexes("integration_configs")}
        if INDEX in indexes:
            op.drop_index(op.f(INDEX), table_name="integration_configs")
        op.create_index(op.f(INDEX), "integration_configs", ["platform"],
                        unique=False)

    if "integration_links" in tables:
        columns = {c["name"] for c in inspector.get_columns("integration_links")}
        if "documents_pushed_count" in columns:
            op.drop_column("integration_links", "documents_pushed_count")
