// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, cleanup, waitFor, act } from '@testing-library/react';
import { AuthProvider, useAuth } from './AuthContext';

/**
 * Signing out tells the server who is signing out.
 *
 * logout() used to forget the token and then call /api/auth/logout with no
 * Authorization header -- a guaranteed 401, so the server never revoked or
 * audited anything. The token must go with the call, and the local session
 * must still be cleared at once.
 */

let calls: { url: string; init?: RequestInit }[] = [];

function stubFetch() {
    calls = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        if (url.startsWith('/api/auth/me')) {
            return { ok: true, status: 200, json: async () => ({ id: 1, username: 'clerk', role: 'staff' }) };
        }
        if (url.startsWith('/api/auth/logout')) {
            return { ok: true, status: 200, json: async () => ({ logout_url: window.location.origin }) };
        }
        return { ok: true, status: 200, json: async () => ({}) };
    }) as unknown as typeof fetch);
}

let auth: ReturnType<typeof useAuth> | null = null;
function Probe() {
    auth = useAuth();
    return null;
}

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
    auth = null;
});

describe('logout', () => {
    it('sends the session token with the sign-out call and clears it locally', async () => {
        localStorage.setItem('token', 'jwt-abc');
        stubFetch();
        render(<AuthProvider><Probe /></AuthProvider>);
        await waitFor(() => expect(auth?.isAuthenticated).toBe(true));

        await act(async () => { await auth!.logout(); });

        const logoutCall = calls.find(c => c.url.startsWith('/api/auth/logout'));
        expect(logoutCall).toBeTruthy();
        const headers = (logoutCall!.init?.headers || {}) as Record<string, string>;
        expect(headers.Authorization).toBe('Bearer jwt-abc');
        expect(localStorage.getItem('token')).toBeNull();
        expect(auth!.isAuthenticated).toBe(false);
    });
});
