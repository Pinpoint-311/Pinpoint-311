"""Per-category location mode, and keyed fingerprints for resident history.

Revision ID: b3d5f7a9c1e2
Revises: e4b7c9d2f1a8
Create Date: 2026-10-17

Additive only: two new columns on existing tables, one small new table, and
indexes. Nothing is read, rewritten or dropped.

service_definitions.location_mode
    "required" | "optional" | "hidden". Existing categories get "optional",
    which is exactly how every category behaved before: the map was offered and
    nothing enforced it. See app/services/location_policy.py.

service_requests.resident_email_index / resident_name_index / pii_index_version
    HMAC-SHA256 fingerprints of the normalised resident email and full name,
    for the opt-in "Resident history" module. The encrypted PII columns are not
    touched. Existing rows are fingerprinted by resident_index.backfill() at
    startup, because computing them needs the decrypted values and the town's
    key service, which a migration should not depend on.

pii_index_keys
    The single random key behind those fingerprints, stored wrapped by the PII
    envelope encryption (so by the town's KMS when one is configured).
"""
from alembic import op
import sqlalchemy as sa

revision = "b3d5f7a9c1e2"
down_revision = "e4b7c9d2f1a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_definitions",
        sa.Column("location_mode", sa.String(length=16), nullable=False, server_default="optional"),
    )
    op.create_check_constraint(
        "ck_service_definitions_location_mode",
        "service_definitions",
        "location_mode IN ('required', 'optional', 'hidden')",
    )

    op.add_column("service_requests", sa.Column("resident_email_index", sa.String(length=64), nullable=True))
    op.add_column("service_requests", sa.Column("resident_name_index", sa.String(length=64), nullable=True))
    op.add_column("service_requests", sa.Column("pii_index_version", sa.Integer(), nullable=True))
    op.create_index("ix_service_requests_resident_email_index", "service_requests", ["resident_email_index"])
    op.create_index("ix_service_requests_resident_name_index", "service_requests", ["resident_name_index"])

    op.create_table(
        "pii_index_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wrapped_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("pii_index_keys")
    op.drop_index("ix_service_requests_resident_name_index", table_name="service_requests")
    op.drop_index("ix_service_requests_resident_email_index", table_name="service_requests")
    op.drop_column("service_requests", "pii_index_version")
    op.drop_column("service_requests", "resident_name_index")
    op.drop_column("service_requests", "resident_email_index")
    op.drop_constraint("ck_service_definitions_location_mode", "service_definitions", type_="check")
    op.drop_column("service_definitions", "location_mode")
