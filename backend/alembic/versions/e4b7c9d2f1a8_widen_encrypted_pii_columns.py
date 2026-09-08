"""Encrypted PII columns become Text, so a ciphertext cannot outgrow them again.

Revision ID: e4b7c9d2f1a8
Revises: d8f0b2c4e6a3
Create Date: 2026-08-27

The width of these four columns has been wrong twice, for the same reason each
time: how long a ciphertext is depends on which key service wrapped it, and
that is a per-town choice the schema cannot see.

    200  the original. Google KMS produces ~225 characters, so every phone
         write failed the moment a cloud key service was configured.
    500  chosen against that ~225. Azure Key Vault wraps the data key with the
         vault's RSA key -- 684 bytes, ~912 characters base64.

The second one surfaced on the live demo the day the town's Key Vault role
assignment was finally correct: PII encryption stopped falling back to the
application key, started producing real Key Vault envelopes, and every resident
submission began failing with

    asyncpg.exceptions.StringDataRightTruncationError:
    value too long for type character varying(500)

which reached the resident as "Request failed" on the report form.

No width is safe against the next provider, so this stops choosing one.
Postgres stores text and varchar the same way, and dropping a length limit is a
catalogue update rather than a table rewrite -- no data is read or moved, and
nothing is truncated. Existing values are already valid text.

Deliberately not reversible in the destructive direction: downgrade re-imposes
varchar(500), which would fail outright on any row holding a Key Vault envelope
rather than silently cutting a ciphertext in half. A ciphertext that has lost
its tail cannot be decrypted, so failing the downgrade is the safe behaviour.
"""
from alembic import op
import sqlalchemy as sa

revision = "e4b7c9d2f1a8"
down_revision = "d8f0b2c4e6a3"
branch_labels = None
depends_on = None

_COLUMNS = ("first_name", "last_name", "email", "phone")


def upgrade() -> None:
    for column in _COLUMNS:
        op.alter_column(
            "service_requests",
            column,
            existing_type=sa.String(length=500),
            type_=sa.Text(),
            existing_nullable=(column != "email"),
        )


def downgrade() -> None:
    # Will raise if any row no longer fits, which is the point.
    for column in _COLUMNS:
        op.alter_column(
            "service_requests",
            column,
            existing_type=sa.Text(),
            type_=sa.String(length=500),
            existing_nullable=(column != "email"),
        )
