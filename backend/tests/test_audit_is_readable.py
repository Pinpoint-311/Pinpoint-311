"""An audit log has to say what happened, and not say it a hundred times.

The backstop middleware fixed the real gap -- fifty-two mutating endpoints
wrote nothing at all -- and produced this:

    Admin Change    admin    -    Aug 2, 2026, 12:58 AM    -
    Admin Change    admin    -    Aug 2, 2026, 12:58 AM    -
    ... x25

Three separate failures in one screen. The action was not named, so no row
could be acted on. The address was not recorded, so the column read "-" under
sign-in rows that had one. And clicking "Check all providers" wrote a row per
connection test, so the twenty-five entries at 12:58 pushed the change that
mattered onto page four.
"""

import pytest

from app.services.audit_labels import describe_action, should_record


# ---- what is worth a row ----

@pytest.mark.parametrize("method,path", [
    ("POST", "/api/system/providers/twilio/test"),
    ("POST", "/api/system/connectors/check"),
    ("POST", "/api/system/retention/preview"),
    ("POST", "/api/gis/geocode"),
    ("POST", "/api/system/health/refresh"),
])
def test_a_button_that_changes_nothing_writes_nothing(method, path):
    """These are reads that need a body. A person diagnosing an integration
    clicks them a dozen times in a minute, and each one was a row."""
    assert should_record(method, path) is False
    assert describe_action(method, path) is None


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/users"),
    ("DELETE", "/api/departments/4"),
    ("PUT", "/api/system/settings"),
    ("POST", "/api/system/retention/policy"),
    ("POST", "/api/gis/boundaries"),
])
def test_a_real_change_is_recorded(method, path):
    assert should_record(method, path) is True
    assert describe_action(method, path)


def test_a_delete_is_recorded_whatever_it_is_called():
    """`DELETE /api/system/cache/check` is a deletion. Matching the word
    "check" and skipping it would lose a destructive action to a naming
    coincidence."""
    assert should_record("DELETE", "/api/system/cache/check") is True


def test_reads_are_never_recorded():
    """GET is the overwhelming majority of traffic; a log nobody can scroll is
    a log nobody reads."""
    assert should_record("GET", "/api/users") is False
    assert should_record("HEAD", "/api/users") is False


def test_destroying_a_resident_record_is_recorded_in_the_admin_log():
    """Everything else on a request belongs on that request's own timeline.
    Deleting it is different: the timeline is what goes with it, and "who
    deleted this report" is the question a records custodian is actually
    asked."""
    assert describe_action("DELETE", "/api/open311/v2/requests/SR-2026-0041") == (
        "Deleted a resident's service request"
    )
    assert describe_action("POST", "/api/open311/v2/requests/SR-2026-0041/restore") == (
        "Restored a deleted service request"
    )


def test_ordinary_work_on_a_request_stays_off_the_admin_log():
    """A status change and a comment are the day job. They are on the request,
    where somebody looking at that request will see them, and putting them here
    too would bury the deletions in a hundred routine updates."""
    assert should_record("PUT", "/api/open311/v2/requests/41/status") is False
    assert should_record("POST", "/api/open311/v2/public/requests/41/comments") is False


@pytest.mark.parametrize("path", [
    "/api/auth/login",
    "/api/telemetry/ping",
    "/api/open311/v2/requests",
    "/api/system/translate/es",
])
def test_handlers_that_log_themselves_are_not_logged_twice(path):
    """A sign-in already writes a login_success. Two rows for one action makes
    the count meaningless."""
    assert should_record("POST", path) is False


# ---- what the row says ----

def test_the_action_is_a_sentence_not_a_route():
    """The audience is a clerk being asked, at a hearing, what happened on the
    2nd -- not somebody who can read a URL."""
    assert describe_action("POST", "/api/system/retention/policy") == (
        "Added or updated the records retention policy"
    )
    assert describe_action("DELETE", "/api/users/12") == "Deleted a staff account"


def test_the_same_action_on_two_records_reads_the_same_way():
    """Otherwise `/api/users/12` and `/api/users/13` look like two unrelated
    kinds of event, and neither can be counted."""
    assert describe_action("DELETE", "/api/users/12") == describe_action("DELETE", "/api/users/13")


def test_an_unrecognised_endpoint_is_not_filed_under_the_nearest_thing():
    """A new route should read as unfamiliar rather than be mislabelled. A
    wrong label in a compliance record is worse than a bare path."""
    said = describe_action("POST", "/api/something/new")
    assert said and "/api/something/new" in said


def test_no_values_are_put_in_the_label():
    """This table is exported to CSV and handed over on request. The body and
    the query string carry passwords, API keys and residents' addresses."""
    said = describe_action("POST", "/api/system/providers/email?api_key=secret-value")
    assert "secret-value" not in (said or "")


# ---- the middleware uses it, and records who from where ----

def test_the_middleware_names_the_action_and_the_address():
    """Both were missing from the row, which is why the screen was a wall of
    "Admin Change ... - ... -"."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    source = root.joinpath("backend/app/main.py").read_text()
    block = source[source.index("class AdminActionAuditMiddleware"):]
    block = block[:block.index("\ndef _actor_from_request")]

    assert "describe_action(" in block, "the middleware is not naming the action"
    assert 'ip_address=_client_ip(request)' in block, "the address is not recorded"
    assert '"action": action' in block, "the description is not stored on the row"


def test_the_address_is_taken_from_the_proxy_header():
    """Caddy fronts everything, so `request.client.host` is Caddy's address on
    the compose network -- identical for every user, which is the same as
    having no address at all."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    source = root.joinpath("backend/app/main.py").read_text()
    helper = source[source.index("def _client_ip"):]
    helper = helper[:helper.index("\nclass ")]
    assert 'X-Forwarded-For' in helper
    assert "request.client.host" in helper, "no fallback for a direct connection"
