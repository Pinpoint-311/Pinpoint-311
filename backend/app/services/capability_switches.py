"""Whether a town wants a capability, as a fact separate from having set it up.

Three questions about an integration had only two answers between them.

    configured   the selected provider's credentials are stored
                 (`_configured_map`, `/providers/status`)
    wanted       the town intends to use this at all
                 -- nowhere, until this module
    running      dispatch will actually call it

"Wanted" existed only in the browser: `SetupIntegrationsPage` held a
`Set<string>` of ticked features in React state, initialised to everything.
Unticking one hid a section of the setup guide until the page was reloaded and
changed nothing else -- no request, no row, no effect on a single sender. So a
town that had entered an AI key and then decided not to use AI had no way to say
so, and the only way to stop a configured capability was to delete the
credential it had just been asked to paste in.

That is the gap this closes. A capability can now be switched off with its
credentials intact: the key stays readable, the card says "switched off", and
nothing dispatches through it.

Why here and not in `system_settings.modules`
---------------------------------------------
`modules` is the other off-switch in this codebase, and the reason for writing
down which is which is that having two undocumented ones is how the confusion
started. Before this module there were, for email and SMS, *three*:

    modules.email_notifications     JSON flag on system_settings
    EMAIL_ENABLED                   a secret, read by configure_notifications
    (and the same pair for SMS)

Two of the four `modules` flags named a provider-backed capability, and two did
not. That is the split this settles:

    a switch here          the town has a provider, credentials and a card for
                           it, and the setup page owns the decision
    a flag in `modules`    a product feature with nothing to configure --
                           `unlisted_reports`, `research_portal`. No provider,
                           no credentials, no card, nothing to switch off at the
                           dispatch layer.

`ai_analysis`, `sms_alerts` and `email_notifications` moved here, and the
`EMAIL_ENABLED` / `SMS_ENABLED` secrets moved with them. There are two
switches now, with disjoint domains, rather than three that overlap on the
three capabilities a town is most likely to change.

Nothing changes for a town that upgrades. `enabled()` answers from the stored
switch when there is one and from the old sources when there is not, with each
old source's own default -- so an entry that was never written reproduces
exactly what the previous code did, migration or no migration.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# The eight provider-backed capabilities, plus the two features the same
# questionnaire owns that have no provider catalog behind them.
#
# `backups` and `errors` are in this list rather than in `modules` because the
# question being asked is the same one -- does the town want this -- and it is
# asked in the same place, by the same ticks. They have no capability card only
# because there is no vendor to choose between.
SWITCHABLE = (
    "ai", "translation", "email", "sms", "kms", "redaction",
    "identity", "maps", "secrets",
    "backups", "errors",
)

# Not a choice, so not switchable.
#
# Staff have to sign in and residents have to drop a pin, or the town cannot
# take a report at all; and every credential either of those needs is kept by
# the secret store, which is not a feature anyone ticks. Offering an off switch
# for these would be offering to break the product from the setup page.
ALWAYS_ON = frozenset({"identity", "maps", "secrets"})

# Switched off at the setup page, and deliberately not at the point of use.
#
# Every other switchable capability is consulted where it dispatches. This one is
# not, and the absence is a decision rather than an oversight -- written down
# because "is kms covered?" should have an answer in the code instead of needing
# a grep that comes back empty and proves nothing either way.
#
#   kms   Switching off the key store cannot be allowed to mean "encrypt
#         personal data with something weaker". `pii_crypto` refuses a local
#         fallback on purpose, so honouring this at dispatch would either
#         downgrade the cipher or break every read of an already-encrypted
#         column. What a town switching this off actually wants is for the page
#         to stop asking for KMS credentials and the daily sweep to stop
#         reporting them outstanding, and `capability_is_configured` already
#         gives it that. So the switch stops short of the cipher.
#
# `test_every_switch_is_enforced_somewhere` keeps this honest: a capability may
# be missing from the dispatch paths only by being named here.
ADVISORY_ONLY = frozenset({"kms"})

# What each capability meant before this module existed, so an unwritten switch
# behaves exactly as it did. Consulted only when the stored map says nothing.
_LEGACY_MODULE_FLAG = {
    "ai": ("ai_analysis", False),
    "sms": ("sms_alerts", False),
    "email": ("email_notifications", True),
}

# The secret that used to gate the same capability, and the sense of it.
#
# They disagreed, which is why both are reproduced rather than generalised.
# `EMAIL_ENABLED` was an opt-in -- a town had to set it to "true" -- and
# `SMS_ENABLED` was a kill switch, because SMS already had an off state in its
# provider (`none`) and requiring a second yes would have stopped texts for
# every town that configured Twilio and never heard of the key.
_LEGACY_SECRET = {
    "email": ("EMAIL_ENABLED", "opt-in"),
    "sms": ("SMS_ENABLED", "kill-switch"),
}


def _off_word(value: Optional[str]) -> bool:
    from app.services.delivery_providers import switched_off

    return switched_off(value)


# The last switch map this process read, for the one caller that cannot await.
#
# Sentry's `before_send` is a synchronous hook on the error path, and the error
# being reported may well be "the database is unreachable" -- so it is the last
# place to open a session and the last place to block an event loop. It reads
# this instead.
#
# Refreshed by every `_stored()` call, which is every dispatch decision the app
# makes, plus `set_enabled` so that flipping the switch takes effect immediately
# in the process that handled the click, plus the hourly `probe_system` so a
# worker that dispatches nothing still converges.
_snapshot: Dict[str, bool] = {}


def wanted_sync(capability: str, default: bool = True) -> bool:
    """The last answer this process read, without touching the database.

    `default` is what to assume before anything has been read -- which for crash
    reporting is "send it", because a process that has not yet learned the switch
    is off should not swallow the crash that stopped it from learning.
    """
    if capability in ALWAYS_ON:
        return True
    return bool(_snapshot.get(capability, default))


async def refresh_snapshot() -> Dict[str, bool]:
    """Re-read the switches so `wanted_sync` is current. For scheduled callers."""
    return await _stored()


async def _stored() -> Dict[str, bool]:
    """The switches a town has actually set, or {} if it has set none.

    Never raises. This is consulted on dispatch paths -- the photo detector, the
    notification sender, the translation resolver -- and a database hiccup must
    not decide that every integration is off. An empty answer falls through to
    the legacy sources below, which is the behaviour that shipped before this.
    """
    try:
        from sqlalchemy import select

        from app.db.session import SessionLocal
        from app.models import SystemSettings

        async with SessionLocal() as db:
            row = (await db.execute(
                select(SystemSettings).order_by(SystemSettings.id).limit(1)
            )).scalar_one_or_none()
            stored = dict(getattr(row, "capability_switches", None) or {})
        global _snapshot
        _snapshot = stored
        return dict(stored)
    except Exception as exc:
        # The snapshot is deliberately left alone. A failed read is not evidence
        # that anything was switched off, and clearing it here would turn a
        # database hiccup into "start reporting crashes again".
        logger.debug("capability switches: could not be read (%s)", exc)
        return {}


async def _legacy(capability: str) -> bool:
    """What this capability's on/off state was before the switch existed.

    Both of the old sources are consulted and both have to say yes, because
    both were live at once: `configure_notifications` refused to build a sender
    without `EMAIL_ENABLED`, and `send_notifications` refused to send without
    `modules.email_notifications`. Taking either one alone would switch email
    on for some town that had it off.
    """
    ok = True

    module_flag = _LEGACY_MODULE_FLAG.get(capability)
    if module_flag:
        name, default = module_flag
        try:
            from sqlalchemy import select

            from app.db.session import SessionLocal
            from app.models import SystemSettings

            async with SessionLocal() as db:
                row = (await db.execute(
                    select(SystemSettings).order_by(SystemSettings.id).limit(1)
                )).scalar_one_or_none()
            modules = (getattr(row, "modules", None) or {}) if row else {}
            ok = ok and bool(modules.get(name, default))
        except Exception:
            ok = ok and default

    secret_flag = _LEGACY_SECRET.get(capability)
    if secret_flag:
        key, sense = secret_flag
        try:
            from app.services.secret_manager import get_secret

            raw = await get_secret(key)
        except Exception:
            raw = None
        if sense == "opt-in":
            ok = ok and (raw or "").strip().lower() == "true"
        else:
            ok = ok and not _off_word(raw)

    return ok


async def enabled(capability: str) -> bool:
    """Whether this capability may be used at all.

    Says nothing about whether it is set up. A capability can be switched on
    with no credentials -- which is the ordinary state of a town mid-setup --
    and switched off with credentials stored, which is the state that had no
    way to be expressed.
    """
    if capability in ALWAYS_ON:
        return True
    stored = await _stored()
    if capability in stored:
        return bool(stored[capability])
    return await _legacy(capability)


async def all_enabled() -> Dict[str, bool]:
    """Every switch, resolved the same way `enabled` resolves one."""
    stored = await _stored()
    out: Dict[str, bool] = {}
    for capability in SWITCHABLE:
        if capability in ALWAYS_ON:
            out[capability] = True
        elif capability in stored:
            out[capability] = bool(stored[capability])
        else:
            out[capability] = await _legacy(capability)
    return out


async def set_enabled(db, switches: Dict[str, bool]) -> Dict[str, bool]:
    """Record the town's answer, and return every switch as it now stands.

    A partial map is a partial update: the questionnaire posts the one chip that
    was clicked, and a town that has never answered a question about photo
    redaction must not have an answer invented for it by a click on backups.

    Writing is what makes an answer explicit, and explicit is the point -- an
    absent entry falls back to whatever the old flags said, and the whole reason
    for this module is that the old flags could not express "configured, and not
    wanted".
    """
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified

    from app.models import SystemSettings

    row = (await db.execute(
        select(SystemSettings).order_by(SystemSettings.id).limit(1)
    )).scalar_one_or_none()
    if row is None:
        row = SystemSettings()
        db.add(row)
        await db.flush()

    current = dict(row.capability_switches or {})
    for capability, wanted in (switches or {}).items():
        if capability not in SWITCHABLE:
            continue
        if capability in ALWAYS_ON:
            # Accepted and ignored rather than rejected: the questionnaire never
            # offers these, so a request carrying one is a stale client rather
            # than an attempt to break the town.
            continue
        current[capability] = bool(wanted)

    row.capability_switches = current
    flag_modified(row, "capability_switches")
    await db.commit()
    return await all_enabled()
