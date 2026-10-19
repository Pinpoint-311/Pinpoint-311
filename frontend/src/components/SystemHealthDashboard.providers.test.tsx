// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

const catalogs: Record<string, { current_provider: string; providers: { provider: string; name: string }[] }> = {
    identity: { current_provider: 'okta', providers: [{ provider: 'auth0', name: 'Auth0' }, { provider: 'okta', name: 'Okta' }] },
    ai: { current_provider: 'bedrock', providers: [{ provider: 'vertex', name: 'Google Vertex AI' }, { provider: 'bedrock', name: 'Amazon Bedrock' }] },
    translation: { current_provider: 'azure', providers: [{ provider: 'azure', name: 'Azure Translator' }] },
};
vi.mock('../services/api', () => ({
    api: { getProviderCatalog: (cap: string) => Promise.resolve(catalogs[cap]) },
}));

import SystemHealthDashboard from './SystemHealthDashboard';

/* The health cards were headed "Auth0 SSO" and "Vertex AI / AI Analysis
 * (Gemini)" whatever the town had chosen. They are now headed by the
 * capability, with the town's provider (by its catalog name) beneath. */

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const check = (status = 'configured') => ({ status, message: 'ok' });

describe('SystemHealthDashboard provider names', () => {
    it('shows the configured providers and never a fixed vendor heading', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
            overall_status: 'healthy',
            timestamp: new Date().toISOString(),
            checks: {
                database: check('healthy'), auth0: check(), gcp_auth: check('not_configured'),
                kms: check(), secret_store: check(), vertex_ai: check(), translation_api: check(),
            },
        }), { status: 200 })));
        render(<SystemHealthDashboard />);

        expect(await screen.findByText('Okta')).toBeTruthy();
        expect(await screen.findByText('Amazon Bedrock')).toBeTruthy();
        expect(await screen.findByText(/Azure Translator/)).toBeTruthy();
        expect(screen.getByText('Staff Sign-In')).toBeTruthy();
        expect(screen.getByText('AI Analysis')).toBeTruthy();
        expect(screen.queryByText('Auth0 SSO')).toBeNull();
        expect(screen.queryByText('Vertex AI')).toBeNull();
        expect(screen.queryByText(/Gemini/)).toBeNull();
        // A town with no Google service account is not shown a Google card.
        expect(screen.queryByText('Google Cloud Credentials')).toBeNull();
    });
});
