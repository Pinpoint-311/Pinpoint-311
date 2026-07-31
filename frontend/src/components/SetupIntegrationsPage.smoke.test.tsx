// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Does the page still mount?
 *
 * Not a behaviour test. This exists because the "Other settings" block was
 * edited by index -- a Google Cloud card removed, two hand-written credential
 * forms replaced with the shared component, a save button deleted -- and both
 * a clean typecheck and a clean build pass on JSX that throws the moment it
 * renders. The last time something similar happened, a component declared
 * during render remounted on every keystroke and discarded typed credentials,
 * and nothing in CI noticed.
 */

vi.mock('../services/api', () => {
    /* Every method resolves. A hand-listed mock would make this test about
     * whether I guessed the page's API surface correctly, which is not the
     * question -- the question is whether the JSX renders. Named responses
     * below are only for the calls whose *shape* the render depends on. */
    const shapes: Record<string, unknown> = {
        getConfig: { public_origin: 'https://town.gov' },
        getProviderStatus: {},
        getConnectorHealth: { connectors: [] },
        getCloudIdentity: null,
        getStorageStatus: { secrets: { store: 'google', count: 0, reachable: true }, pii: {} },
        getProviderCatalog: {
            capability: 'ai', current_provider: 'vertex', providers: [], configured: {},
        },
        getCloudProfile: {
            profile: 'google', managed: false, profiles: [],
            components: { identity: 'auth0' }, maps: { label: 'Google Maps' },
        },
    };
    /* Anything list-shaped defaults to an array rather than an object: a
     * component doing `(x || []).filter(...)` on `{}` throws, and that would
     * be the mock failing rather than the page. */
    const listish = /^(list|get)[A-Za-z]*(s|List|Configs|Layers|Errors|Catalog)$/;
    const api: any = new Proxy({}, {
        get: (_t, prop: string) => vi.fn().mockResolvedValue(
            prop in shapes ? shapes[prop] : listish.test(prop) ? [] : {},
        ),
    });
    return { default: api, api };
});

let host: HTMLDivElement;
let root: Root;

const props: any = {
    secrets: [],
    onSaveSecret: vi.fn().mockResolvedValue(undefined),
    onRefresh: vi.fn(),
    modules: { ai_analysis: false },
    onUpdateModules: vi.fn().mockResolvedValue(undefined),
};

async function mount() {
    const { default: Page } = await import('./SetupIntegrationsPage');
    await act(async () => { root.render(React.createElement(Page, props)); });
    return host.textContent || '';
}

beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
});
afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.clearAllMocks();
});

describe('the setup page after the Other-settings surgery', () => {
    it('mounts without throwing', async () => {
        const text = await mount();
        expect(text).toContain('Setup Instructions');
    });

    it('still offers crash reporting and backups', async () => {
        // Both were rewritten to render shared field definitions. If either
        // vanished during the edit, this is where it shows up.
        const text = await mount();
        expect(text).toContain('Crash reporting');
        expect(text).toMatch(/Database Backups/i);
    });

    it('no longer carries a Google Cloud card in Other settings', async () => {
        // Its fields moved into the guide, under the steps that produce them.
        const text = await mount();
        expect(text).not.toContain('GCP Project ID');
    });

    it('asks for the backup bucket by the shared label', async () => {
        // Proves the shared array is what rendered, not a surviving hand-written
        // copy that happens to look similar.
        const text = await mount();
        expect(text).toContain('Bucket name');
    });
});
