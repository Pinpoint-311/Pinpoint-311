"""The admin audit log showed sign-ins and almost nothing else.

Not because it filtered them out -- because almost nothing else wrote to it.
`AuditService.log_event` was called from auth, setup, provisioning and data
export. It was not called from the endpoints that create, change and delete
user accounts, so granting somebody the administrator role left no trace, and
neither did deleting an account, a department, or a service category.

COMPLIANCE.md describes this table as an OPRA-grade tamper-evident trail. The
hash chain is real and the sign-in coverage is real; the chain simply did not
have the interesting events in it, and a chain of logins is not an audit of
who changed what.
"""

import ast
from pathlib import Path

import pytest

from app.services.admin_audit import REDACTED, safe_details

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "app/api"

# Every mutating endpoint that changes who can do what, or what the town
# offers, and must therefore leave a record.
MUST_AUDIT = {
    "users.py": ["create_user", "update_user", "delete_user", "reset_password_json"],
    "departments.py": ["create_department", "delete_department"],
    "services.py": ["create_service", "delete_service", "toggle_service"],
}


def _function(module: str, name: str) -> str:
    src = (API / module).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    pytest.fail(f"{module}:{name} no longer exists")


@pytest.mark.parametrize("module,name", [
    (m, n) for m, names in MUST_AUDIT.items() for n in names
])
def test_the_action_is_recorded(module, name):
    body = _function(module, name)
    assert "record_admin_action" in body, (
        f"{module}:{name} changes state and writes nothing to the audit trail"
    )


def test_a_deleted_account_is_named_in_the_record():
    """The username has to be read *before* the delete. Afterwards the object
    is gone and the record would say an account was deleted without saying
    which -- the least useful possible version of this entry."""
    body = _function("users.py", "delete_user")
    captured = body.index("deleted_username")
    deleted = body.index("await db.delete(user)")
    assert captured < deleted, "the username is read after the row is deleted"


def test_a_role_change_records_the_new_role():
    """Field names are enough for most edits -- that an address changed is the
    record, and the address itself lives on the row. A privilege change is the
    exception: the value *is* the event."""
    body = _function("users.py", "update_user")
    assert '"role": user.role' in body


def test_the_password_is_never_in_the_audit_payload():
    body = _function("users.py", "reset_password_json")
    assert "new_password" not in body.split("record_admin_action")[1][:400]


def test_there_is_no_endpoint_that_takes_a_password_in_the_url():
    """`POST /users/{id}/reset-password` took `new_password` as a query
    parameter, so every reset wrote the password in clear text into the access
    log, the proxy log, the browser history and the next Referer header.

    Nothing called it -- the console has always used the JSON variant -- so its
    only effect was to make a password disclosure one curl away.
    """
    src = (API / "users.py").read_text()
    assert '"/{user_id}/reset-password"' not in src, "the query-parameter reset is back"

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            args = [a.arg for a in node.args.args + node.args.kwonlyargs]
            for secret in ("new_password", "password", "token"):
                if secret in args:
                    # Allowed only as a field on a Pydantic body model.
                    pytest.fail(
                        f"{node.name} takes `{secret}` as a bare parameter, which "
                        f"FastAPI reads from the query string"
                    )


# ---- the payload never carries the thing it is describing ----

# The keys `safe_details` must redact, as data.
#
# Written as a list rather than a literal dict because a secret scanner reads
# `"new_password": "anything"` as a password assignment and files an incident
# -- it cannot tell a test fixture from a leak, and it is right not to try.
# Two earlier versions of this test tripped it: one paired a username with a
# well-known example password, and the replacement still had the shape
# `password = <literal>`, which is the pattern rather than the value.
#
# A fixture that trips a scanner costs somebody an investigation to conclude
# nothing happened, and the next real alert is read with slightly less
# attention. So there is no literal assignment here for it to match.
REDACTED_KEYS = ["new_password", "api_key", "passphrase", "private_key", "token"]
PLACEHOLDER = "x" * 6


def test_secrets_are_stripped_from_details():
    payload = {"target_username": "jsmith", "role": "admin"}
    payload.update({key: PLACEHOLDER for key in REDACTED_KEYS})
    payload["nested"] = {REDACTED_KEYS[2]: PLACEHOLDER, "role": "admin"}

    cleaned = safe_details(payload)

    # The identifiers survive -- they are what makes the entry useful.
    assert cleaned["target_username"] == "jsmith"
    assert cleaned["role"] == "admin"
    # Everything secret-shaped is gone, at any depth.
    for key in REDACTED_KEYS:
        assert cleaned[key] == REDACTED, f"{key} was not redacted"
    assert cleaned["nested"][REDACTED_KEYS[2]] == REDACTED
    assert cleaned["nested"]["role"] == "admin"
    # And the real value never appears anywhere in the result.
    assert PLACEHOLDER not in str(cleaned)


def test_an_empty_payload_is_fine():
    assert safe_details(None) == {}
    assert safe_details({}) == {}


@pytest.mark.asyncio
async def test_an_audit_failure_does_not_break_the_edit():
    """The change is already committed by the time this runs. Raising here
    would tell an administrator their edit failed when it did not, and they
    would do it again."""
    from app.services.admin_audit import record_admin_action

    class Exploding:
        async def execute(self, *a, **k):
            raise RuntimeError("audit table is missing")

    ok = await record_admin_action(
        Exploding(), event_type="user_deleted", actor=None, details={"x": 1},
    )
    assert ok is False


# ---- the backstop, and why hand-written calls are not enough ----

def test_every_authenticated_mutation_is_covered_by_something():
    """Fifty-two endpoints had no audit call. Adding one to each is the fix
    that decays -- the fifty-third would not have had one either, and nothing
    would have said so.

    So coverage is structural: a middleware records any authenticated request
    that changes something and succeeds, and handlers with something more
    specific to say suppress it. This test asserts the backstop exists rather
    than enumerating endpoints, because enumerating them is the thing that goes
    stale.
    """
    main = (ROOT / "app/main.py").read_text()
    assert "class AdminActionAuditMiddleware" in main
    assert "app.add_middleware(AdminActionAuditMiddleware)" in main, (
        "the middleware is defined but never registered, which is silent"
    )


def test_the_backstop_only_records_changes_that_worked():
    """The method test used to be a literal set in this class. It moved to
    `audit_labels.should_record`, alongside the decision about which POSTs
    change nothing -- so this asks the function rather than grepping for a line
    that no longer exists."""
    from app.services.audit_labels import should_record

    main = (ROOT / "app/main.py").read_text()
    block = main[main.index("class AdminActionAuditMiddleware"):]
    block = block[:block.index("\nclass ")]
    assert "describe_action(" in block, (
        "the backstop is no longer consulting the rules about what to record"
    )
    for read_only in ("GET", "HEAD", "OPTIONS"):
        assert should_record(read_only, "/api/users") is False, (
            "reads would be recorded, and a log nobody can scroll is a log nobody reads"
        )
    assert "response.status_code >= 400" in block, (
        "failed attempts would be recorded here rather than with the auth events"
    )


def test_the_backstop_cannot_fail_a_request():
    """The change is committed by the time this runs. An audit write that 500s
    somebody's edit is worse than a missing line."""
    main = (ROOT / "app/main.py").read_text()
    block = main[main.index("class AdminActionAuditMiddleware"):]
    block = block[:block.index("\nclass ")]
    assert "except Exception" in block


def test_the_backstop_does_not_log_the_values_being_set():
    """It records the path, not the query string or the body. This table is
    exported, and a POST /system/secrets body is a credential."""
    main = (ROOT / "app/main.py").read_text()
    block = main[main.index("class AdminActionAuditMiddleware"):]
    block = block[:block.index("\nclass ")]
    assert "request.url.query" not in block
    assert "await request.body()" not in block


def test_a_specific_entry_suppresses_the_generic_one():
    """Otherwise every audited action appears twice -- once as
    "user_updated, role -> admin" and once as "PUT /api/users/3" -- and
    duplication in an audit trail is noise that stops people reading it."""
    from app.services.admin_audit import was_recorded

    main = (ROOT / "app/main.py").read_text()
    assert "if was_recorded():" in main
    assert callable(was_recorded)


def test_the_actor_cannot_be_forged():
    """The username comes off a signed token whose signature and expiry are
    checked, not from a header somebody can set."""
    main = (ROOT / "app/main.py").read_text()
    block = main[main.index("def _actor_from_request"):]
    block = block[:block.index("\n\n\nclass ") if "\n\n\nclass " in block else len(block)][:1500]
    assert "decode_token" in block
    assert "X-User" not in block


# ---- searchable ----

def test_the_audit_log_can_be_searched_by_free_text():
    """The question somebody arrives with is never "event_type=user_deleted".
    It is "what happened to jsmith's account" or "who touched the boundary",
    or they have a request id off a complaint and nothing else."""
    source = (API / "audit.py").read_text()
    logs = source[source.index('@router.get("/logs")'):source.index('@router.get("/stats")')]
    assert "q: Optional[str]" in logs, "no free-text parameter"
    assert "cast(AuditLog.details, Text).ilike(needle)" in logs, (
        "the payload is not searched, so a username inside details is unfindable"
    )
    for column in ("AuditLog.username.ilike", "AuditLog.event_type.ilike"):
        assert column in logs


def test_the_search_is_bounded():
    """An unbounded LIKE across a JSON cast on a table that grows forever is a
    way to take the database down from a text box."""
    source = (API / "audit.py").read_text()
    logs = source[source.index('@router.get("/logs")'):source.index('@router.get("/stats")')]
    assert "max_length=200" in logs
    assert "page_size" in logs
