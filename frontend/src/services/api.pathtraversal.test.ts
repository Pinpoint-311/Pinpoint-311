import { describe, it, expect, afterEach, vi } from 'vitest';

import { api, hasDotSegment } from './api';

/**
 * Client-side path traversal. `#track/<id>` is decoded and dropped into
 * `/open311/v2/public/requests/${id}`, so `#track/..%2F..%2F..%2Fusers` used
 * to send the signed-in user's token to `/api/users`. request() now refuses
 * any path with a dot segment, in every spelling the URL parser accepts.
 */

const originalFetch = globalThis.fetch;

describe('hasDotSegment', () => {
    it.each([
        '/open311/v2/public/requests/../../../users',
        '/requests/..',
        '/requests/./x',
        '/requests/%2e%2e/x',
        '/requests/%2E./x',
        '/requests/.%2e/x',
        '/requests/..\\..\\users',
        '/requests/.\t./x',
        '/requests/.\n./x',
    ])('flags %j', (p) => {
        expect(hasDotSegment(p)).toBe(true);
    });

    it.each([
        '/open311/v2/public/requests/REQ-2026-0001',
        '/services/',
        '/research/export/csv?start=2026-01-01&q=../x',
        '/files/report.v1..json',
        '/a/...',
    ])('allows %j', (p) => {
        expect(hasDotSegment(p)).toBe(false);
    });
});

describe('request() path guard', () => {
    afterEach(() => {
        api.setToken(null);
        globalThis.fetch = originalFetch;
    });

    it('never sends a traversing id to the network', async () => {
        const fetchMock = vi.fn();
        globalThis.fetch = fetchMock;
        api.setToken('staff-token');

        await expect(api.getPublicRequestDetail(decodeURIComponent('..%2F..%2F..%2Fusers')))
            .rejects.toThrow('Invalid request path');
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('still sends an ordinary id', async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true, status: 200, json: async () => ({ service_request_id: 'REQ-1' }),
        } as unknown as Response);
        globalThis.fetch = fetchMock;

        await api.getPublicRequestDetail('REQ-1');
        expect(fetchMock.mock.calls[0][0]).toBe('/api/open311/v2/public/requests/REQ-1');
    });
});
