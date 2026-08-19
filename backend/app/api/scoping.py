"""Department scoping for staff access to one service request.

`GET /api/open311/v2/requests.json` has scoped its LIST by department for a
while: a non-admin staffer sees requests routed to a department they belong to,
requests assigned to them by name, and unrouted requests that still need
triage. Admins see everything.

None of the by-id endpoints applied that rule. Every request id is printed on
the public map, so a Parks staffer could read one off the map and
`GET /api/requests/{id}.json` a Police complaint -- receiving the reporter's
first name, last name, email, phone, the staff notes and the moderation flag
reason -- and could then change its status, delete it, and comment on it. The
list endpoint was a curtain in front of an open door.

The rule lives here rather than in open311.py because three modules need it
(open311, comments, integrations), and because a second copy of it is exactly
how the list and the by-id endpoints drifted apart in the first place.
"""

from typing import Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServiceRequest, User


async def department_scope_filters(db: AsyncSession, current_user: User) -> Sequence:
    """WHERE clauses restricting a staff user to their departments' requests.

    Empty for an admin, matching the list endpoint's rule exactly.
    """
    if getattr(current_user, "role", None) == "admin":
        return ()

    from app.models import user_departments

    dept_rows = await db.execute(
        select(user_departments.c.department_id).where(
            user_departments.c.user_id == current_user.id
        )
    )
    my_dept_ids = [row[0] for row in dept_rows.all()]

    scope = [
        ServiceRequest.assigned_to == current_user.username,
        # Nobody has routed it yet, so it is everyone's to triage. The same
        # allowance the list makes.
        ServiceRequest.assigned_department_id.is_(None),
    ]
    if my_dept_ids:
        scope.append(ServiceRequest.assigned_department_id.in_(my_dept_ids))
    return (or_(*scope),)


async def scoped_request(
    db: AsyncSession,
    current_user: User,
    *,
    service_request_id: Optional[str] = None,
    record_id: Optional[int] = None,
    include_deleted: bool = False,
    options: Sequence = (),
) -> Optional[ServiceRequest]:
    """One request, if this staff user is allowed to see it. None otherwise.

    None rather than a distinct "forbidden" answer on purpose: telling a Parks
    staffer that REQ-...-1234 exists but belongs to Police is itself a
    disclosure, and every caller renders this as the same 404 an unknown id gets.

    `include_deleted` defaults to False because most callers work live records.
    The endpoints that exist *because* a record was deleted -- restore, and the
    audit log recording who deleted it -- pass True.
    """
    query = select(ServiceRequest)
    for option in options:
        query = query.options(option)
    if service_request_id is not None:
        query = query.where(ServiceRequest.service_request_id == service_request_id)
    if record_id is not None:
        query = query.where(ServiceRequest.id == record_id)
    if not include_deleted:
        query = query.where(ServiceRequest.deleted_at.is_(None))
    for clause in await department_scope_filters(db, current_user):
        query = query.where(clause)
    return (await db.execute(query)).scalar_one_or_none()
