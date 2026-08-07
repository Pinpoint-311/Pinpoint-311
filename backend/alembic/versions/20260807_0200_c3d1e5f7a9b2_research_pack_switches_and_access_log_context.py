"""research pack switches + request context on the research access log

Two additive columns for the research-portal hardening:

system_settings.research_packs -- {pack_id: bool}, the admin's per-pack export
switches. NULL (every upgraded deployment) means "never answered", and each
pack falls back to its own default in research.RESEARCH_PACKS_DEF: ON for the
analytical packs, so an upgrade changes nothing a town already relied on, and
OFF for the two packs whose fields are town-authored characterizations of a
resident's own message (sentiment/trust, moderation flags) -- those are
enabled deliberately, never discovered.

research_access_logs.ip_address / user_agent -- who downloaded a dataset is
only half an audit answer when the account is shared or compromised; the
client address and agent string are what an investigation correlates against.
Nullable because history cannot be backfilled and an empty value must read as
"predates this column", not "unknown client".

Guarded by inspection, matching the migrations before it: a create_all
provisioned database arrives here with the columns already present, and an
unguarded add_column would fail on a schema that is already correct.

Revision ID: c3d1e5f7a9b2
Revises: a7029676a2bc
Create Date: 2026-08-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d1e5f7a9b2"
down_revision: Union[str, None] = "a7029676a2bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if "research_packs" not in _columns("system_settings"):
        op.add_column("system_settings", sa.Column("research_packs", sa.JSON(), nullable=True))

    access_log_columns = _columns("research_access_logs")
    if "ip_address" not in access_log_columns:
        op.add_column("research_access_logs", sa.Column("ip_address", sa.String(45), nullable=True))
    if "user_agent" not in access_log_columns:
        op.add_column("research_access_logs", sa.Column("user_agent", sa.String(500), nullable=True))


def downgrade() -> None:
    if "research_packs" in _columns("system_settings"):
        op.drop_column("system_settings", "research_packs")

    access_log_columns = _columns("research_access_logs")
    if "user_agent" in access_log_columns:
        op.drop_column("research_access_logs", "user_agent")
    if "ip_address" in access_log_columns:
        op.drop_column("research_access_logs", "ip_address")
