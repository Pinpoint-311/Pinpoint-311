"""What leaves the building, and what does not.

`_build_payload` builds the record Pinpoint pushes to a county's Accela or
Tyler system. Two ways to get it wrong and they pull in opposite directions:

  too little   the external work order shows an open job the town closed three
               weeks ago, because the resolution never went with it
  too much     a resident's PII, a staff member's private note, or the reason a
               report was flagged ends up in a vendor system the town does not
               control and cannot scrub

Why this file no longer reads the source text
---------------------------------------------
It used to. `_payload_keys()` sliced `integrations.py` between the literal
`"    payload = {"` and the `share_pii` line and regex-matched `"key":`
literals. Everything about that was blind in the direction that matters:

  * changing the guard to `if _flag(config, "share_pii") or True:` ships the
    resident's name, email and phone to every vendor unconditionally, and the
    text between those two markers stays byte-for-byte identical -- the whole
    suite passed
  * `payload["staff_notes"] = sr.staff_notes` appended *after* the window is
    outside the slice and invisible
  * a `**{...}` spread contributes no `"key":` literal at all

So the payload is built for real now, from a stand-in request whose every
attribute carries a traceable sentinel, and the assertions are about the dict
that comes out. A field that leaks is a sentinel turning up where it should
not, whatever syntax put it there.

On free text and the share_pii gate
-----------------------------------
`custom_fields` and `description` are sent unconditionally, outside the gate,
and that is a decision rather than an oversight. Both are free text a resident
typed and both can name a third party -- `retention_scrub.py` says exactly that
about each of them. Gating one and not the other would be incoherent, and
gating both would mean the vendor receives a work order with no statement of
the problem, which is not a work order. The gate is about *contact* details:
the structured fields that make a record directly re-identifiable and the
resident directly reachable inside a system the town does not control. A town
that must keep free text out of a vendor system has a retention/redaction lever
for that; this flag is not it.
"""

import inspect
import types
from datetime import datetime, timezone

import pytest

# Guarded on submodules rather than packages, per test_migrate.py's note: an
# environment without Celery or SQLAlchemy skips instead of erroring at
# collection.
pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("celery.app")

integrations = pytest.importorskip("app.tasks.integrations")
models = pytest.importorskip("app.models")

_build_payload = integrations._build_payload
ServiceRequest = models.ServiceRequest


# ------------------------------------------------------------ the stand-in

# Four plaintext hybrid properties sit over the encrypted columns. Both names
# matter: the hybrids are what a leak would read, and the `_*_encrypted`
# columns are ciphertext that must never be sent under any flag.
PII_PROPERTIES = ("first_name", "last_name", "email", "phone")


def _column_names() -> list:
    """Mapped attribute names on ServiceRequest, from the mapper itself, so a
    column declared in any style is included."""
    from sqlalchemy import inspect as sa_inspect

    return list(sa_inspect(ServiceRequest).columns.keys())


def _sentinel_for(name: str, column) -> object:
    """A value traceable back to the attribute it came from, of a type the
    builder can handle.

    Every attribute gets one. That is what makes the "no None" assertion below
    work: a payload value that comes out None was read from something the model
    does not have.
    """
    type_name = type(column.type).__name__.lower()
    tag = f"SENTINEL::{name}"

    if "datetime" in type_name or "timestamp" in type_name:
        return datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    if "boolean" in type_name:
        return True
    if "float" in type_name or "numeric" in type_name:
        return 1.5
    if "integer" in type_name:
        return 7
    if "json" in type_name:
        # A dict so custom_fields/matched_asset keep their shape; the sentinel
        # lives inside it so a leak is still findable by string search.
        return {"sentinel": tag}
    return tag


def _stand_in(**overrides):
    """A ServiceRequest-shaped object with a sentinel in every attribute.

    A plain namespace rather than an ORM instance: assigning to the `first_name`
    hybrid runs the encryption setter, and this file is about what the payload
    builder reads, not about KMS.
    """
    from sqlalchemy import inspect as sa_inspect

    columns = sa_inspect(ServiceRequest).columns
    attrs = {name: _sentinel_for(name, columns[name]) for name in columns.keys()}

    # Plaintext hybrids over the encrypted columns.
    for prop in PII_PROPERTIES:
        attrs[prop] = f"SENTINEL::{prop}"

    # The relationship the builder must never read (it is resolved by
    # _dept_name against the session and passed in), plus the two link-shaped
    # fields the builder filters to http(s) URLs -- given real links so the
    # filter passes and the values are present to assert on.
    attrs["assigned_department"] = types.SimpleNamespace(name="SENTINEL::dept_relationship")
    attrs["media_urls"] = ["https://example.test/SENTINEL_media_urls.jpg"]
    attrs["completion_photo_url"] = "https://example.test/SENTINEL_completion_photo_url.jpg"

    attrs.update(overrides)
    return types.SimpleNamespace(**attrs)


def _flatten(value) -> str:
    """Every scalar in the payload as one searchable string, so a sentinel
    nested inside a dict or a list is found too."""
    if isinstance(value, dict):
        return " ".join(_flatten(k) + " " + _flatten(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


# ---------------------------------------------------------------- what goes

REQUIRED = {
    # Identity and what was reported
    "service_request_id", "service_code", "service_name", "description",
    "address", "lat", "long", "status", "requested_datetime",
    # Attachments, as links only
    "media_urls",
    # Routing
    "priority", "assigned_to", "assigned_department",
    # Outcome -- the half that was missing
    "closed_datetime", "closed_substatus", "completion_message",
    "completion_photo_url", "updated_datetime",
    # Context the far end can act on
    "source", "preferred_language", "matched_asset", "custom_fields",
}

PII_KEYS = set(PII_PROPERTIES)


def test_the_work_order_carries_everything_it_should():
    payload = _build_payload(_stand_in(), {}, "Public Works")
    missing = REQUIRED - set(payload)
    assert not missing, (
        f"the outbound work order is missing {sorted(missing)}. A field the "
        f"external system never receives is one the town has to re-key by hand."
    )


def test_the_payload_is_exactly_the_agreed_key_set():
    """The check the old regex could not make.

    Appending to the dict after it is built, spreading a comprehension over the
    model's columns, or adding a key below the PII block all change this set.
    None of them changed the text the previous version of this file read.
    """
    payload = _build_payload(_stand_in(), {}, "Public Works")
    unexpected = set(payload) - REQUIRED
    assert not unexpected, (
        f"the outbound work order has grown {sorted(unexpected)}. Add each to "
        f"REQUIRED with a reason, or take it back out of the payload."
    )


def test_the_resolution_travels_with_the_record():
    """`completion_message` was already pushed on a status change and was absent
    from the record push, so a platform that only ingests the initial create
    never learned how anything ended."""
    payload = _build_payload(_stand_in(), {}, "Public Works")
    for field in ("completion_message", "closed_datetime", "closed_substatus"):
        assert payload.get(field), f"{field} is not in the pushed record"


def test_every_payload_field_reads_something_that_exists():
    """No value may be None when every source attribute has a sentinel.

    This is how `due_date` was caught. It read
    `getattr(sr, "due_datetime", None)` -- and ServiceRequest has no
    `due_datetime`; that name exists only on the *inbound* ExternalRecord
    dataclass. The default swallowed the miss, so every work order Pinpoint has
    ever pushed carried `due_date: null`, and the old test asserted only that
    the string "due_date" appeared somewhere in the source.
    """
    payload = _build_payload(_stand_in(), {}, "Public Works")
    empty = sorted(k for k, v in payload.items() if v is None)
    assert not empty, (
        f"{empty} came out null from a request whose every attribute was set. "
        f"The field is reading an attribute ServiceRequest does not have (a "
        f"getattr default hides that), or filtering its own value away."
    )


def test_the_department_name_is_the_one_it_was_given():
    """Resolved by _dept_name against the session and passed in, never lazy
    loaded off the relationship -- which raises under the async engine."""
    payload = _build_payload(_stand_in(), {}, "Sanitation")
    assert payload["assigned_department"] == "Sanitation"
    assert "SENTINEL::dept_relationship" not in _flatten(payload)


# ------------------------------------------------------------ what does not

NEVER = {
    # Internal identifiers and storage
    "id", "location", "assigned_department_id",
    # Encrypted PII columns. The plaintext equivalents are sent only behind the
    # share_pii flag; these are the ciphertext and must never be sent at all.
    "_first_name_encrypted", "_last_name_encrypted",
    "_email_encrypted", "_phone_encrypted",
    # Written by staff, for staff.
    "staff_notes",
    # The legal hold and the content-moderation flag, plus the moderation text
    # explaining the latter. None is the vendor's business, and flag_reason can
    # quote what a resident wrote. (These were one column until the hold was
    # split out; both stay out of the payload.)
    "legal_hold", "flagged", "flag_reason",
    # Deletion and archival bookkeeping.
    "deleted_at", "deleted_by", "delete_justification", "archived_at",
    # Where the report is listed on Pinpoint's own tracker and map is a Pinpoint
    # setting, whether the resident chose it (is_public) or staff did
    # (public_archived). Neither says anything about the work order.
    "is_public", "public_archived",
    # AI output. Sending it copies a generated assessment of a resident's
    # report into a system the retention policy cannot reach -- the scrub
    # clears these columns here and would leave the vendor's copy untouched.
    "ai_analysis", "ai_summary", "ai_classification", "ai_analyzed_at",
    # The optional platform-feedback module. These are not ServiceRequest
    # columns -- they live on `platform_feedback` and on `system_settings` --
    # and they are listed here anyway, because "the payload builder happens not
    # to read that table" is an accident and this list is a decision.
    #
    # A resident's opinion of Pinpoint is not part of a work order, and
    # aggregate sentiment about a vendor is not something to hand that vendor.
    # `platform_feedback_email` is a town's support mailbox, which has no
    # business in a county system either.
    "platform_experience", "submitted_at", "platform_feedback_email",
    # Photos the redactor could not clear. These are UNREDACTED -- the whole
    # reason they are held out of media_urls is that nothing ever established
    # there is no face in them -- and they are waiting on a staff decision that
    # has not been made. Pushing one to a vendor would copy, into a system our
    # retention policy cannot reach, exactly the image we declined to publish
    # ourselves. A photo staff release moves into media_urls and travels the
    # normal way from there.
    "media_pending_review",
}


@pytest.mark.parametrize("field", sorted(NEVER))
def test_internal_fields_do_not_leave_the_building(field):
    """By value as well as by key.

    `payload["notes"] = sr.staff_notes` renames the leak and a key check misses
    it. The sentinel does not care what it was called on the way out.
    """
    payload = _build_payload(_stand_in(), {}, "Public Works")
    assert field not in payload, (
        f"{field} is being pushed to external platforms. See NEVER in this file "
        f"for why it should not be."
    )
    assert f"SENTINEL::{field}" not in _flatten(payload), (
        f"the value of {field} is in the outbound payload under another key. "
        f"See NEVER in this file."
    )


def test_pii_is_not_sent_when_the_flag_is_off():
    """The mutation this file exists for.

    Changing the guard to `if _flag(config, "share_pii") or True:` ships four
    contact fields to every vendor. Under the old source-text version of this
    file, all 2055 tests still passed.
    """
    for config in ({}, {"share_pii": False}, {"share_pii": "no"}, {"share_pii": "0"}):
        payload = _build_payload(_stand_in(), config, "Public Works")
        present = PII_KEYS & set(payload)
        assert not present, (
            f"contact details {sorted(present)} are in the payload with "
            f"share_pii={config.get('share_pii')!r}"
        )
        flat = _flatten(payload)
        for prop in PII_PROPERTIES:
            assert f"SENTINEL::{prop}" not in flat, (
                f"the resident's {prop} is in the outbound payload with "
                f"share_pii off, under some other key"
            )


@pytest.mark.parametrize("truthy", [True, "true", "True", "1", "yes", "on"])
def test_pii_is_sent_when_the_flag_is_on(truthy):
    """The other direction: a town that switched sharing on must actually get
    it, including when the admin UI hands the flag over as a string."""
    payload = _build_payload(_stand_in(), {"share_pii": truthy}, "Public Works")
    assert PII_KEYS <= set(payload)
    for prop in PII_PROPERTIES:
        assert payload[prop] == f"SENTINEL::{prop}"
    # And nothing else came along with them.
    assert set(payload) - REQUIRED == PII_KEYS


def test_the_ciphertext_is_never_sent_under_any_flag():
    """The hybrid properties are what sharing means. The `_*_encrypted` columns
    behind them are ciphertext -- sending those is not a privacy control, it is
    handing a vendor a blob it cannot use and we cannot revoke."""
    for config in ({}, {"share_pii": True}):
        flat = _flatten(_build_payload(_stand_in(), config, "Public Works"))
        for prop in PII_PROPERTIES:
            assert f"SENTINEL::_{prop}_encrypted" not in flat


def test_free_text_is_sent_and_that_is_a_recorded_decision():
    """See the module docstring. `description` and `custom_fields` are both free
    text a resident typed, both can name a third party, and both go
    unconditionally. Pinned as a pair, so changing one forces a decision about
    the other rather than leaving the reasoning half-applied."""
    payload = _build_payload(_stand_in(), {}, "Public Works")
    assert payload["description"] == "SENTINEL::description"
    assert payload["custom_fields"] == {"sentinel": "SENTINEL::custom_fields"}


def test_every_column_is_either_sent_or_deliberately_not():
    """The list that stops this file going stale.

    A new column on ServiceRequest is a decision: it goes to the work order or
    it does not. Left unlisted, it silently does not -- which is the safe
    default but not a recorded one, and the next person cannot tell whether it
    was considered.
    """
    columns = set(_column_names())
    accounted = REQUIRED | NEVER | PII_KEYS
    # Columns that map onto a differently-named payload key.
    accounted |= {"manual_priority_score", "priority",
                  "requested_datetime", "media_urls", "matched_asset",
                  "custom_fields", "closed_datetime", "updated_datetime"}
    unaccounted = columns - accounted
    assert not unaccounted, (
        f"new ServiceRequest columns nobody has ruled on: {sorted(unaccounted)}. "
        f"Add each to REQUIRED (and to the payload) or to NEVER."
    )


def test_the_work_order_has_never_heard_of_platform_feedback():
    """Stronger than the NEVER list, which only checks payload keys.

    The platform-feedback table must not be read, joined or imported anywhere in
    the outbound integration path at all -- there is no version of "a bit of it
    goes to Accela" that is correct. A resident's opinion of this software is
    not work-order data, and aggregate sentiment about a vendor is not something
    to hand that vendor.

    Checked against the module source rather than a built payload because the
    point is stronger than absence from one payload: the push path must not so
    much as touch the table, in any branch, including ones a stand-in record
    would not exercise.
    """
    source = inspect.getsource(integrations)
    for token in ("PlatformFeedback", "platform_feedback", "platform_experience"):
        assert token not in source, (
            f"{token} appears in the govtech push path. Feedback about Pinpoint "
            f"is not work-order data."
        )


def test_attachments_are_links_and_never_inline_blobs():
    """Photos are stored base64 in some deployments. Posting a few megabytes of
    data URI into a county API is how an integration gets rate-limited off."""
    blob = "data:image/jpeg;base64," + "A" * 4096
    sr = _stand_in(media_urls=["https://example.test/ok.jpg", blob],
                   completion_photo_url=blob)
    payload = _build_payload(sr, {}, "Public Works")
    assert payload["media_urls"] == ["https://example.test/ok.jpg"]
    assert payload["completion_photo_url"] is None
    assert "base64" not in _flatten(payload)


def test_the_priority_the_town_set_wins_over_the_stored_one():
    """`manual_priority_score` is the human-approved number; `priority` is the
    default. Sending the wrong one routes the job into the wrong queue."""
    sr = _stand_in(manual_priority_score=9.0, priority=2)
    assert _build_payload(sr, {}, "Public Works")["priority"] == 9.0
    sr = _stand_in(manual_priority_score=None, priority=2)
    assert _build_payload(sr, {}, "Public Works")["priority"] == 2
