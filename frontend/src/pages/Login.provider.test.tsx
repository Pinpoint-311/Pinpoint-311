// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * The sign-in page names the identity provider it will hand you to.
 *
 * It used to say "Secured by Auth0 SSO with MFA" as a literal, so a town that
 * had moved to Microsoft Entra ID was still told Auth0 -- on the one screen
 * where being handed to an unexpected sign-in host is the thing a careful
 * person is watching for. The backend now reports the provider actually
 * configured, and this badge follows it.
 */

vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { township_name: 'Testville' }, isLoading: false, refreshSettings: () => { } }),
}));

vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({ setToken: () => { }, isAuthenticated: false, user: null }),
}));

import Login from './Login';

function mockStatus(body: Record<string, unknown>) {
    vi.stubGlobal('fetch', vi.fn(async () => ({
        ok: true,
        json: async () => body,
    })) as unknown as typeof fetch);
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('the provider badge on the sign-in page', () => {
    it('names Entra when the deployment is on Entra', async () => {
        mockStatus({ auth0_configured: true, provider: 'entra', provider_name: 'Microsoft Entra ID', message: 'Ready' });

        render(<MemoryRouter><Login /></MemoryRouter>);

        await waitFor(() => {
            expect(screen.getByText(/Microsoft Entra ID/)).toBeTruthy();
        });
        expect(screen.queryByText(/Auth0/)).toBeNull();
    });

    it('still names Auth0 when the deployment is on Auth0', async () => {
        mockStatus({ auth0_configured: true, provider: 'auth0', provider_name: 'Auth0', message: 'Ready' });

        render(<MemoryRouter><Login /></MemoryRouter>);

        await waitFor(() => {
            expect(screen.getByText(/Auth0/)).toBeTruthy();
        });
    });

    it('claims no particular provider when the backend names none', async () => {
        /* An older backend, or a status call that failed. Better to say "SSO"
         * than to assert a provider this deployment may not be using. */
        mockStatus({ auth0_configured: true, provider: null, provider_name: null });

        render(<MemoryRouter><Login /></MemoryRouter>);

        await waitFor(() => {
            expect(screen.getByText(/Secured by/)).toBeTruthy();
        });
        expect(screen.queryByText(/Auth0/)).toBeNull();
        expect(screen.queryByText(/Entra/)).toBeNull();
    });
});
