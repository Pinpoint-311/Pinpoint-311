import { describe, it, expect } from 'vitest';
import { assignmentPayload, draftAfterDepartmentChange, staffForDepartment } from './assignment';

const users = [
    { username: 'roads.ann', departments: [{ id: 1 }] },
    { username: 'parks.bob', departments: [{ id: 2 }] },
    { username: 'both.cy', departments: [{ id: 1 }, { id: 2 }] },
    { username: 'no.dept', departments: [] },
];

describe('staffForDepartment', () => {
    it('offers only the department members, or everyone without a department', () => {
        expect(staffForDepartment(users, 2).map(u => u.username)).toEqual(['parks.bob', 'both.cy']);
        expect(staffForDepartment(users, null)).toHaveLength(4);
    });
});

describe('draftAfterDepartmentChange', () => {
    it('clears an assignee the new department does not have', () => {
        const next = draftAfterDepartmentChange({ departmentId: 1, assignedTo: 'roads.ann' }, 2, users);
        expect(next).toEqual({ departmentId: 2, assignedTo: null });
    });

    it('keeps an assignee who is also in the new department', () => {
        const next = draftAfterDepartmentChange({ departmentId: 1, assignedTo: 'both.cy' }, 2, users);
        expect(next).toEqual({ departmentId: 2, assignedTo: 'both.cy' });
    });

    it('keeps the assignee when the department is cleared, since anyone may then be picked', () => {
        const next = draftAfterDepartmentChange({ departmentId: 1, assignedTo: 'roads.ann' }, null, users);
        expect(next).toEqual({ departmentId: null, assignedTo: 'roads.ann' });
    });

    it('changes nothing when the same department is picked again', () => {
        const draft = { departmentId: 1, assignedTo: 'parks.bob' };
        expect(draftAfterDepartmentChange(draft, 1, users)).toBe(draft);
    });
});

describe('assignmentPayload', () => {
    it('sends explicit nulls so a department or assignee can be cleared', () => {
        const body = JSON.parse(JSON.stringify(assignmentPayload({ departmentId: null, assignedTo: '' })));
        expect(body).toEqual({ assigned_department_id: null, assigned_to: null });
    });

    it('sends the chosen pair as is', () => {
        expect(assignmentPayload({ departmentId: 3, assignedTo: 'parks.bob' }))
            .toEqual({ assigned_department_id: 3, assigned_to: 'parks.bob' });
    });
});
