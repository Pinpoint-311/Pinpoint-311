"""the vendor's own codes, kept locally so a mapping can be picked not typed

A status or service-code mapping is a promise about codes that live in the
vendor's *data* -- this town's Accela service codes, this ArcGIS layer's status
domain. Nothing published anywhere says what they are, so the setup form asked
an admin to type them from memory or from an email, and a typo is not an error:
it is a status that silently never maps, or a 422 on the first real report.

Four additive columns on `integration_configs`:

  * `lookups_cache` / `lookups_fetched_at` -- the lists pulled from the vendor
    while we had their credentials, so the admin picks from their own live
    codes. Deliberately its own column rather than a key inside `config`:
    `config` is the admin-writable blob with an allowlist on every key, and a
    value that exists to check the admin's input must not be settable by them.
  * `mapping_approved_at` / `mapping_approved_by` -- an empty mapping somebody
    deliberately approved (the vendor's words happen to match ours) and one
    nobody has ever opened are indistinguishable in the config blob, and only
    one of them is a decision.

Purely additive and all four nullable, so a town can run the new image before
or after this applies; every read is guarded and degrades to "no lookups yet",
which is also the honest state for a vendor that publishes no such list.

Revision ID: d8f0b2c4e6a3
Revises: c7e9a1b3d5f2
Create Date: 2026-08-23 02:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd8f0b2c4e6a3'
down_revision: Union[str, None] = 'c7e9a1b3d5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('integration_configs',
                  sa.Column('lookups_cache', sa.JSON(), nullable=True))
    op.add_column('integration_configs',
                  sa.Column('lookups_fetched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('integration_configs',
                  sa.Column('mapping_approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('integration_configs',
                  sa.Column('mapping_approved_by', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('integration_configs', 'mapping_approved_by')
    op.drop_column('integration_configs', 'mapping_approved_at')
    op.drop_column('integration_configs', 'lookups_fetched_at')
    op.drop_column('integration_configs', 'lookups_cache')
