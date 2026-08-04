// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Deselecting a feature has to leave a trace.
 *
 * Reported: "I deselected some and nothing popped up." Hiding the card is only
 * half an answer -- the other half is telling a town the capability exists and
 * where to switch it on, or "we cannot do that" becomes the standing
 * assumption for anything declined once during a five-minute questionnaire.
 */

vi.mock('../services/api', () => {
    const shapes: Record<string, unknown> = {
        getConnectorHealth: { connectors: [] },
        getCloudIdentity: null,
        getProviderCatalog: {
            capability: 'ai', current_provider: 'vertex',
            providers: [{ provider: 'vertex', name: 'Google Vertex AI', credential_fields: [] }],
            configured: { vertex: true },
        },
        getCloudProfile: {
            profile: 'google', managed: false, profiles: [],
            components: { identity: 'auth0' }, maps: { label: 'Google Maps' },
        },
    };
    const api: any = new Proxy({}, {
        get: (_t, prop: string) => vi.fn().mockResolvedValue(prop in shapes ? shapes[prop] : {}),
    });
    return { default: api, api };
});

let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

async function mount(show?: Set<string>, statusMap?: Record<string, unknown>) {
    const { default: ServiceProviders } = await import('./ServiceProviders');
    await act(async () => {
        root.render(React.createElement(ServiceProviders as any, { show, statusMap }));
    });
    return host.textContent || '';
}

describe('capabilities the town switched off', () => {
    it('lists them when a feature is deselected', async () => {
        // Everything except text messages and translation.
        const text = await mount(new Set(['ai', 'email', 'kms', 'redaction']));
        expect(text).toContain('Switched off');
        expect(text).toContain('Text Messages');
        expect(text).toContain('Translation');
    });

    it('points at where they are switched back on', async () => {
        const text = await mount(new Set(['ai']));
        expect(text).toMatch(/Setup Instructions/i);
    });

    it('says nothing when the town asked for everything', async () => {
        const text = await mount(new Set(['ai', 'translation', 'email', 'sms', 'kms', 'redaction']));
        expect(text).not.toContain('Switched off');
    });

    /* The requirement, in the reporter's words: "I can for example save an
     * email or AI key but not use it and then this is reflected in the service
     * provider card but things are still saved."
     *
     * Half of that was already true -- the card disappeared into this section.
     * The other half was not said anywhere, and the safe assumption from a
     * greyed-out tile is that whatever was entered has gone, which makes
     * switching something off feel like throwing work away. */
    it('says when a switched-off capability still has its credentials', async () => {
        const text = await mount(new Set(['ai']), {
            sms: { current_provider: 'twilio', configured: { twilio: true }, enabled: false },
        });

        expect(text).toContain('Switched off — credentials still saved');
        expect(text).toMatch(/Nothing was deleted/);
    });

    it('does not claim credentials for one that never had any', async () => {
        const text = await mount(new Set(['ai']), {
            sms: { current_provider: 'twilio', configured: { twilio: false }, enabled: false },
        });

        expect(text).toContain('Not switched on');
        expect(text).not.toMatch(/Nothing was deleted/);
    });

    it('does not claim credentials for a provider the town has since left', async () => {
        // `configured` is per provider for a reason: a town that set up Twilio
        // and then selected a gateway it has entered nothing for has no stored
        // credentials for the provider in use.
        const text = await mount(new Set(['ai']), {
            sms: { current_provider: 'http', configured: { twilio: true }, enabled: false },
        });

        expect(text).not.toMatch(/Nothing was deleted/);
    });

    it('never lists sign-in or maps, which cannot be switched off', async () => {
        const text = await mount(new Set([]));
        const off = text.slice(text.indexOf('Switched off'));
        expect(off).not.toContain('Staff Sign-In');
        expect(off).not.toContain('Maps Provider');
    });
});
