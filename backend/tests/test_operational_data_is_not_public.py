"""Who a report is assigned to is not public, and the UI is not what enforces it.

The request map now shows department, assigned-staff, priority and layer
filters on the staff dashboard and not on the resident portal. That difference
is a prop on a React component, which is compiled into a public JavaScript
bundle -- anyone can set it to true in a debugger and make the checkboxes
appear.

That is fine, and this file is why. The filters are a way of looking at data
you already have. If the server never sends a resident `assigned_to`, an
`assigned_department_id`, a department list or a staff roster, then forcing the
panel open renders empty checkboxes over data that is not there. The boundary
is the endpoint, not the layout.

Checked here rather than trusted to review, because every one of these is a
single line somebody could add back for a reasonable-sounding reason -- "the
public map should show which department is handling it" is not an obviously
wrong thing to want.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "backend/app/api"

# Fields that describe how the town works internally rather than what was
# reported. A resident is told the status of their report, not who is holding it.
INTERNAL_FIELDS = {
    "assigned_to",
    "assigned_department_id",
    "assigned_department",
    "manual_priority_score",
    "ai_analysis",
    "internal_notes",
    "staff_notes",
    "flag_reason",
}


# Every attribute of the row the public payload is allowed to read. The keys
# are only half the control: `"description": r.staff_notes` renames a leak and
# a key check waves it through, and `**{...}` contributes no key at all.
ALLOWED_ROW_ATTRS = {
    "service_request_id", "service_code", "service_name", "description",
    "status", "address", "lat", "long", "requested_datetime",
    "updated_datetime", "closed_substatus", "media_urls",
    "completion_message", "completion_photo_url",
}


def _public_list_dict() -> ast.Dict:
    """The dict node `list_public_requests` builds one element of the response
    from.

    Parsed rather than grepped: the endpoint sits in a 1500-line module and a
    substring search for "assigned_to" matches the staff endpoints below it.
    """
    tree = ast.parse((API / "open311.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_public_requests":
            for dict_node in ast.walk(node):
                if isinstance(dict_node, ast.Dict) and len(dict_node.keys) > 5:
                    return dict_node
    pytest.fail("could not find the payload built by list_public_requests")


def _public_list_payload() -> set:
    """The payload's keys -- but only once the dict is known to be all literal
    keys. `_public_list_dict` plus `test_..._is_built_only_from_literal_keys`
    is what makes this set trustworthy; on its own a key set is not, which is
    the bug this file had."""
    return {k.value for k in _public_list_dict().keys if isinstance(k, ast.Constant)}


def test_the_public_payload_is_built_only_from_literal_keys():
    """No `**spread`, no computed key.

    This is the hole that was here. `_public_list_payload` collected
    `ast.Constant` keys and quietly dropped everything else, so inserting

        **{c.name: getattr(r, c.name) for c in r.__table__.columns}

    into the unauthenticated list endpoint published reporter names, emails,
    phones and staff notes to anyone -- and every test in this file passed. A
    spread has a `None` key in the AST: it contributed no key to the set the
    "internal fields" check ran against, and no key to the `len(keys) < 25`
    size check either, so the payload could grow to every column while
    measuring as fourteen.
    """
    node = _public_list_dict()
    spreads = [i for i, k in enumerate(node.keys) if k is None]
    assert not spreads, (
        "the public request payload contains a `**` spread. Whatever it "
        "expands to is served unauthenticated, and no key-based check in this "
        "file can see it. List the fields."
    )
    computed = [ast.dump(k) for k in node.keys
                if not (isinstance(k, ast.Constant) and isinstance(k.value, str))]
    assert not computed, (
        f"the public request payload has non-literal keys: {computed}. The "
        f"explicit dict is the access control; a computed key is not reviewable."
    )


def test_the_public_payload_reads_only_the_fields_it_names():
    """The values, not just the keys.

    `"description": r.staff_notes` passes every key check in this file. So does
    `"lat": r.__dict__`. What the payload is allowed to *read off the row* is
    pinned here.
    """
    node = _public_list_dict()
    read = set()
    for value in node.values:
        for sub in ast.walk(value):
            # Only attribute access directly on a name (`r.description`).
            # `r.requested_datetime.isoformat()` yields the inner one, which is
            # the access that matters.
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                read.add(sub.attr)
    unexpected = read - ALLOWED_ROW_ATTRS
    assert not unexpected, (
        f"the public request payload reads {sorted(unexpected)} off the row. "
        f"Add it to ALLOWED_ROW_ATTRS only if a resident is meant to see it."
    )


def test_the_public_map_is_not_told_who_is_handling_a_report():
    keys = _public_list_payload()
    leaked = keys & INTERNAL_FIELDS
    assert not leaked, (
        f"the public requests list now includes {sorted(leaked)}. That is the "
        f"data the staff-only map filters run on, and publishing it makes the "
        f"UI split cosmetic."
    )


def test_the_public_payload_is_a_named_list_rather_than_the_whole_row():
    """A future refactor to `ServiceRequestResponse.model_validate(r)` would
    pass the test above while serving every column. The explicit dict is the
    control, so its shape is pinned."""
    keys = _public_list_payload()
    assert "service_request_id" in keys and "status" in keys, "payload shape changed"
    assert len(keys) < 25, "the public payload has grown; check what was added"


def test_there_is_no_unauthenticated_staff_roster():
    """`GET /users/staff/public` served every active staff and admin account --
    username, full name and role -- to anyone who asked. Its only caller was
    the public map's staff filter.

    A username list is the first half of a credential-stuffing attempt and
    `role` said which of them were administrators.
    """
    source = (API / "users.py").read_text()
    assert '"/staff/public"' not in source, "the public staff roster endpoint is back"

    # And the remaining staff endpoint is behind a session.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_staff_members":
            defaults = ast.dump(ast.Module(body=[ast.Expr(d) for d in node.args.defaults],
                                           type_ignores=[]))
            assert "get_current_staff" in defaults, "/users/staff lost its auth"
            return
    pytest.fail("no list_staff_members endpoint")


def test_the_departments_list_stays_behind_a_login():
    """It carries routing_email, which is an internal address, and it is the
    other half of what the department filter needs."""
    tree = ast.parse((API / "departments.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_departments":
            defaults = ast.dump(ast.Module(body=[ast.Expr(d) for d in node.args.defaults],
                                           type_ignores=[]))
            assert "get_current_staff" in defaults or "get_current_admin" in defaults, (
                "GET /departments/ is no longer authenticated"
            )
            return
    pytest.fail("no list_departments endpoint")


# ---- the UI half: correct, but not what is doing the enforcing ----

PORTAL = ROOT / "frontend/src/pages/ResidentPortal.tsx"
DASHBOARD = ROOT / "frontend/src/pages/StaffDashboard.tsx"
MAP = ROOT / "frontend/src/components/StaffDashboardMap.tsx"


@pytest.fixture(scope="module")
def portal() -> str:
    if not PORTAL.exists():
        pytest.skip("frontend not present in this checkout")
    return PORTAL.read_text()


def test_the_resident_portal_asks_for_none_of_it(portal):
    """Not a security control -- the endpoints above are. This keeps the public
    page from making requests that will 401, which is what was deleting
    people's sessions before the 401 handling was fixed."""
    for call in ("api.getDepartments(", "api.getPublicStaffList("):
        assert call not in portal, f"the public portal calls {call}"


def test_the_two_callers_disagree_on_purpose(portal):
    """The staff dashboard opts in; the resident portal does not. Written as a
    pair because the failure mode is adding the prop to the shared component
    and forgetting one caller."""
    dashboard = DASHBOARD.read_text()
    staff_call = re.search(r"<StaffDashboardMap(.*?)/>", dashboard, re.S).group(1)
    portal_call = re.search(r"<StaffDashboardMap(.*?)/>", portal, re.S).group(1)

    assert "operationalFilters" in staff_call, "the staff map lost its filters"
    assert "operationalFilters" not in portal_call, (
        "the resident portal is asking for the internal filters"
    )


def test_the_flag_defaults_to_off():
    """A new caller of this component gets the resident view unless it says
    otherwise. Defaulting the other way means every future embed leaks by
    omission."""
    source = MAP.read_text()
    assert "operationalFilters = false" in source, (
        "operationalFilters must default to false"
    )


def test_hiding_a_filter_also_stops_it_filtering():
    """The panels are hidden by `operationalFilters &&`, but the predicates run
    inside updateMarkers regardless of what is on screen. A checkbox nobody can
    see must not be able to remove a pin from the map -- that is a report the
    public silently cannot find."""
    source = MAP.read_text()
    for guard in (
        "operationalFilters && Object.keys(departmentFilters).length > 0",
        "operationalFilters && Object.keys(staffFilters).length > 0",
        "operationalFilters && !priorityFilters[priorityLevel]",
    ):
        assert guard in source, f"predicate not gated: {guard}"
