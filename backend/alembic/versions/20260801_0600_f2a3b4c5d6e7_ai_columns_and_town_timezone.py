"""Drop a vendor's name from provider-agnostic columns, and record the town's timezone.

`vertex_ai_summary`, `vertex_ai_classification` and `vertex_ai_analyzed_at`
were named after Google Vertex AI, which is one of five providers a town can
pick. A deployment running Azure OpenAI stored its summaries in a column
claiming otherwise -- the same mistake as the old `google_kms`, which was
renamed to `kms` for the same reason.

The timezone column is the other half of the timestamp work. Everything is
stored in UTC, which is right; showing it in UTC is not. "Closed at 02:14"
means nothing to a clerk looking at a report closed just before ten the
previous night.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REQUESTS = "service_requests"
SETTINGS = "system_settings"
RENAMES = [
    ("vertex_ai_summary", "ai_summary"),
    ("vertex_ai_classification", "ai_classification"),
    ("vertex_ai_analyzed_at", "ai_analyzed_at"),
]


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # Renamed rather than added-and-copied: these hold a model's summary of a
    # resident's report, so two columns holding the same text while something
    # backfills is two places for it to be missed by the retention scrub.
    existing = _columns(REQUESTS)
    for old, new in RENAMES:
        if old in existing and new not in existing:
            op.alter_column(REQUESTS, old, new_column_name=new)

    settings = _columns(SETTINGS)
    if settings and "timezone" not in settings:
        op.add_column(SETTINGS, sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    existing = _columns(REQUESTS)
    for old, new in RENAMES:
        if new in existing and old not in existing:
            op.alter_column(REQUESTS, new, new_column_name=old)
    if "timezone" in _columns(SETTINGS):
        op.drop_column(SETTINGS, "timezone")
