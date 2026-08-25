"""When a credential the town cannot renew automatically runs out.

Entra caps a client secret at 24 months, and says nothing when one lapses: the
vault stops answering, PII stops decrypting, and the failure looks like a bug
rather than a date. The advice in the setup walk used to be "diary the date",
which is an instruction to a person because the software did not help.

Recording the date is optional and always will be -- a town on a managed
identity has no secret to record, and one that would rather not is not blocked.
What this removes is the case where somebody did know the date and had nowhere
to put it.

Deliberately not a live lookup. Reading the expiry from Entra would need
directory permissions this deployment does not have and should not ask for, to
learn a date the operator was already shown when they created the secret.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

# Far enough ahead to rotate without hurry, near enough that it is still true
# when the reminder lands. A warning a year out is furniture.
WARN_WITHIN_DAYS = 30


@dataclass(frozen=True)
class ExpiryStatus:
    """`None` days_left means the value was not a date we could read."""
    days_left: Optional[int]
    expired: bool
    message: str
    severity: str  # "info" | "warning" | "error"


def parse_expiry(value: Optional[str]) -> Optional[date]:
    """A date from what an operator is likely to paste, or None.

    Entra shows expiry as a date; people paste it in their own format, and a
    date we cannot read is worth saying so about rather than treating as absent
    -- absent means "not recorded", unreadable means "you recorded something and
    it is doing nothing".
    """
    if not value or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y",
                "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:  # ISO with a time on it, which is what an export tends to carry
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def check_expiry(value: Optional[str], *, label: str, today: Optional[date] = None
                 ) -> Optional[ExpiryStatus]:
    """None when nothing was recorded -- silence is the right answer there."""
    if not value or not value.strip():
        return None
    when = parse_expiry(value)
    if when is None:
        return ExpiryStatus(
            None, False,
            f"{label}: “{value.strip()}” is not a date Pinpoint can read, so "
            f"nothing will warn you. Use YYYY-MM-DD.",
            "info",
        )
    days = (when - (today or date.today())).days
    if days < 0:
        return ExpiryStatus(
            days, True,
            f"{label} expired on {when.isoformat()}. Resident data cannot be "
            f"decrypted until a new secret is saved. Nothing is lost — the key "
            f"is still in the vault.",
            "error",
        )
    if days <= WARN_WITHIN_DAYS:
        return ExpiryStatus(
            days, False,
            f"{label} expires on {when.isoformat()}, in {days} "
            f"day{'' if days == 1 else 's'}. Create a new one in Entra and save "
            f"it here before then.",
            "warning",
        )
    return ExpiryStatus(days, False,
                        f"{label} expires on {when.isoformat()}.", "info")
