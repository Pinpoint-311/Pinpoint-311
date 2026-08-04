"""Give "the town does not want this" somewhere to live.

Wanted-ness was browser state. `SetupIntegrationsPage` initialised a
`Set<string>` to every feature and unticking one hid part of the setup guide
until the next reload -- no request, no row, and no effect on any sender. So a
capability could be configured or unconfigured and nothing else, and the only
way to stop one that was configured was to delete its credential.

This adds `system_settings.capability_switches` and folds into it the two
places that were already answering a piece of the same question:

    modules.ai_analysis / sms_alerts / email_notifications
    the EMAIL_ENABLED and SMS_ENABLED secrets

Email and SMS had all three at once, at different layers, with different
defaults. The seed below only writes an entry where the old sources settle the
answer on their own; anything it leaves out is resolved at read time from the
same old sources, so an unseeded capability behaves exactly as it did.

The `modules` JSON keeps `unlisted_reports` and `research_portal`: product
features with no provider, no credentials and nothing to configure. See
app/services/capability_switches.py for the rule.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Reproduced rather than imported. A migration has to keep describing the schema
# as it was on the day it ran, and importing the service would make this file's
# behaviour change the next time that module does.
_LEGACY_MODULE_DEFAULT = {"ai_analysis": False, "sms_alerts": False, "email_notifications": True}


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("capability_switches", sa.JSON(), nullable=True, server_default="{}"),
    )

    conn = op.get_bind()
    row = conn.execute(sa.text(
        "SELECT id, modules FROM system_settings ORDER BY id LIMIT 1"
    )).fetchone()
    if row is None:
        # No settings row yet, so no town to preserve the behaviour of. The
        # column default and the read-time fallback cover whatever is created
        # next.
        return

    settings_id = row[0]
    modules = row[1] or {}

    def module(name: str) -> bool:
        return bool(modules.get(name, _LEGACY_MODULE_DEFAULT[name]))

    switches = {
        # No secret ever gated AI, so the module flag was the whole switch.
        "ai": module("ai_analysis"),
        # These four never had a switch: they ran whenever their credentials
        # were present, which is what "on" now means.
        "translation": True,
        "kms": True,
        "redaction": True,
        "backups": True,
        "errors": True,
    }

    # Email and SMS had a second gate in a secret, and this migration cannot
    # read it -- the value is encrypted with a key it does not hold, and may
    # have been migrated into the vault and scrubbed from the database
    # entirely. So only the unambiguous direction is seeded: a module flag that
    # says no means off whatever the secret says, because both had to agree
    # before anything sent. The other direction is left to the read-time
    # fallback, which consults the secret properly.
    if not module("email_notifications"):
        switches["email"] = False
    if not module("sms_alerts"):
        switches["sms"] = False

    conn.execute(
        sa.text("UPDATE system_settings SET capability_switches = CAST(:v AS json) WHERE id = :id"),
        {"v": json.dumps(switches), "id": settings_id},
    )

    # Drop the three provider-backed flags from `modules`, so there is one
    # switch per capability rather than two that can disagree. The column is
    # `json` rather than `jsonb`, which has no key-removal operator of its own.
    conn.execute(sa.text(
        "UPDATE system_settings SET modules = CAST("
        "  (CAST(COALESCE(modules, '{}') AS jsonb) - 'ai_analysis' - 'sms_alerts' - 'email_notifications')"
        " AS json)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    # Put the three flags back from the switches, so a rollback does not leave
    # a town with email quietly defaulting back on.
    conn.execute(sa.text("""
        UPDATE system_settings SET modules = CAST(
            CAST(COALESCE(modules, '{}') AS jsonb) || jsonb_build_object(
                'ai_analysis', COALESCE(CAST(capability_switches AS jsonb)->'ai', 'false'::jsonb),
                'sms_alerts', COALESCE(CAST(capability_switches AS jsonb)->'sms', 'false'::jsonb),
                'email_notifications', COALESCE(CAST(capability_switches AS jsonb)->'email', 'true'::jsonb)
            ) AS json)
    """))
    op.drop_column("system_settings", "capability_switches")
