/** The request-detail assignment controls on the staff dashboard: which staff
 *  a department offers, and what an edit sends to the server. */

export interface AssignmentDraft {
    departmentId: number | null;
    assignedTo: string | null;
}

export interface AssignableUser {
    username: string;
    departments?: { id: number }[];
}

/** Staff the assignee picker offers: the department's members, or everyone
 *  when the request has no department. */
export function staffForDepartment<T extends AssignableUser>(users: T[], departmentId: number | null): T[] {
    return departmentId ? users.filter(u => u.departments?.some(d => d.id === departmentId)) : users;
}

/** The draft after the department picker changes.
 *
 *  The assignee used to be carried over unchanged. The staff picker is
 *  filtered to the new department, so the old person vanished from view but
 *  was still sent, and the request ended up with a department and an assignee
 *  from somewhere else. Now the assignee is kept only when they are someone
 *  the new department offers; otherwise it is cleared. */
export function draftAfterDepartmentChange(
    current: AssignmentDraft,
    departmentId: number | null,
    users: AssignableUser[],
): AssignmentDraft {
    if (departmentId === current.departmentId) return current;
    const stillOffered = current.assignedTo !== null
        && staffForDepartment(users, departmentId).some(u => u.username === current.assignedTo);
    return { departmentId, assignedTo: stillOffered ? current.assignedTo : null };
}

/** What Save sends. Both fields always go, with an explicit null for "none":
 *  `undefined` is dropped by JSON.stringify, so a cleared department never
 *  reached the server and the dropdown snapped back. */
export function assignmentPayload(draft: AssignmentDraft): {
    assigned_department_id: number | null;
    assigned_to: string | null;
} {
    return {
        assigned_department_id: draft.departmentId,
        assigned_to: draft.assignedTo || null,
    };
}
