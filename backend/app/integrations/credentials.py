"""Secret Manager–of–record credential handling for govtech integrations.

Government deployments must not hold raw vendor secrets in the application
database. When a real external Secret Manager (Google Secret Manager, Azure Key
Vault, or AWS Secrets Manager) is configured, an integration's credentials are
written *there* and the ``IntegrationConfig`` row stores only an opaque
reference — ``@secret:<NAME>`` — never the secret itself. Connectors resolve
references to live values at call time, so the raw secret exists only in the
vault of record.

When no external vault is configured (local/dev, or a fully self-contained
single-tenant install), values fall back to the existing encrypted-in-DB
storage so the platform still works standalone. The reference format is the
same in both worlds; only *where the value lives* changes.

Key scheme (shared with the read path and the old mirror): each field is stored
under ``INTEGRATION_<PLATFORM>_<FIELD>``, upper-cased.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Sentinel prefix marking a stored credential as a Secret Manager reference
# rather than a literal value. Chosen to be something no real secret would be.
SECRET_REF_PREFIX = "@secret:"


def secret_key_for(platform: str, field: str) -> str:
    """The Secret Manager key name for one integration credential field."""
    return f"INTEGRATION_{str(platform).upper()}_{str(field).upper()}"


def is_reference(value: object) -> bool:
    return isinstance(value, str) and value.startswith(SECRET_REF_PREFIX)


def reference_name(value: str) -> str:
    """The Secret Manager key name a ``@secret:NAME`` reference points at."""
    return value[len(SECRET_REF_PREFIX):]


def make_reference(name: str) -> str:
    return f"{SECRET_REF_PREFIX}{name}"


async def store_credentials(platform: str, credentials: Dict[str, str]) -> Dict[str, str]:
    """Persist raw secret values to the external Secret Manager and return the
    dict to store on the ``IntegrationConfig`` row.

    For each field:
      * an already-``@secret:`` reference is passed through untouched;
      * a blank value is dropped (means "keep existing" upstream);
      * a real value is written to the vault. If the write succeeds, the row
        stores a ``@secret:NAME`` reference (the raw value never lands in the
        app DB). If no external vault is configured or the write fails, the raw
        value is returned so the caller's encrypted-DB column keeps it — the
        platform still functions, just without a separate vault of record.
    """
    if not credentials:
        return {}

    out: Dict[str, str] = {}
    try:
        from app.services.secret_manager import set_secret, clear_cache
    except Exception:  # secret_manager unavailable → keep everything raw
        return {k: v for k, v in credentials.items() if v or is_reference(v)}

    from app.core.sanitize import sanitize_for_log

    wrote = False
    written: list[str] = []
    for field, value in credentials.items():
        if is_reference(value):
            out[field] = value
            continue
        if not value:
            continue
        name = secret_key_for(platform, field)
        try:
            ok = await set_secret(name, value)
        except Exception as e:
            logger.warning(
                "[Integrations] Secret Manager write failed for %s: %s",
                sanitize_for_log(name), sanitize_for_log(str(e)),
            )
            ok = False
        if ok:
            out[field] = make_reference(name)  # vault of record — no raw in DB
            wrote = True
            written.append(name)
        else:
            # No external vault (or transient failure): fall back to keeping the
            # value, which the model encrypts at rest in the DB column.
            out[field] = value

    if wrote:
        # Only the bundles these keys live in. This loop can span several, so it
        # clears each rather than everything -- an integration save should not
        # cost the next request a refetch of every other capability's secrets.
        for name in written:
            try:
                clear_cache(key_name=name)
            except Exception:
                pass
    return out


class CredentialsUnavailable(Exception):
    """The credentials exist but could not be read from the vault right now.

    A distinct failure from "the admin never filled this in", and the two used to
    be indistinguishable. An unresolvable reference was simply omitted, the
    connector then said "credentials missing", and `_friendly_test_error` turned
    that into "Some required fields are still blank — go back one step and fill
    them in". Which is the worst possible advice: the fields are not blank, the
    vault is unreachable, and following the instruction overwrites good
    references with whatever the admin retypes -- turning an outage into data
    loss.

    Carries the field names so the message can say which, without ever carrying
    a value.
    """

    def __init__(self, fields):
        self.fields = sorted(fields)
        super().__init__(
            "Could not read " + ", ".join(self.fields) + " from your Secret Manager. "
            "The credentials are stored but unreadable right now, so this is a "
            "vault or permissions problem rather than a missing setting."
        )


async def resolve_credentials(credentials: Dict[str, str]) -> Dict[str, str]:
    """Resolve any ``@secret:NAME`` references to live values from the Secret
    Manager, for handing to a connector. Non-reference values (dev fallback,
    or plain config) pass through unchanged.

    Raises ``CredentialsUnavailable`` when a reference cannot be resolved, rather
    than omitting the field. Omitting it made an unreachable vault look exactly
    like an unfilled form — see that exception's docstring for why that
    mattered more than it sounds.
    """
    if not credentials:
        return {}

    from app.core.sanitize import sanitize_for_log

    resolved: Dict[str, str] = {}
    unresolved: list[str] = []
    get_secret = None
    for field, value in credentials.items():
        if not is_reference(value):
            resolved[field] = value
            continue
        if get_secret is None:
            from app.services.secret_manager import get_secret as _get
            get_secret = _get
        name = reference_name(value)
        try:
            live = await get_secret(name)
        except Exception as e:
            logger.error(
                "[Integrations] Could not resolve secret reference %s: %s",
                sanitize_for_log(name), sanitize_for_log(str(e)),
            )
            live = None
        if live:
            resolved[field] = live
        else:
            logger.error(
                "[Integrations] Secret reference %s did not resolve.",
                sanitize_for_log(name),
            )
            unresolved.append(field)

    if unresolved:
        raise CredentialsUnavailable(unresolved)
    return resolved
