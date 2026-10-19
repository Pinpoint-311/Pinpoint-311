// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, waitFor, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * The SSO callback no longer puts the session token in the URL.
 *
 * It used to redirect to /login?token=<jwt>, leaving an eight-hour bearer token
 * in browser history, proxy logs and the next page's Referer. It now redirects
 * with a single-use, 60-second ?login_code=, which this page must (1) strip
 * from the address bar straight away and (2) trade for the token over POST,
 * exactly once. A ?token= in the URL is never accepted as a session.
 */

const setToken = vi.fn(async () => { });

vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { township_name: 'Testville' }, isLoading: false, refreshSettings: () => { } }),
}));

vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({ setToken, isAuthenticated: false, user: null }),
}));

import Login from './Login';

type Call = { url: string; init?: RequestInit };
let calls: Call[];

function mockFetch(exchange: { ok: boolean; body: unknown; status?: number }) {
    calls = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        if (url.startsWith('/api/auth/exchange')) {
            return {
                ok: exchange.ok,
                status: exchange.status ?? (exchange.ok ? 200 : 401),
                json: async () => exchange.body,
            };
        }
        return { ok: true, status: 200, json: async () => ({ auth0_configured: true, provider: 'auth0', provider_name: 'Auth0' }) };
    }) as unknown as typeof fetch);
}

function visit(search: string) {
    window.history.replaceState(null, '', `/login${search}`);
    return render(
        <MemoryRouter initialEntries={[`/login${search}`]}>
            <Login />
        </MemoryRouter>,
    );
}

const exchangeCalls = () => calls.filter(c => c.url.startsWith('/api/auth/exchange'));

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState(null, '', '/');
});

describe('signing in from the SSO callback', () => {
    it('trades the code for a token over POST and hands the token to the session', async () => {
        mockFetch({ ok: true, body: { access_token: 'jwt-123', token_type: 'bearer' } });

        visit('?login_code=abc123');

        await waitFor(() => expect(setToken).toHaveBeenCalledWith('jwt-123'));
        const [call] = exchangeCalls();
        expect(call.init?.method).toBe('POST');
        expect(JSON.parse(String(call.init?.body))).toEqual({ code: 'abc123' });
    });

    it('strips the code from the address bar before the exchange answers', async () => {
        mockFetch({ ok: true, body: { access_token: 'jwt-123', token_type: 'bearer' } });

        visit('?login_code=abc123&keep=1');

        expect(window.location.search).not.toContain('login_code');
        expect(window.location.search).toContain('keep=1');
        expect(window.location.pathname).toBe('/login');
        await waitFor(() => expect(setToken).toHaveBeenCalled());
    });

    it('spends the code once, even when the page re-renders', async () => {
        mockFetch({ ok: true, body: { access_token: 'jwt-123', token_type: 'bearer' } });

        const { rerender } = visit('?login_code=once');
        rerender(
            <MemoryRouter initialEntries={['/login?login_code=once']}>
                <Login />
            </MemoryRouter>,
        );

        await waitFor(() => expect(setToken).toHaveBeenCalled());
        expect(exchangeCalls()).toHaveLength(1);
    });

    it('shows an error and starts no session when the code is refused', async () => {
        mockFetch({ ok: false, body: { detail: 'This sign-in has expired or was already used. Sign in again.' } });

        visit('?login_code=stale');

        await waitFor(() => expect(screen.getByText(/expired or was already used/)).toBeTruthy());
        expect(setToken).not.toHaveBeenCalled();
        expect(window.location.search).not.toContain('login_code');
    });

    it('never takes a session from a ?token= in the URL, and strips it', async () => {
        mockFetch({ ok: true, body: {} });

        visit('?token=attacker-chosen-jwt');

        await waitFor(() => expect(calls.length).toBeGreaterThan(0));
        expect(setToken).not.toHaveBeenCalled();
        expect(exchangeCalls()).toHaveLength(0);
        expect(window.location.search).not.toContain('token');
    });
});
