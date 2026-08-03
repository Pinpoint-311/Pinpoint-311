"""Whether this town has actually chosen a records-retention schedule.

The state code used to default to ``NJ``, in the model and again in five
separate ``or "NJ"`` fallbacks around the codebase. That is not a default in
any harmless sense: it is the duration a record is kept and the statute cited
when it is destroyed. A town in Texas inherited a seven-year OPRA schedule and
began anonymising records four years before the Texas Public Information Act
allows, and nothing on any screen said so -- the compliance tab confidently
headlined "New Jersey / OPRA" to a clerk in Amarillo.

There is no safe implicit answer here, so this module refuses to invent one.
An unconfigured town gets ``configured=False`` and every caller declines to
act: the nightly task archives nothing, the backup pruner deletes nothing, the
console shows the capability as not set up. Halted retention is a problem an
administrator can see and fix in a minute. Records destroyed on the wrong
state's schedule cannot be brought back.

The confirmation flag is the awkward part, and it exists because the old
default already materialised into rows. A stored ``NJ`` is genuinely ambiguous
-- it is what a town in Newark chose and also what a town in Amarillo never
chose -- and no amount of reading the database distinguishes them. So the value
is left alone and ``retention_state_confirmed`` records, from this point on,
whether a human picked it. Existing rows start unconfirmed: retention pauses
for everyone until each town says which state it is in, including the ones that
were right all along. That is the tradeoff, and it is deliberate -- a pause is
visible and reversible in both directions, whereas the alternative keeps
destroying records on the wrong schedule in every town that never looked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

# The name this capability is reported under, in connector health and in the
# proactive check. Retention has no provider and no credentials, so it is not
# in the provider catalog -- but "configured or not" is the same question the
# setup page asks of everything else, and it should be answerable the same way.
CAPABILITY = "retention"

# Why a town is unconfigured. Three different situations that a clerk needs
# told apart: nothing saved at all, a settings row with no state, and a state
# that is only there because it used to be the default.
NO_SETTINGS = "no_settings"
NO_STATE = "no_state"
UNCONFIRMED = "unconfirmed"

_WHERE = "Settings → Compliance → Document Retention"


@dataclass(frozen=True)
class RetentionConfig:
    """What a retention run needs to know, plus whether it may run at all.

    ``configured`` is the only field a caller must check. The rest are filled
    in either way so an unconfigured town can still be *shown* what it has --
    the console needs to display the inherited state code in order to ask about
    it -- but ``state_code`` being populated is not permission to act on it.
    """

    configured: bool
    state_code: Optional[str] = None
    override_days: Optional[int] = None
    mode: str = "redact"
    scrub_fields: Optional[List[str]] = None
    reason: Optional[str] = None
    detail: Optional[str] = None

    def as_status(self) -> dict:
        """The shape the setup page already reads for unconfigured things.

        Matches the ``{"ok", "configured", "detail"}`` contract the provider
        tests return, so a card can render this without a second code path.
        """
        return {
            "ok": self.configured,
            "configured": self.configured,
            "detail": self.detail or "",
            "reason": self.reason,
        }


def _explain(reason: str, inherited: Optional[str]) -> str:
    if reason == UNCONFIRMED:
        return (
            f"Records retention is still on the {inherited} schedule this instance "
            f"shipped with, which nobody here has confirmed. Nothing will be archived "
            f"or deleted until an administrator confirms the town's state in {_WHERE}."
        )
    return (
        "No state has been chosen for records retention, so the retention period "
        "and the public-records law to cite are both unknown. Nothing will be "
        f"archived or deleted until an administrator chooses a state in {_WHERE}."
    )


def read_retention_config(settings: Any) -> RetentionConfig:
    """Resolve retention settings from a ``SystemSettings`` row (or ``None``).

    Pure, so the decision that stops a destructive job is testable without a
    database.
    """
    from app.services.retention_scrub import normalise_fields, normalise_mode

    if settings is None:
        return RetentionConfig(
            configured=False,
            scrub_fields=normalise_fields(None),
            reason=NO_SETTINGS,
            detail=_explain(NO_SETTINGS, None),
        )

    state_code = (getattr(settings, "retention_state_code", None) or "").strip().upper() or None
    confirmed = bool(getattr(settings, "retention_state_confirmed", False))
    # normalise_mode already reads NULL as redact; going through it here means
    # the live rows that predate the column default -- retention_mode is NULL on
    # them -- resolve the same way everywhere rather than at each call site.
    mode = normalise_mode(getattr(settings, "retention_mode", None))
    scrub_fields = normalise_fields(getattr(settings, "retention_scrub_fields", None))
    override_days = getattr(settings, "retention_days_override", None)

    if not state_code:
        reason = NO_STATE
    elif not confirmed:
        reason = UNCONFIRMED
    else:
        return RetentionConfig(
            configured=True,
            state_code=state_code,
            override_days=override_days,
            mode=mode,
            scrub_fields=scrub_fields,
        )

    return RetentionConfig(
        configured=False,
        state_code=state_code,
        override_days=override_days,
        mode=mode,
        scrub_fields=scrub_fields,
        reason=reason,
        detail=_explain(reason, state_code),
    )


async def load_retention_config(db) -> RetentionConfig:
    """The same answer, read from the singleton settings row."""
    from app.services.system_settings import get_settings

    return read_retention_config(await get_settings(db))
