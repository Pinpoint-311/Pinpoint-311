// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * The registration touchpoint on the setup tracker has two shapes, and this
 * pins the branch between them: an operator who set CONTACT_FORM_URL gets a
 * link out to their Microsoft Form, opened in a new tab and without a window
 * handle; a self-hoster who set nothing keeps the built-in contact form. The
 * second case is the one that must not regress quietly -- losing it means a
 * town without a form loses its only way to leave a contact.
 */

const state = vi.hoisted(() => ({ systemConfig: {} as Record<string, unknown> }));

vi.mock('../services/api', () => {
    /* Same proxy as the smoke test: every method resolves, list-shaped names
     * resolve to arrays, and only the calls this test branches on are named. */
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
    const listish = /^(list|get)[A-Za-z]*(s|List|Configs|Layers|Errors|Catalog)$/;
    const api: any = new Proxy({}, {
        get: (_t, prop: string) => prop === 'getSystemConfig'
            ? vi.fn().mockImplementation(async () => state.systemConfig)
            : vi.fn().mockResolvedValue(
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
};

async function mount() {
    const { default: Page } = await import('./SetupIntegrationsPage');
    const { DialogProvider } = await import('./DialogProvider');
    await act(async () => {
        root.render(React.createElement(DialogProvider, null, React.createElement(Page, props)));
    });
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

describe('the registration touchpoint on the setup tracker', () => {
    it('links out to a configured contact form, in a new tab, without a window handle', async () => {
        state.systemConfig = { contact_form_url: 'https://forms.office.com/r/example' };
        await mount();

        const link = host.querySelector<HTMLAnchorElement>('a[href="https://forms.office.com/r/example"]');
        expect(link).not.toBeNull();
        expect(link!.target).toBe('_blank');
        expect(link!.rel).toContain('noopener');
        expect(link!.textContent).toContain('Register your deployment');
        // The honesty note: the form is not ours and the page says so.
        expect(host.textContent).toContain('hosted by Microsoft Forms');
    });

    it('falls back to the built-in contact form when no URL is configured', async () => {
        state.systemConfig = { contact_form_url: '' };
        await mount();

        expect(host.textContent).toContain('Register a contact');
        expect(host.textContent).not.toContain('Microsoft Forms');
        expect(host.querySelector('a[href*="forms.office.com"]')).toBeNull();
    });
});
