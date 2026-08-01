import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { api } from './api';

/**
 * Being signed out at random, while clicking around.
 *
 * Every 401 from any endpoint ran the auto-logout, which deletes the token
 * from localStorage. That is right for an expired session and wrong for
 * everything else -- and "everything else" turned out to include a request
 * that had not been given the token yet.
 *
 * AuthProvider restores the token inside a useEffect. React runs child effects
 * before parent effects, so a page that loads data on mount can get its first
 * request out the door before the token is back. ProtectedRoute holds
 * protected pages back until auth resolves, but the resident portal is public,
 * ungated, and calls a staff-only endpoint on mount. So: reload the portal
 * while logged in, one request goes out bare, 401 comes back, and the handler
 * throws away a session that had hours left on it.
 *
 * The rule is that a 401 only ends a session that was actually offered.
 */

const originalFetch = globalThis.fetch;

function respond(status: number) {
    return vi.fn().mockResolvedValue({
        ok: status >= 200 && status < 300,
        status,
        json: async () => ({ detail: 'nope' }),
    } as unknown as Response);
}

describe('auto-logout on 401', () => {
    let loggedOut: number;

    beforeEach(() => {
        loggedOut = 0;
        api.setOnUnauthorized(() => { loggedOut += 1; });
        api.setToken(null);
    });

    afterEach(() => {
        api.setOnUnauthorized(null);
        api.setToken(null);
        globalThis.fetch = originalFetch;
    });

    it('signs you out when a request that carried a session is rejected', async () => {
        // The case the handler exists for: the token was sent and the server
        // said it is no longer good.
        globalThis.fetch = respond(401);
        api.setToken('a-real-token');

        await expect(api.getMe()).rejects.toThrow();
        expect(loggedOut).toBe(1);
    });

    it('does not sign you out over a request that carried no session', async () => {
        // The regression. This is the request that raced ahead of the token
        // being restored, and it was deleting the token it raced.
        globalThis.fetch = respond(401);
        api.setToken(null);

        await expect(api.getMe()).rejects.toThrow();
        expect(loggedOut).toBe(0);
    });

    it('does not sign you out over a permission error', async () => {
        // 403 is "you are logged in and may not do this" -- a staff user on an
        // admin endpoint. Ending their session for it would be absurd, and it
        // is one typo in the status check away.
        globalThis.fetch = respond(403);
        api.setToken('a-real-token');

        await expect(api.getMe()).rejects.toThrow();
        expect(loggedOut).toBe(0);
    });

    it('does not sign you out over a missing record or a server fault', async () => {
        for (const status of [404, 422, 500, 503]) {
            globalThis.fetch = respond(status);
            api.setToken('a-real-token');
            await expect(api.getMe()).rejects.toThrow();
        }
        expect(loggedOut).toBe(0);
    });

    it('still surfaces the failure to the caller either way', async () => {
        // Suppressing the logout must not turn into suppressing the error --
        // the page still has to know its request did not work.
        globalThis.fetch = respond(401);
        api.setToken(null);
        await expect(api.getMe()).rejects.toThrow();
    });
});
