import { describe, it, expect, beforeEach } from 'vitest';

import { NEW_FOR_MS, bellAppearance, feedKeysFor, markKeyRead, markKeysRead, readIdsFromStorage, readKey, unreadCount } from './activityBell';
import { ServiceRequest } from '../types';

/**
 * The bell went grey-forever in production for the most ordinary setup there
 * is: every service auto-routes to a department, and the town's one admin
 * belongs to no department. Routed report + empty membership list = counted
 * for nobody. These tests pin the relevance rule the fix installed: the server
 * already scoped the list to what this user may see, so a user with no
 * memberships owns everything in it, and a by-name assignment always counts.
 */

const NOW = Date.UTC(2026, 7, 7, 12, 0, 0);

function req(over: Partial<ServiceRequest>): ServiceRequest {
    return {
        service_request_id: 'REQ-1',
        status: 'open',
        requested_datetime: new Date(NOW - 60 * 60 * 1000).toISOString(), // an hour old
        assigned_department_id: null,
        assigned_to: null,
        ...over,
    } as ServiceRequest;
}

function count(requests: ServiceRequest[], over: Partial<Parameters<typeof unreadCount>[0]> = {}) {
    return unreadCount({ requests, readIds: new Set(), departmentIds: [], now: NOW, ...over });
}

describe('unreadCount relevance', () => {
    it('counts a routed report for a user with no department memberships (the live bug)', () => {
        // Auto-routed to Public Works (4); admin belongs to no department.
        expect(count([req({ assigned_department_id: 4 })], { departmentIds: [] })).toBe(1);
    });

    it('counts a report routed to one of my departments', () => {
        expect(count([req({ assigned_department_id: 4 })], { departmentIds: [4] })).toBe(1);
    });

    it('does not count a report routed to somebody else\'s department', () => {
        // With memberships configured, other departments' reports are theirs.
        expect(count([req({ assigned_department_id: 5 })], { departmentIds: [4] })).toBe(0);
    });

    it('counts a report assigned to me by name even in another department', () => {
        expect(count(
            [req({ assigned_department_id: 5, assigned_to: 'pat' })],
            { departmentIds: [4], username: 'pat' },
        )).toBe(1);
    });

    it('always counts an unrouted report — it is everybody\'s until claimed', () => {
        expect(count([req({ assigned_department_id: null })], { departmentIds: [4] })).toBe(1);
    });
});

describe('unreadCount recency and read state', () => {
    it('ignores the backlog (older than the 24h window) and closed reports', () => {
        const old = req({ requested_datetime: new Date(NOW - NEW_FOR_MS - 1000).toISOString() });
        const closed = req({ status: 'closed' });
        expect(count([old, closed])).toBe(0);
    });

    it('ignores unparseable and missing dates rather than counting 1970 as news', () => {
        expect(count([
            req({ requested_datetime: 'not-a-date' }),
            req({ requested_datetime: '' }),
        ])).toBe(0);
    });

    it('does not count a report already marked read, under the shared key', () => {
        const r = req({});
        expect(count([r], { readIds: new Set([readKey(r)]) })).toBe(0);
    });
});

describe('storage and appearance', () => {
    it('survives corrupted localStorage instead of blanking the header', () => {
        expect(readIdsFromStorage('{half written').size).toBe(0);
        expect(readIdsFromStorage(null).size).toBe(0);
        expect(readIdsFromStorage('["a", 3, "b"]')).toEqual(new Set(['a', 'b']));
    });

    it('turns amber only when there is something unread', () => {
        expect(bellAppearance(0).icon).toContain('white');
        expect(bellAppearance(2).icon).toContain('amber');
        expect(bellAppearance(2).label).toContain('2 new reports');
    });
});

describe('markKeyRead', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('persists the key under activityFeedRead and reports it as newly read', () => {
        expect(markKeyRead('new-REQ-1')).toBe(true);
        expect(readIdsFromStorage(localStorage.getItem('activityFeedRead')).has('new-REQ-1')).toBe(true);
    });

    it('is a no-op the second time — nothing left to clear', () => {
        markKeyRead('new-REQ-1');
        expect(markKeyRead('new-REQ-1')).toBe(false);
    });

    it('leaves other requests\' keys untouched', () => {
        markKeyRead('new-REQ-1');
        const stored = readIdsFromStorage(localStorage.getItem('activityFeedRead'));
        expect(stored.has('new-REQ-1')).toBe(true);
        expect(stored.has('new-REQ-2')).toBe(false);
    });

    it('drives unreadCount down to zero once a request is opened', () => {
        const r = req({});
        expect(count([r])).toBe(1);
        markKeyRead(readKey(r));
        const readIds = readIdsFromStorage(localStorage.getItem('activityFeedRead'));
        expect(count([r], { readIds })).toBe(0);
    });

    it('reports failure rather than throwing when storage rejects the write (Safari private mode, quota-full)', () => {
        const original = Storage.prototype.setItem;
        Storage.prototype.setItem = () => {
            throw new DOMException('QuotaExceededError');
        };
        try {
            expect(() => markKeyRead('new-REQ-1')).not.toThrow();
            expect(markKeyRead('new-REQ-1')).toBe(false);
        } finally {
            Storage.prototype.setItem = original;
        }
    });
});

describe('opening a request reads every notice for it', () => {
    beforeEach(() => localStorage.clear());

    it('covers new, needs-an-owner and the latest update', () => {
        const keys = feedKeysFor({ service_request_id: 'REQ-7', updated_datetime: '2026-10-20T10:00:00Z' });
        expect(keys).toEqual(['new-REQ-7', 'dept-REQ-7', `upd-REQ-7-${Date.parse('2026-10-20T10:00:00Z')}`]);
        expect(feedKeysFor({ service_request_id: 'REQ-8', updated_datetime: null })).toEqual(['new-REQ-8', 'dept-REQ-8']);
    });

    it('writes them once and reports whether anything was unread', () => {
        localStorage.setItem('activityFeedRead', JSON.stringify(['new-REQ-7']));
        expect(markKeysRead(['new-REQ-7', 'dept-REQ-7'])).toBe(true);
        expect(readIdsFromStorage(localStorage.getItem('activityFeedRead'))).toEqual(new Set(['new-REQ-7', 'dept-REQ-7']));
        expect(markKeysRead(['new-REQ-7', 'dept-REQ-7'])).toBe(false);
    });
});
