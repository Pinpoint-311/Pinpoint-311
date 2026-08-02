"""Record what an administrator changed, not only that they signed in.

The admin console's audit log showed sign-in events and almost nothing else,
and the reason was simply that almost nothing else wrote to `AuditLog`. Auth,
setup, provisioning and data export did. The endpoints that create and delete
user accounts did not -- so granting somebody the admin role, or deleting an
account, left no trace anywhere. Nor did deleting a department or a service
category.

That is a gap in something the compliance documentation describes as an
OPRA-grade tamper-evident trail. The hash chain is real and the sign-in
coverage is real; the chain just did not have the interesting events in it.

`AuditService.log_event` already exists and already chains. This is a thin
wrapper over it with three jobs:

  * never raise -- an audit write must not be the reason a user edit fails,
    and the caller has already committed by the time we are here
  * take the actor off the request rather than making thirteen call sites
    remember to
  * keep the `details` payload to identifiers and field names, never values

That last one matters. This table is exported, and "changed the phone number"
is the audit record; the phone number itself is the data the record is *about*
and belongs in the row it was written to, not duplicated into a log with a
different retention story.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.core.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

# Values that must never be copied into an audit detail payload, whatever a
# caller passes. Belt and braces: call sites pass field *names*, but a future
# one that passes a whole dict of changes would otherwise leak.
REDACT_KEYS = frozenset({
    "password", "hashed_password", "new_password", "token", "secret",
    "api_key", "credential", "credentials", "private_key", "passphrase",
})

REDACTED = "[redacted]"


def safe_details(details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Strip anything secret-shaped out of an audit payload."""
    if not details:
        return {}
    clean: Dict[str, Any] = {}
    for key, value in details.items():
        if any(marker in key.lower() for marker in REDACT_KEYS):
            clean[key] = REDACTED
        elif isinstance(value, dict):
            clean[key] = safe_details(value)
        else:
            clean[key] = value
    return clean


async def record_admin_action(
    db,
    *,
    event_type: str,
    actor,
    success: bool = True,
    details: Optional[Dict[str, Any]] = None,
    failure_reason: Optional[str] = None,
) -> bool:
    """Write one administrative action to the audit trail. Never raises.

    Returns whether it was written, so a caller that wants to refuse the action
    when it cannot be recorded has the option. None currently do: the change is
    already committed by this point, and failing the request afterwards would
    leave the caller believing an edit did not happen that did.
    """
    try:
        from app.services.audit_service import AuditService

        await AuditService.log_event(
            db,
            event_type=event_type,
            success=success,
            username=getattr(actor, "username", None),
            user_id=getattr(actor, "id", None),
            failure_reason=failure_reason,
            details=safe_details(details),
        )
        return True
    except Exception as exc:
        logger.warning(
            "[Audit] could not record %s: %s",
            sanitize_for_log(event_type), sanitize_for_log(str(exc)),
        )
        return False
