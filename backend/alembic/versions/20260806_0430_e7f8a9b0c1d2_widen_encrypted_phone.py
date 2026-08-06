"""Widen the encrypted phone column to fit a KMS-wrapped value.

`service_requests.phone` was varchar(200) while its three sibling PII columns
are varchar(500). Ciphertext is longer than plaintext, and a value wrapped by a
cloud key service is longer still -- prefix, wrapped data key, nonce and
ciphertext come to ~225 characters. So the moment a town connected Google
Cloud KMS, every phone write raised StringDataRightTruncationError: new
reports could not store the resident's number, and the nightly re-wrap failed
on every phone field it touched, forever.

Widening a varchar is metadata-only in Postgres: no rewrite, no downtime.
There is deliberately no downgrade to 200 -- shrinking would truncate stored
ciphertext, which is unrecoverable.

Revision ID: e7f8a9b0c1d2
Revises: b1c2d3e4f5a6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "service_requests" not in set(inspector.get_table_names()):
        return
    op.alter_column(
        "service_requests", "phone",
        existing_type=sa.String(length=200),
        type_=sa.String(length=500),
        existing_nullable=True,
    )


def downgrade() -> None:
    # No shrink. Values longer than 200 exist precisely because this migration
    # ran, and truncating ciphertext destroys the value it encodes.
    pass
