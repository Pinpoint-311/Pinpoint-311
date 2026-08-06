"""SeeClickFix: the report form, and the difference between "signed in" and
"able to file a report".

Creating a SeeClickFix issue is a two-step flow. The request type owns a form of
questions, and the POST must carry an `answers` map keyed by each question's
`primary_key` (https://dev.seeclickfix.com/v2/issues/reporting/). A connector
that posts a summary and a description and hopes gets a 422 naming question ids
nobody in the building can decode -- and it gets it per resident report, after
the setup wizard has already said "You're connected!".

So most of these tests are about the gap between the two: the connection check
passes on credentials alone, and the questions it cannot answer have to be said
out loud at setup time rather than discovered one rejected report at a time.

The question shapes here are the vendor's own documented fixtures (request types
121/122/657): primary_key, question_type, response_required, select_values.
"""

import httpx
import pytest

import app.integrations.base as base
from app.integrations.base import ConnectorError
from app.integrations.registry import PLATFORM_CATALOG, build_connector


# ---- vendor fixtures ---------------------------------------------------------

POTHOLE_QUESTIONS = [
    {"primary_key": "142", "question": "Depth of pothole?", "question_type": "select",
     "response_required": True,
     "select_values": [{"key": "BUMPY", "name": "Bumpy Surface"},
                       {"key": "SHALLOW", "name": "Shallow Hole"},
                       {"key": "DEEP", "name": "Deep Hole"}]},
    {"primary_key": "summary", "question": "Issue Title", "question_type": "text",
     "response_required": True},
    {"primary_key": "description", "question": "Description", "question_type": "textarea",
     "response_required": False},
    {"primary_key": "issue_image", "question": "Issue Image", "question_type": "file",
     "response_required": False},
]

OTHER_QUESTIONS = [
    {"primary_key": "summary", "question": "Issue Title", "question_type": "text",
     "response_required": True},
    {"primary_key": "description", "question": "Description", "question_type": "textarea",
     "response_required": False},
    {"primary_key": "note", "question": "Crews respond in 3 days.", "question_type": "note",
     "response_required": False},
]

PAYLOAD = {
    "service_name": "Pothole",
    "description": "Big hole on the corner",
    "address": "123 State St",
    "lat": 41.3,
    "long": -72.9,
}


def scf(config=None, credentials=None):
    return build_connector("civicplus", config or {}, credentials or {"api_key": "tok"})


def route(monkeypatch, *, questions=OTHER_QUESTIONS, issue=None, issues_status=200,
          request_type_status=200):
    """Stand in for the SeeClickFix API, recording what we sent it."""
    seen = {"requests": [], "create_body": None}
    monkeypatch.setattr(base, "_assert_public_url", lambda url: None)

    async def handle(self, request):
        seen["requests"].append(request)
        url = str(request.url)
        if "/request_types/" in url:
            if request_type_status != 200:
                return httpx.Response(request_type_status, json={}, request=request)
            return httpx.Response(200, json={"id": 122, "questions": questions}, request=request)
        if request.method == "POST":
            import json as _json
            seen["create_body"] = _json.loads(request.content.decode())
            return httpx.Response(201, json=issue if issue is not None else {"id": 987, "status": "Open"},
                                  request=request)
        return httpx.Response(issues_status,
                              json={"issues": [], "metadata": {"pagination": {"entries": 4}}},
                              request=request)

    monkeypatch.setattr(base.httpx.AsyncHTTPTransport, "handle_async_request", handle)
    return seen


# ---- the report form ---------------------------------------------------------

@pytest.mark.asyncio
async def test_creating_an_issue_fetches_the_request_types_form_first(monkeypatch):
    """Step 2 of the vendor's three-step flow. Skipping it is why creation was
    failing: the answers can't be built without knowing the questions."""
    seen = route(monkeypatch, questions=OTHER_QUESTIONS)
    await scf({"request_type_id": "other"}).push_request(PAYLOAD)
    assert any("/request_types/other" in str(r.url) for r in seen["requests"])


@pytest.mark.asyncio
async def test_the_report_is_sent_as_answers_not_top_level_fields(monkeypatch):
    """SeeClickFix reads summary and description out of `answers`, keyed by the
    form's primary_key -- not off the root of the body."""
    seen = route(monkeypatch)
    await scf({"request_type_id": "other"}).push_request(PAYLOAD)
    body = seen["create_body"]
    assert body["request_type_id"] == "other"
    assert body["answers"]["summary"] == "Pothole"
    assert body["answers"]["description"] == "Big hole on the corner"
    assert "summary" not in body and "description" not in body


@pytest.mark.asyncio
async def test_the_parameter_is_request_type_id(monkeypatch):
    """`request_type` is silently ignored by the API, which is a 422 on a
    required question rather than an error about the parameter itself."""
    seen = route(monkeypatch)
    await scf({"request_type_id": "122"}).push_request(PAYLOAD)
    assert "request_type" not in seen["create_body"]


@pytest.mark.asyncio
async def test_a_connection_saved_under_the_old_key_still_files_reports(monkeypatch):
    """The field was renamed. A town that set it up before that keeps working."""
    seen = route(monkeypatch)
    await scf({"request_type": "122"}).push_request(PAYLOAD)
    assert seen["create_body"]["request_type_id"] == "122"


@pytest.mark.asyncio
async def test_a_note_question_is_not_answered(monkeypatch):
    """`note` is display text for the reporter. Answering it invents data."""
    seen = route(monkeypatch, questions=OTHER_QUESTIONS)
    await scf({"request_type_id": "other"}).push_request(PAYLOAD)
    assert "note" not in seen["create_body"]["answers"]


@pytest.mark.asyncio
async def test_photos_travel_in_the_description(monkeypatch):
    """A JSON create cannot carry a file, and a photo the resident took is the
    most useful thing in the report. The link goes where staff will see it."""
    seen = route(monkeypatch)
    payload = {**PAYLOAD, "media_urls": ["https://cdn.test/a.jpg"]}
    await scf({"request_type_id": "other"}).push_request(payload)
    assert "https://cdn.test/a.jpg" in seen["create_body"]["answers"]["description"]


@pytest.mark.asyncio
async def test_a_report_with_no_description_still_answers_a_required_one(monkeypatch):
    seen = route(monkeypatch, questions=[
        {"primary_key": "summary", "question": "Issue Title", "question_type": "text",
         "response_required": True},
        {"primary_key": "description", "question": "Description", "question_type": "textarea",
         "response_required": True},
    ])
    await scf({"request_type_id": "other"}).push_request({**PAYLOAD, "description": None})
    assert seen["create_body"]["answers"]["description"]


# ---- questions nobody can answer ---------------------------------------------

@pytest.mark.asyncio
async def test_an_unanswerable_required_question_fails_before_the_vendor_does(monkeypatch):
    """"Depth of pothole?" is not in a resident's report and never will be. The
    vendor's answer is `422 {"142": ["can't be blank"]}`; ours names the
    question, its id, and the answers it accepts."""
    route(monkeypatch, questions=POTHOLE_QUESTIONS)
    with pytest.raises(ConnectorError) as exc:
        await scf({"request_type_id": "122"}).push_request(PAYLOAD)
    message = str(exc.value)
    assert "Depth of pothole?" in message
    assert "142" in message and "SHALLOW" in message
    assert "Extra answers" in message


@pytest.mark.asyncio
async def test_a_configured_answer_satisfies_the_question(monkeypatch):
    """The way out of the failure above: answer it once, for every report."""
    seen = route(monkeypatch, questions=POTHOLE_QUESTIONS)
    await scf({"request_type_id": "122", "answers": '{"142": "SHALLOW"}'}).push_request(PAYLOAD)
    assert seen["create_body"]["answers"]["142"] == "SHALLOW"


@pytest.mark.asyncio
async def test_a_configured_answer_may_be_a_real_json_object(monkeypatch):
    """The wizard stores text; the API accepts a dict. Both are the same thing."""
    seen = route(monkeypatch, questions=POTHOLE_QUESTIONS)
    await scf({"request_type_id": "122", "answers": {"142": "DEEP"}}).push_request(PAYLOAD)
    assert seen["create_body"]["answers"]["142"] == "DEEP"


@pytest.mark.asyncio
async def test_an_answer_that_is_not_one_of_the_choices_is_caught_here(monkeypatch):
    """A typo'd option and a missing option fail identically at the vendor. This
    one says which value was wrong and what the alternatives are."""
    route(monkeypatch, questions=POTHOLE_QUESTIONS)
    with pytest.raises(ConnectorError) as exc:
        await scf({"request_type_id": "122", "answers": '{"142": "shallow"}'}).push_request(PAYLOAD)
    assert "shallow" in str(exc.value) and "SHALLOW" in str(exc.value)


@pytest.mark.asyncio
async def test_a_multivaluelist_answer_is_checked_option_by_option(monkeypatch):
    route(monkeypatch, questions=[
        {"primary_key": "400", "question": "Surface?", "question_type": "multivaluelist",
         "response_required": True,
         "select_values": [{"key": "Brick", "name": "Brick"}, {"key": "Wood", "name": "Wood"}]},
    ])
    conn = scf({"request_type_id": "657", "answers": {"400": ["Brick", "Marble"]}})
    with pytest.raises(ConnectorError) as exc:
        await conn.push_request(PAYLOAD)
    assert "Marble" in str(exc.value)


@pytest.mark.asyncio
async def test_unparseable_extra_answers_say_what_the_shape_should_be(monkeypatch):
    """Someone will type `142: SHALLOW`. A JSONDecodeError in a sync log helps
    nobody."""
    route(monkeypatch, questions=POTHOLE_QUESTIONS)
    with pytest.raises(ConnectorError) as exc:
        await scf({"request_type_id": "122", "answers": "142: SHALLOW"}).push_request(PAYLOAD)
    assert "valid JSON" in str(exc.value)


@pytest.mark.asyncio
async def test_a_required_photo_question_is_reported_rather_than_faked(monkeypatch):
    """We cannot post a file on a JSON create, so a request type that demands
    one is unusable over this connection -- and should say so, not 422."""
    route(monkeypatch, questions=[
        {"primary_key": "issue_image", "question": "Issue Image", "question_type": "file",
         "response_required": True},
    ])
    with pytest.raises(ConnectorError) as exc:
        await scf({"request_type_id": "122"}).push_request(PAYLOAD)
    assert "photo" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_no_request_type_fails_with_an_instruction(monkeypatch):
    """request_type_id is required on every create. Leaving it blank used to
    post anyway and take a 422."""
    route(monkeypatch)
    with pytest.raises(ConnectorError) as exc:
        await scf({}).push_request(PAYLOAD)
    assert "other" in str(exc.value)


@pytest.mark.asyncio
async def test_a_request_type_that_does_not_exist_is_named(monkeypatch):
    route(monkeypatch, request_type_status=404)
    with pytest.raises(ConnectorError) as exc:
        await scf({"request_type_id": "9999"}).push_request(PAYLOAD)
    assert "9999" in str(exc.value)


@pytest.mark.asyncio
async def test_a_moderated_report_is_not_reported_as_a_broken_create(monkeypatch):
    """202 + `moderated: true` means SeeClickFix took it and is holding it. The
    old message was "returned no issue id", which reads like a bug in us."""
    route(monkeypatch, issue={"metadata": {"moderated": True}})
    with pytest.raises(ConnectorError) as exc:
        await scf({"request_type_id": "other"}).push_request(PAYLOAD)
    assert "moderation" in str(exc.value)


# ---- the connection check ----------------------------------------------------

@pytest.mark.asyncio
async def test_the_check_warns_about_questions_it_could_not_answer(monkeypatch):
    """The whole point of the warning: the credentials work, so the check
    passes, and the request type still cannot be filed against."""
    route(monkeypatch, questions=POTHOLE_QUESTIONS)
    result = await scf({"request_type_id": "122"}).test_connection()
    assert result["ok"] is True
    assert any("Depth of pothole?" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_a_fully_answerable_request_type_produces_no_warnings(monkeypatch):
    route(monkeypatch, questions=OTHER_QUESTIONS)
    result = await scf({"request_type_id": "other"}).test_connection()
    assert "warnings" not in result


@pytest.mark.asyncio
async def test_the_check_warns_when_no_request_type_is_set(monkeypatch):
    """Reads as connected, cannot file anything."""
    route(monkeypatch)
    result = await scf({}).test_connection()
    assert result["ok"] is True
    assert any("Request Type" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_the_check_nudges_a_basic_auth_connection_towards_a_token(monkeypatch):
    route(monkeypatch, questions=OTHER_QUESTIONS)
    conn = scf({"request_type_id": "other"}, {"username": "clerk@town.gov", "password": "pw"})
    result = await conn.test_connection()
    assert any("Personal Access Token" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_a_token_connection_is_not_nudged(monkeypatch):
    route(monkeypatch, questions=OTHER_QUESTIONS)
    result = await scf({"request_type_id": "other"}).test_connection()
    assert not any("Personal Access Token" in w for w in result.get("warnings", []))


# ---- auth --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_personal_access_token_is_sent_as_bearer(monkeypatch):
    """The documented scheme (https://dev.seeclickfix.com/v2/overview/authentication/)."""
    seen = route(monkeypatch)
    await scf({"request_type_id": "other"}, {"api_key": "tok-123"}).push_request(PAYLOAD)
    assert seen["requests"][0].headers["Authorization"] == "Bearer tok-123"


@pytest.mark.asyncio
async def test_a_token_wins_over_a_leftover_username_and_password(monkeypatch):
    """Both filled in is the normal state of a town mid-migration. The token is
    the one that should be used."""
    seen = route(monkeypatch)
    conn = scf({"request_type_id": "other"}, {"api_key": "tok-123", "username": "u", "password": "p"})
    await conn.push_request(PAYLOAD)
    assert seen["requests"][0].headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_username_and_password_still_authenticate(monkeypatch):
    """Legacy, not removed -- some towns still run a Basic service account."""
    seen = route(monkeypatch)
    conn = scf({"request_type_id": "other"}, {"username": "clerk@town.gov", "password": "pw"})
    await conn.push_request(PAYLOAD)
    assert seen["requests"][0].headers["Authorization"].startswith("Basic ")


# ---- pulling -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_pulls_are_org_scoped_when_an_organization_id_is_set(monkeypatch):
    """The org API is the only one that returns a town's private issues, and it
    does not depend on the place slug being spelled their way."""
    seen = route(monkeypatch)
    await scf({"organization_id": "4321"}).pull_updates()
    url = str(seen["requests"][0].url)
    assert "/organizations/4321/issues" in url
    assert "place_url" not in url


@pytest.mark.asyncio
async def test_pulls_fall_back_to_the_place_slug(monkeypatch):
    seen = route(monkeypatch)
    await scf({"place_url": "springfield"}).pull_updates()
    url = str(seen["requests"][0].url)
    assert "/organizations/" not in url and "place_url=springfield" in url


@pytest.mark.asyncio
async def test_the_poll_filters_on_updated_at_not_created_at(monkeypatch):
    """`after` filters creation time, so a two-year-old pothole closed this
    morning would never come back -- which is the only reason we poll."""
    from datetime import datetime, timezone
    seen = route(monkeypatch)
    await scf({}).pull_updates(since=datetime(2026, 8, 1, tzinfo=timezone.utc))
    url = str(seen["requests"][0].url)
    assert "updated_at_after=" in url


# ---- catalog -----------------------------------------------------------------

def test_the_token_is_the_first_credential_a_clerk_is_asked_for():
    """Field order is the recommendation. Username first taught every town to
    set up the scheme SeeClickFix no longer documents."""
    fields = [f["key"] for f in PLATFORM_CATALOG["civicplus"]["credential_fields"]]
    assert fields[0] == "api_key"
    assert fields.index("api_key") < fields.index("password")


def test_the_catalog_says_where_to_click_for_a_token():
    """A clerk who cannot find the token page does not have a token."""
    entry = PLATFORM_CATALOG["civicplus"]
    text = entry["setup_notes"] + " ".join(entry["what_you_need"]) + entry["field_help"]["api_key"]
    assert "Password & Security" in text
    assert "Personal Access Token" in text


def test_the_request_type_is_asked_for_rather_than_left_optional():
    """It is required on every create. Optional in the wizard meant every town
    that skipped it had a connection that passed its check and filed nothing."""
    fields = {f["key"]: f for f in PLATFORM_CATALOG["civicplus"]["config_fields"]}
    assert fields["request_type_id"]["required"] is True
    assert "answers" in fields and "organization_id" in fields
