"""The unauthenticated Open311 routes answer with what a stranger may know.

Two of these endpoints used to hand an anonymous caller the staff response
models, whole:

  * `POST /open311/v2/requests.json` declared `ServiceRequestResponse`, built
    from the ORM row. Filing a pothole report returned the internal integer
    `id`, `assigned_to` -- the login name of the staff member the router had
    just picked -- `assigned_department_id`, `ai_analysis`,
    `manual_priority_score`, `flagged`, `priority`, `source`, `matched_asset`,
    `custom_fields`, `is_public`, `public_archived`, and the soft-delete triple
    `deleted_at`/`deleted_by`/`delete_justification`. No login, no api_key, no
    rate limit worth the name: the disclosure was the success path.
  * `GET /open311/v2/public/requests/{id}/comments` declared
    `RequestCommentResponse`, which carries each author's `username` and
    `user_id`. The tracker page of any report published the roster of everyone
    who had touched it, with their internal ids.

Both are fixed by giving the public routes their own narrow models. The reason
this file exists rather than trusting that: the leak was not an added line, it
was a *shared* line -- one model serving a staff endpoint and a public one --
and the way it comes back is somebody adding a field to
`ServiceRequestResponse` for the console, which is a completely reasonable
thing to do and would say nothing about Open311 in its diff.

So the assertions below are on the actual serialised payloads, and on the
response_model FastAPI has bound to each route in the real router. Both, on
purpose: the model could be right and the route still point at the old one.
"""

import pytest

# Guard on the submodule, not on "app". backend/app/ is a directory, so with
# the dependencies absent Python resolves it as a namespace package and
# importorskip("app") succeeds -- the guard misses and collection dies on the
# first real import. See the header of test_migrate.py. CI installs a minimal
# set; this module needs fastapi, sqlalchemy, slowapi and redis, all of which
# app.api.open311 pulls in at import time.
open311 = pytest.importorskip("app.api.open311")
schemas = pytest.importorskip("app.schemas")


# Fields that describe how the town works internally, or who works for it.
# Every one of these was in the old create response.
FORBIDDEN_ON_CREATE = {
    "id",
    "assigned_to",
    "assigned_department_id",
    "assigned_department",
    "ai_analysis",
    "manual_priority_score",
    "flagged",
    "flag_reason",
    "priority",
    "source",
    "matched_asset",
    "custom_fields",
    "is_public",
    "public_archived",
    "deleted_at",
    "deleted_by",
    "delete_justification",
    "external_links",
}

# What the submitter legitimately needs: the acknowledgement, and enough to
# look the report up again. Removing any of these WOULD be a regression --
# `service_request_id` most of all, which is the only field the resident portal
# reads off this response (ResidentPortal.tsx: setSubmittedId, and the
# my_requests localStorage list that drives the tracker).
REQUIRED_ON_CREATE = {
    "service_request_id",
    "service_code",
    "service_name",
    "description",
    "status",
    "requested_datetime",
    "address",
    "lat",
    "long",
}


def _route(method: str, path_suffix: str):
    """The APIRoute for one endpoint, from the real router.

    Matched on the declared path so a renamed handler still resolves, and
    asserted to be unique so a second route on the same path cannot make this
    test silently check the wrong one.
    """
    matches = [
        r for r in open311.router.routes
        if getattr(r, "path", None) == path_suffix and method in getattr(r, "methods", set())
    ]
    assert len(matches) == 1, f"expected exactly one {method} {path_suffix}, got {len(matches)}"
    return matches[0]


class _Row:
    """Stands in for the ORM object a handler hands to its response model."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# --------------------------------------------------------------------------
# POST /requests.json
# --------------------------------------------------------------------------

def test_creating_a_request_does_not_reveal_who_it_was_assigned_to():
    """The serialised create response, field by field.

    Built from a row that has every internal field populated -- including an
    `assigned_to` of "j.morales", because auto-assignment runs inside the same
    handler and that field is reliably set by the time the response is built.
    """
    row = _Row(
        id=4711,
        service_request_id="REQ-20260823-AB12CD34",
        service_code="POTHOLE",
        service_name="Pothole",
        description="Deep pothole outside the library",
        status="open",
        priority=2,
        address="12 Main St",
        lat=40.1,
        long=-74.2,
        requested_datetime=None,
        updated_datetime=None,
        source="resident_portal",
        flagged=True,
        is_public=True,
        public_archived=False,
        matched_asset={"asset_id": "SIGN-9"},
        custom_fields={"depth": "large"},
        assigned_department_id=3,
        assigned_to="j.morales",
        closed_substatus=None,
        deleted_at=None,
        deleted_by="admin",
        delete_justification="duplicate",
        manual_priority_score=8.5,
        ai_analysis={"priority_score": 9},
        external_links=["accela"],
    )

    payload = schemas.Open311CreatedRequestResponse.model_validate(row).model_dump()

    leaked = FORBIDDEN_ON_CREATE & set(payload)
    assert not leaked, f"create response still exposes internal fields: {sorted(leaked)}"
    # Not just the key: the staff username must not appear anywhere in the
    # body, under any name a future refactor might give it.
    assert "j.morales" not in str(payload)
    assert REQUIRED_ON_CREATE <= set(payload), (
        f"create response is missing fields a submitter needs: "
        f"{sorted(REQUIRED_ON_CREATE - set(payload))}"
    )
    assert payload["service_request_id"] == "REQ-20260823-AB12CD34"


def test_the_create_route_is_bound_to_the_narrow_model():
    """The model being right does not help if the route serves the old one."""
    route = _route("POST", "/requests.json")
    assert route.response_model is schemas.Open311CreatedRequestResponse
    assert route.response_model is not schemas.ServiceRequestResponse


def test_the_staff_response_model_is_left_alone():
    """`ServiceRequestResponse` is still the console's, unchanged.

    The fix was to stop *sharing* it, not to strip it -- the staff dashboard
    reads assignment and triage off exactly these fields, and narrowing them
    would break the admin UI, which is the worse outcome of the two.
    """
    staff_fields = set(schemas.ServiceRequestResponse.model_fields)
    assert {"assigned_to", "assigned_department_id", "ai_analysis", "id"} <= staff_fields


# --------------------------------------------------------------------------
# GET/POST /public/requests/{id}/comments
# --------------------------------------------------------------------------

def test_public_comments_never_carry_a_user_id_or_an_internal_request_id():
    fields = set(schemas.PublicRequestCommentResponse.model_fields)
    assert "user_id" not in fields
    assert "service_request_id" not in fields
    # Still enough for the tracker to render the thread: it keys on id, renders
    # content and created_at, and shows the author name and badge.
    assert {"id", "username", "content", "created_at", "author_type"} <= fields


@pytest.mark.parametrize(
    "user_id,external_ref,username,expected_type,expected_name",
    [
        (17, None, "j.morales", "staff", "Staff"),
        (None, None, "Resident", "resident", "Resident"),
        (None, "accela:88", "Accela", "integration", "Accela"),
    ],
)
def test_a_staff_comment_is_attributed_to_staff_and_nothing_more(
    user_id, external_ref, username, expected_type, expected_name
):
    """The same rule the public audit log already applies to `actor_name`.

    A resident keeps the anonymous name they were stored under; a platform sync
    note keeps the platform's name, which is not a person's; a staff comment
    becomes "Staff". The classification is by what the writer left behind
    (`user_id`, `external_ref`), not by parsing the name -- an integration
    called "Resident Services" would otherwise be read as a resident.
    """
    comment = _Row(
        id=9,
        service_request_id=4711,
        user_id=user_id,
        external_ref=external_ref,
        username=username,
        content="We have scheduled a crew.",
        visibility="external",
        created_at=None,
        updated_at=None,
    )

    author_type, display_name = open311.public_comment_author(comment)
    assert (author_type, display_name) == (expected_type, expected_name)

    payload = schemas.PublicRequestCommentResponse(
        id=comment.id,
        author_type=author_type,
        username=display_name,
        content=comment.content,
        visibility=comment.visibility,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    ).model_dump()

    assert "user_id" not in payload
    assert "service_request_id" not in payload
    assert "4711" not in str(payload)
    if expected_type == "staff":
        assert "j.morales" not in str(payload)


def test_both_halves_of_the_public_comments_route_use_the_narrow_model():
    """GET and POST, because a route answering in two shapes is how one of
    them quietly gets a field added back."""
    path = "/public/requests/{request_id}/comments"
    for method in ("GET", "POST"):
        route = _route(method, path)
        model = route.response_model
        # The GET is a list; unwrap List[...] to compare the element model.
        args = getattr(model, "__args__", None)
        if args:
            model = args[0]
        assert model is schemas.PublicRequestCommentResponse, (
            f"{method} {path} serves {model!r}, not the narrowed public model"
        )


def test_the_staff_comment_model_still_carries_what_the_dashboard_reads():
    """StaffDashboard and PrintWorkOrder read username, visibility and the
    author's id off the authenticated comments endpoint. Narrowing the public
    route must not have narrowed theirs."""
    staff_fields = set(schemas.RequestCommentResponse.model_fields)
    assert {"user_id", "username", "visibility", "service_request_id"} <= staff_fields
