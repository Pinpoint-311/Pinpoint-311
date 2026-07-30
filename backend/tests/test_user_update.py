"""Tests for editing an existing staff member.

Staff details change constantly -- people move department, change surname, get a
new phone, leave -- and none of it was editable: the frontend had no updateUser
call at all, and the endpoint behind it had a bug that would have made the new
edit UI lie.

`update_user` looped over the submitted fields and setattr'd each one onto the
ORM object. That works for columns. `department_ids` is not a column; it is a
many-to-many relationship through a join table. Setting it bound a stray Python
attribute, the request returned 200 with the user's *old* departments in the
response, and nothing changed in the database. create_user always did this
correctly, which is what made the difference easy to miss.
"""

import pytest

from app.schemas import UserUpdate


def test_departments_are_not_a_plain_column():
    """The premise of the bug, pinned so it cannot be reintroduced by someone
    simplifying the handler back into a single setattr loop."""
    from app.models import User
    assert not hasattr(User, "department_ids"), (
        "department_ids is a request field, not a model attribute -- setattr on "
        "it silently does nothing"
    )
    assert hasattr(User, "departments")


def test_the_handler_no_longer_setattrs_department_ids():
    """Read the source: the fix is structural, and the failure it prevents is
    invisible at runtime (a 200 with stale data)."""
    import inspect
    from app.api import users

    src = inspect.getsource(users.update_user)
    assert 'update_data.pop("department_ids"' in src, \
        "department_ids must be removed before the setattr loop"
    assert "user.departments =" in src, \
        "departments must be assigned as a relationship"


# ---- what the schema accepts -------------------------------------------------

def test_phone_is_editable():
    """A column on User used for staff SMS alerts that the update schema simply
    did not include, so it could be set at creation and never changed."""
    assert "phone" in UserUpdate.model_fields


def test_every_field_is_optional():
    """Partial updates: editing a phone number must not blank a role."""
    for name, field in UserUpdate.model_fields.items():
        assert not field.is_required(), f"{name} should be optional on an update"


def test_an_empty_update_changes_nothing():
    assert UserUpdate().model_dump(exclude_unset=True) == {}


def test_only_submitted_fields_are_sent():
    sent = UserUpdate(phone="+15550100").model_dump(exclude_unset=True)
    assert sent == {"phone": "+15550100"}


def test_username_cannot_be_changed_through_this_schema():
    """The username keys the audit log and the identity provider. Renaming it
    orphans that history rather than correcting it, so the field is absent by
    design and the UI shows it read-only."""
    assert "username" not in UserUpdate.model_fields


def test_password_is_not_part_of_a_profile_edit():
    """Resetting a password is a separate, deliberately louder action with its
    own endpoint."""
    assert "password" not in UserUpdate.model_fields


def test_deactivating_is_expressible():
    """False must survive exclude_unset -- deactivation is the safe alternative
    to deletion for a records system, and a truthiness check would drop it."""
    sent = UserUpdate(is_active=False).model_dump(exclude_unset=True)
    assert sent == {"is_active": False}


def test_departments_can_be_cleared():
    """An empty list is a real instruction ("belongs to no department"), not an
    absent field."""
    sent = UserUpdate(department_ids=[]).model_dump(exclude_unset=True)
    assert sent == {"department_ids": []}
