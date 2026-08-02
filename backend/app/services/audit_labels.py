"""What an audited action is called, and whether it is worth recording at all.

The backstop middleware records every authenticated change. That closed the
real gap -- fifty-two mutating endpoints wrote nothing -- and immediately
created a smaller one: twenty-five consecutive rows reading

    Admin Change    admin    -    Aug 2, 2026, 12:58 AM    -

which is not an audit trail. It says somebody changed something, twenty-five
times, and refuses to say what. A compliance log that cannot answer "who
changed the retention policy" is decorative, and one that fills with rows
nobody can read is worse than a short one, because the sign-in that mattered is
now on page four.

Two jobs, both here so both are testable without a request:

  1. Name the action in a sentence. "Saved the email provider" beats
     "POST /api/system/providers/email" for the clerk being asked, at an OPRA
     hearing or an audit, what happened on the 2nd.

  2. Say when not to record. A great many POSTs change nothing: testing a
     connection, re-running a health check, generating a preview. They are
     reads that need a body. Recording them buries the changes that matter, and
     "Tested SMTP" twenty times in a minute is what a person clicking
     "Check all" looks like.

Pure -- no FastAPI, no database -- so all of it runs in CI.
"""

from __future__ import annotations

import re
from typing import Optional

# Paths whose own handler writes a better record, or where a per-request entry
# is noise. Checked as prefixes against the full path.
SKIP_PREFIXES = (
    "/api/auth/",              # sign-in and sign-out write their own events
    "/api/system/translate/",  # a rendering call, made per page view
    "/api/system/upload/",     # the request it belongs to records the upload
    "/api/open311/",           # work on a request lives on that request's timeline
    "/api/research/",          # read-only analysis with its own access log
    "/api/telemetry",          # machine polling
    "/api/client-errors",      # browser crash reports, sent unattended
)

# A POST that changes nothing. These are reads that happen to need a body, or
# buttons a person clicks repeatedly while diagnosing something -- exactly the
# traffic that produced twenty-five identical rows in one minute.
NO_CHANGE_SEGMENTS = (
    "/test", "/verify", "/check", "/health", "/preview", "/refresh",
    "/validate", "/geocode", "/search", "/reverse", "/analyze", "/summarize",
    "/recheck", "/ping", "/diagnose",
)

# Path fragment -> what the thing is called. Longest match wins, so
# "/retention/policy" beats "/retention".
_SUBJECTS = (
    ("/system/retention/policy", "the records retention policy"),
    ("/system/retention/run", "a records retention run"),
    ("/system/retention/export", "a public records export"),
    ("/system/retention/legal-hold", "the legal hold"),
    ("/system/domain", "the site's domain"),
    ("/system/providers", "a service provider's settings"),
    ("/system/settings", "the system settings"),
    ("/system/backup", "database backups"),
    ("/system/branding", "the town's branding"),
    ("/system/integrations", "an integration"),
    ("/gis/boundaries", "the town boundary"),
    ("/gis/layers", "a map layer"),
    ("/departments", "a department"),
    ("/services", "a service category"),
    ("/users", "a staff account"),
    ("/assets", "an asset"),
    ("/requests", "a service request"),
    ("/notifications", "notification settings"),
    ("/workflows", "a workflow"),
    ("/knowledge", "the knowledge base"),
)

# Which provider, not just "a provider". "Added or updated a service provider's
# settings" is four rows in a row when somebody works through the setup guide,
# and none of them says whether the thing that changed was who sends the town's
# text messages or who translates its pages.
_CAPABILITIES = {
    "sms": "the SMS provider",
    "email": "the email provider",
    "ai": "the AI provider",
    "translation": "the translation provider",
    "identity": "the sign-in provider",
    "maps": "the maps provider",
    "storage": "the file storage provider",
    "kms": "the encryption key provider",
    "redaction": "the photo redaction provider",
    "payments": "the payments provider",
}

_PROVIDER_SAVE = re.compile(r"^/api/system/providers/([a-z0-9_-]+)/save$")

_VERBS = {
    "POST": "Added or updated",
    "PUT": "Updated",
    "PATCH": "Updated",
    "DELETE": "Deleted",
}

# Trailing identifiers, so `/api/users/42` and `/api/users/7` are the same
# action rather than two unrelated-looking rows.
_ID = re.compile(r"/(?:\d+|[0-9a-f]{8}-[0-9a-f-]{27,})(?=/|$)", re.I)


DESTROYED_A_RECORD = "Deleted a resident's service request"
RESTORED_A_RECORD = "Restored a deleted service request"

# Exceptions to the skip list, because they are the actions a records custodian
# is most likely to be asked about. Work on a request belongs on that request's
# own timeline, but destroying one is a records-management decision, and the
# request's timeline is exactly what disappears with it.
_ALWAYS = (
    ("DELETE", re.compile(r"^/api/open311/v2/requests/[^/]+$"), DESTROYED_A_RECORD),
    ("POST", re.compile(r"^/api/open311/v2/requests/[^/]+/restore$"), RESTORED_A_RECORD),
    # Silencing an integration's alerts is the action behind "why did nobody
    # get emailed for three weeks". It is the last thing that should be
    # filtered out of the log as routine.
    ("POST", re.compile(r"^/api/system/connectors/[^/]+/mute$"),
     "Changed alerting for an integration"),
)


def _exception_for(method: str, path: str) -> Optional[str]:
    for wanted, pattern, label in _ALWAYS:
        if method.upper() == wanted and pattern.match(path):
            return label
    return None


def should_record(method: str, path: str) -> bool:
    """False for reads, for handlers that log themselves, and for no-op POSTs."""
    if method.upper() not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    path = (path or "").rstrip("/") or "/"
    if _exception_for(method, path):
        return True
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return False
    # DELETE always changes something, whatever the last segment is called.
    if method.upper() != "DELETE":
        lowered = path.lower()
        if any(lowered.endswith(s) or f"{s}/" in lowered for s in NO_CHANGE_SEGMENTS):
            return False
    return True


def describe_action(method: str, path: str) -> Optional[str]:
    """A sentence for the Details column, or None if this is not worth a row.

    Deliberately derived from the path alone. The body and the query string
    carry the values being set -- a password, an API key, a resident's address
    -- and this table is exported to CSV and handed over on request.
    """
    if not should_record(method, path):
        return None

    method = method.upper()
    path = (path or "").rstrip("/") or "/"
    named = _exception_for(method, path)
    if named:
        return named

    capability = _PROVIDER_SAVE.match(path)
    if capability:
        which = _CAPABILITIES.get(capability.group(1))
        # An unknown capability keeps its own name rather than being flattened
        # into "a provider": a new one should read as itself on day one.
        return f"Updated {which or capability.group(1) + ' provider'} settings"

    clean = _ID.sub("", path)
    subject = next((name for frag, name in
                    sorted(_SUBJECTS, key=lambda p: -len(p[0]))
                    if frag in clean), None)
    if subject is None:
        # Better a plain path than a wrong guess: a new endpoint should read as
        # unfamiliar rather than be silently filed under the nearest thing.
        return f"{_VERBS.get(method, method)}: {clean}"
    return f"{_VERBS.get(method, method)} {subject}"
