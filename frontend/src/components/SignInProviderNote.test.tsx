// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import adminConsoleSource from '../pages/AdminConsole.tsx?raw';
import type { AuthStatus } from '../services/api';

const getAuthStatus = vi.fn<() => Promise<AuthStatus>>();
vi.mock('../services/api', () => ({
    api: { getAuthStatus: () => getAuthStatus() },
}));

import SignInProviderNote from './SignInProviderNote';

/**
 * The Add User form said "Users log in via Auth0 SSO" to every town, including
 * the ones whose staff sign in with Microsoft Entra ID or Okta. Staff sign-in
 * is chosen per town, so the note names whichever provider /api/auth/status
 * reports, and stays provider-neutral until it knows.
 */

beforeEach(() => { getAuthStatus.mockReset(); });
afterEach(cleanup);

describe('SignInProviderNote', () => {
    it('names the configured provider, not Auth0', async () => {
        getAuthStatus.mockResolvedValue({
            auth0_configured: true, provider: 'entra', provider_name: 'Microsoft Entra ID',
        });
        render(<SignInProviderNote />);
        expect(await screen.findByText(
            'Staff sign in with Microsoft Entra ID using their work email. Pinpoint never stores a password.',
        )).toBeTruthy();
        expect(screen.getByText('Single sign-on with Microsoft Entra ID')).toBeTruthy();
        expect(screen.getByTestId('sign-in-provider-note').textContent).not.toContain('Auth0');
    });

    it('is provider-neutral while loading or when the status request fails', async () => {
        let fail: (e: Error) => void = () => { };
        getAuthStatus.mockImplementation(() => new Promise((_, reject) => { fail = reject; }));
        render(<SignInProviderNote />);
        const note = screen.getByTestId('sign-in-provider-note');
        // Loading: nothing known yet, so no vendor is named.
        expect(note.textContent).toContain('your town’s sign-in provider');
        await act(async () => { fail(new Error('offline')); });
        expect(note.textContent).toContain('your town’s sign-in provider');
        expect(note.textContent).not.toMatch(/Auth0|Entra|Okta/);
    });

    it('says sign-in is not set up when no provider is configured', async () => {
        getAuthStatus.mockResolvedValue({ auth0_configured: false, provider: null, provider_name: null });
        render(<SignInProviderNote />);
        expect(await screen.findByText(/Staff sign-in isn’t set up yet/)).toBeTruthy();
    });
});

describe('Admin Console staff-user copy', () => {
    it('no longer hardcodes Auth0 on the Users page or the Add User form', () => {
        expect(adminConsoleSource).not.toContain('Auth0 SSO');
        expect(adminConsoleSource).not.toMatch(/log in via Auth0/);
        expect(adminConsoleSource).toContain('<SignInProviderNote />');
    });
});
