"""Whether this town has actually chosen a records-retention schedule.

The product used to answer that question on the town's behalf, twice over.

It shipped a table of retention periods for all 51 US jurisdictions, each
carrying the name of that state's records authority and the title of its public
records law. Nobody verified any of it, and the periods gave it away: forty-one
of the fifty-one were five years, and the rest were six, seven, three or ten.
One number wearing fifty-one different citations. A clerk reading "5 years,
source: Alabama State Records Commission" had every reason to believe somebody
had looked it up. Towns not in the table were told they were governed by
"Federal FOIA", which covers federal executive-branch agencies and has no
bearing on a municipal pothole report at all.

The failure is asymmetric, which is why none of it survives. If a town's real
schedule is longer than the number we invented, the town destroys records it
was legally required to keep, and there is no undo. If retention simply does
not run, the town keeps records longer than it meant to, which is a problem an
administrator can see and fix.

So both halves are the municipality's to state: how long a record is kept, and
what a run removes from it. Every municipality already has a retention schedule,
usually approved by its state archives, and its clerk has the authoritative
document. We add nothing by guessing, and we take something away by looking as
though we had researched it.

An unconfigured town gets ``configured=False`` and every caller declines to act:
the nightly task archives nothing, the backup pruner deletes nothing, the setup
page and the health dashboard say so and keep saying so. That last part is not
decoration. With no period there is no deletion, so a town that never configures
keeps resident personal data indefinitely -- and data minimisation is its own
obligation. Off by default is still right, because under-deletion is recoverable
and over-deletion is not, but it must not be quiet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

# The name this capability is reported under, in connector health and in the
# proactive check. Retention has no provider and no credentials, so it is not
# in the provider catalog -- but "configured or not" is the same question the
# setup page asks of everything else, and it should be answerable the same way.
CAPABILITY = "retention"

# Why a town is unconfigured. Three situations a clerk needs told apart:
# nothing saved at all, no retention period, and a period with nothing chosen
# to remove when it expires.
NO_SETTINGS = "no_settings"
NO_PERIOD = "no_period"
NO_FIELDS = "no_fields"

_WHERE = "Settings → Compliance → Document Retention"

# The consequence of each gap, said in the terms it actually bites in. "Not
# configured" is a status; "resident personal data is being kept indefinitely"
# is what is happening while it stays that way.
_KEPT_INDEFINITELY = (
    "resident personal data on closed requests is being kept indefinitely"
)


@dataclass(frozen=True)
class RetentionConfig:
    """What a retention run needs to know, plus whether it may run at all.

    ``configured`` is the only field a caller must check. The rest are filled
    in either way so an unconfigured town can still be *shown* what it has --
    a half-filled form is worth rendering -- but a populated ``retention_days``
    is not on its own permission to act.
    """

    configured: bool
    retention_days: Optional[int] = None
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


def _explain(reason: str) -> str:
    """Say what is not happening, and what that costs, before what to click.

    Each of these ends at the same place -- nothing is being deleted -- but a
    clerk cannot act on that without knowing which half is missing, so the
    sentence names it.
    """
    if reason == NO_FIELDS:
        return (
            "A retention period is set, but nothing has been chosen to remove when "
            "it expires, so a run would mark records archived and leave every name, "
            f"address and phone number on them. Nothing is being cleared and "
            f"{_KEPT_INDEFINITELY} until an administrator chooses what a run removes "
            f"in {_WHERE}."
        )
    if reason == NO_PERIOD:
        return (
            "No retention period has been set, so there is no date at which a closed "
            f"request becomes eligible to be cleared. Nothing is being archived or "
            f"deleted and {_KEPT_INDEFINITELY} until an administrator sets the period "
            f"their town's records schedule requires, in {_WHERE}."
        )
    return (
        "Records retention has never been set up: there is no period after which a "
        "closed request is cleared, and nothing has been chosen to remove from it. "
        f"Nothing is being archived or deleted and {_KEPT_INDEFINITELY} until an "
        f"administrator sets both in {_WHERE}."
    )


def _period(value: Any) -> Optional[int]:
    """A stored retention period, or ``None`` if there isn't a usable one.

    Zero and negatives are read as unset rather than as "delete everything
    immediately". They arrive from a cleared form field, and the one reading
    that must never be inferred is the one that destroys records today.
    """
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if days > 0 else None


def read_retention_config(settings: Any) -> RetentionConfig:
    """Resolve retention settings from a ``SystemSettings`` row (or ``None``).

    Pure, so the decision that stops a destructive job is testable without a
    database.
    """
    from app.services.retention_scrub import normalise_fields, normalise_mode

    if settings is None:
        return RetentionConfig(
            configured=False,
            scrub_fields=[],
            reason=NO_SETTINGS,
            detail=_explain(NO_SETTINGS),
        )

    # normalise_mode already reads NULL as redact; going through it here means
    # the live rows that predate the column default -- retention_mode is NULL on
    # them -- resolve the same way everywhere rather than at each call site.
    mode = normalise_mode(getattr(settings, "retention_mode", None))
    scrub_fields = normalise_fields(getattr(settings, "retention_scrub_fields", None))
    retention_days = _period(getattr(settings, "retention_days", None))

    if retention_days is None:
        reason = NO_PERIOD
    elif not scrub_fields:
        # An empty selection is not "redact nothing, harmlessly". A run still
        # stamps archived_at, which takes the record out of every future run's
        # candidate set -- so the records pass out of retention's reach with
        # their personal data intact and nothing left to notice it.
        reason = NO_FIELDS
    else:
        return RetentionConfig(
            configured=True,
            retention_days=retention_days,
            mode=mode,
            scrub_fields=scrub_fields,
        )

    return RetentionConfig(
        configured=False,
        retention_days=retention_days,
        mode=mode,
        scrub_fields=scrub_fields,
        reason=reason,
        detail=_explain(reason),
    )


async def load_retention_config(db) -> RetentionConfig:
    """The same answer, read from the singleton settings row."""
    from app.services.system_settings import get_settings

    return read_retention_config(await get_settings(db))
