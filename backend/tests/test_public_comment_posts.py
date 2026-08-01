"""A resident's comment has to reach the endpoint that stores it.

It did not. `POST /open311/v2/public/requests/{id}/comments` declares its
content as `Body(..., embed=True)`, and the browser sent it as a query string
with no body at all. FastAPI answered 422 on every attempt, the component
logged it to `console.error`, and the resident saw the button stop spinning and
nothing appear. Reproduced against a real FastAPI app before fixing:

    as the browser sends it : 422 {"detail":[{"type":"missing",
                                   "loc":["body","content"],...}]}
    with a JSON body       : 200

Nothing caught it, because nothing tested it. Both halves of the contract were
individually reasonable and no test looked at them together -- which is the
same shape as every other bug in this codebase that survived a release: a thing
that stores fine, reads back fine, and silently does nothing.

So this file pins the two halves against each other. It lives in the backend
suite for the reason the other frontend contract tests do: it is the suite that
runs on every change, with no npm install and no browser.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = ROOT / "backend/app/api/open311.py"
API_CLIENT = ROOT / "frontend/src/services/api.ts"
COMPONENT = ROOT / "frontend/src/components/TrackRequests.tsx"

ROUTE = "/public/requests/{request_id}/comments"


@pytest.fixture(scope="module")
def handler() -> ast.AsyncFunctionDef:
    """The `add_public_comment` function, as a syntax tree.

    Found by name rather than by line number so the test survives the file
    being reordered, and parsed rather than grepped so a mention of `Query` in
    a docstring two functions away cannot decide the answer. An earlier test in
    this suite was written the grep way and tripped over its own explanation.
    """
    tree = ast.parse(ENDPOINT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "add_public_comment":
            return node
    pytest.fail("no add_public_comment handler in open311.py")


def _content_default(handler: ast.AsyncFunctionDef) -> ast.AST:
    args = handler.args.args + handler.args.kwonlyargs
    names = [a.arg for a in args]
    assert "content" in names, f"handler takes {names}, expected a `content` parameter"
    # Defaults align to the tail of the positional list.
    positional = handler.args.args
    padding = len(positional) - len(handler.args.defaults)
    for i, arg in enumerate(positional):
        if arg.arg == "content":
            assert i >= padding, "`content` has no default, so nothing declares where it is read from"
            return handler.args.defaults[i - padding]
    for arg, default in zip(handler.args.kwonlyargs, handler.args.kw_defaults):
        if arg.arg == "content":
            return default
    pytest.fail("could not locate the default for `content`")


def _source_of(node: ast.AST) -> str:
    return ast.dump(node)


def test_the_endpoint_reads_the_comment_from_the_body(handler):
    """`Body(...)`, not `Query(...)`.

    The body is the right place and this test is not neutral about which side
    should have moved. A URL is written to the access log, the reverse proxy,
    the CDN, the browser's history and the Referer header of the next click. A
    resident's comment can name a neighbour or describe what happened to them.
    Switching the endpoint to `Query` would make this pass and would put that
    text in five logs a town never decided to keep it in.
    """
    default = _content_default(handler)
    assert isinstance(default, ast.Call), "`content` should be declared with Body(...)"
    called = default.func.id if isinstance(default.func, ast.Name) else getattr(default.func, "attr", "")
    assert called == "Body", f"`content` is read from {called}(...), expected Body(...)"


def test_the_body_is_a_named_field_rather_than_a_bare_string(handler):
    """`embed=True` means `{"content": "..."}`.

    Without it FastAPI expects the bare JSON string as the whole body, which no
    caller writes by accident and no Open311 client sends. The frontend test
    below pins the matching `JSON.stringify({ content })`; the pair is the
    contract.
    """
    default = _content_default(handler)
    embed = [kw for kw in default.keywords if kw.arg == "embed"]
    assert embed and getattr(embed[0].value, "value", False) is True, (
        "Body(..., embed=True) -- the frontend sends {\"content\": ...}"
    )


def test_a_comment_has_a_length_the_endpoint_will_accept(handler):
    """Unauthenticated and public, so the bound is the only thing between a town
    and somebody pasting a novel into its database."""
    default = _content_default(handler)
    bounds = {kw.arg: getattr(kw.value, "value", None) for kw in default.keywords}
    assert bounds.get("min_length", 0) >= 1, "an empty comment is not a comment"
    assert bounds.get("max_length"), "no upper bound on an unauthenticated public write"


@pytest.fixture(scope="module")
def client_source() -> str:
    if not API_CLIENT.exists():
        pytest.skip("frontend not present in this checkout")
    return API_CLIENT.read_text()


def _add_public_comment(client_source: str) -> str:
    body = re.search(r"async addPublicComment\(.*?\n    \}", client_source, re.S)
    assert body, "no addPublicComment in the api client"
    return body.group(0)


def test_the_browser_sends_the_comment_in_the_body(client_source):
    """The half that was wrong. `JSON.stringify({ content })` and a POST."""
    call = _add_public_comment(client_source)
    assert "method: 'POST'" in call
    assert "JSON.stringify({ content })" in call, (
        "the comment must be sent as a JSON body -- a POST with no body is "
        "answered 422 by the endpoint above and the comment is lost"
    )


def test_the_browser_does_not_put_the_comment_in_the_url(client_source):
    """The specific regression. This is what shipped, and it 422'd every time.

    Checked separately from the test above because adding a body while leaving
    the query string in place would pass that one and still leak the text into
    every log between the resident and the database.
    """
    call = _add_public_comment(client_source)
    assert "?content=" not in call, "the comment text is in the URL"
    assert "encodeURIComponent(content)" not in call, "the comment text is in the URL"


@pytest.fixture(scope="module")
def component_source() -> str:
    if not COMPONENT.exists():
        pytest.skip("frontend not present in this checkout")
    return COMPONENT.read_text()


def _handle_add_comment(component_source: str) -> str:
    handler = re.search(r"const handleAddComment = async \(\) => \{.*?\n    \};",
                        component_source, re.S)
    assert handler, "no handleAddComment in TrackRequests"
    return handler.group(0)


def test_a_rejected_comment_tells_the_resident_why(component_source):
    """The endpoint's moderation branch raises 400 with a sentence addressed to
    the person who typed the comment. It was going to `console.error`.

    That is the failure mode that made this bug take a release to notice: a
    rejected comment, a broken endpoint and a dropped network request all
    looked identical from the resident's chair -- the button stops spinning and
    nothing appears.
    """
    handler = _handle_add_comment(component_source)

    # The catch block specifically. Checking the whole handler is not enough:
    # it opens with `setCommentError(null)` to clear the previous attempt, and
    # that alone satisfied an earlier version of this assertion even with the
    # catch reverted to console.error. The mutation survived and the test was
    # wrong, not the code.
    catch = handler[handler.index("} catch"):]
    assert "setCommentError(" in catch, (
        "the failure has to reach the screen, not just the console"
    )
    assert "console." not in catch, (
        "the console is not a way of telling a resident anything"
    )
    assert "commentError &&" in component_source, "the error state is set but never rendered"


def test_the_message_shown_is_the_one_the_endpoint_wrote(component_source):
    """The moderation rejection names what to do about it -- "please rephrase
    without offensive content". A generic "something went wrong" in its place
    leaves the resident retyping the same comment into the same refusal."""
    catch = _handle_add_comment(component_source)
    catch = catch[catch.index("} catch"):]
    assert "err.message" in catch, "the server's own sentence has to be preferred"
    assert re.search(r"instanceof Error", catch), (
        "a non-Error rejection has to fall back to something readable rather "
        "than rendering [object Object]"
    )


def test_a_comment_reaches_the_timeline(handler):
    """`comment_added` is a documented action on RequestAuditLog and is
    rendered in both the resident tracker and the staff dashboard. Nothing
    anywhere wrote one, so a timeline that showed a report being filed, routed
    and closed silently omitted every word said about it in between.
    """
    written = [
        node for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "RequestAuditLog"
    ]
    assert written, "a public comment writes no timeline entry"
    kwargs = {kw.arg: getattr(kw.value, "value", None) for kw in written[0].keywords}
    assert kwargs.get("action") == "comment_added"
    assert kwargs.get("actor_type") == "resident"


def test_the_timeline_entry_does_not_carry_the_comment_text(handler):
    """The words live in `request_comments`, which is what the retention policy
    scrubs. The audit trail is append-only and hash-chained, so a copy here
    would be a copy the scrub cannot reach and the chain will not let it
    rewrite -- a redacted comment with its full text still on the timeline
    beneath it."""
    written = [
        node for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "RequestAuditLog"
    ][0]
    for kw in written.keywords:
        assert not (isinstance(kw.value, ast.Name) and kw.value.id == "content"), (
            f"the comment text is being copied into the audit trail as {kw.arg}"
        )


def test_the_public_timeline_hides_internal_notes():
    """Staff notes are written to the same timeline with new_value="internal".
    Showing even that one happened tells the public that a report was discussed
    privately, which is the thing the internal/external split exists to keep
    separate."""
    source = ENDPOINT.read_text()
    public = source[source.index("async def get_public_audit_log"):]
    public = public[:public.index("\n@router")]
    assert "comment_added" in public, "resident comments never reach the public timeline"
    assert 'new_value == "external"' in public, (
        "the public timeline does not distinguish an internal note from a reply"
    )


def test_the_public_tracker_reads_the_public_timeline(component_source):
    """The tracker is opened by whoever holds the link, and that is a person
    with no session. Calling the staff endpoint answered 401 every time, so the
    timeline was empty for exactly the audience it was built for."""
    assert "api.getPublicAuditLog(" in component_source
    assert "api.getAuditLog(" not in component_source, (
        "the staff audit endpoint requires a session this page never has"
    )


def test_what_somebody_typed_survives_a_failed_post(component_source):
    """Clearing the box before the save is confirmed loses the comment to any
    blip, and the resident has no copy of it."""
    body = _handle_add_comment(component_source)
    cleared = body.index("setNewComment('')")
    posted = body.index("api.addPublicComment")
    assert posted < cleared, "the box is cleared before the comment is known to be saved"
    assert cleared < body.index("} catch"), "clearing must be on the success path only"
