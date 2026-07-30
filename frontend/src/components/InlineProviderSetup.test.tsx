// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Tells React this is an act() environment, so state updates outside act are
// reported as the test bug they are rather than silently tolerated.
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/* Re-imported per test rather than imported once at the top.
 *
 * The component memoises the attached-identity probe at module scope -- eight
 * of these mount at once in the guide and the answer is a property of the
 * server, so asking eight times is eight round trips to learn the same thing.
 * That cache is right in a browser and sticky in a test file: whatever the
 * first test resolves is what every later test sees. Resetting the module
 * registry gives each test its own cache instead of loosening the cache to suit
 * the tests. */
let InlineProviderSetup: typeof import('./InlineProviderSetup').default;

/**
 * The guide's credential boxes are really there, and they really save.
 *
 * Everything else asserting this reads the TSX as text, which proves the
 * component is mounted and nothing about what it puts on the screen. That gap
 * is exactly where the original failure lived: the page looked configured,
 * every string was present, and the thing a clerk needed to type into was
 * somewhere else entirely.
 *
 * So this renders it. A stubbed catalog goes in, and the assertions are on the
 * DOM that comes out -- the walk from setupStepsContent, an input per credential
 * the catalog declares, and a save that posts what was typed.
 */

const AUTH0 = {
    current_provider: 'auth0',
    configured: {},
    providers: [{
        provider: 'auth0',
        name: 'Auth0',
        credential_fields: [
            { key: 'AUTH0_DOMAIN', label: 'Auth0 Domain', secret: false },
            { key: 'AUTH0_CLIENT_ID', label: 'Client ID', secret: false },
            { key: 'AUTH0_CLIENT_SECRET', label: 'Client Secret', secret: true },
        ],
    }],
};

let container: HTMLDivElement;
let root: Root;

const getCloudIdentity = vi.fn();
const getProviderCatalog = vi.fn();
const saveProvider = vi.fn();
const testProvider = vi.fn();

vi.mock('../services/api', () => ({
    api: {
        getProviderCatalog: (...a: unknown[]) => getProviderCatalog(...a),
        getCloudIdentity: (...a: unknown[]) => getCloudIdentity(...a),
        saveProvider: (...a: unknown[]) => saveProvider(...a),
        testProvider: (...a: unknown[]) => testProvider(...a),
    },
}));

async function mount(ui: React.ReactElement) {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => { root.render(ui); });
    // Let the catalog and identity promises settle.
    await act(async () => { await Promise.resolve(); });
}

beforeEach(async () => {
    vi.clearAllMocks();
    vi.resetModules();
    // Order matters. SETUP_STEPS is a module-scoped registry that
    // setupStepsContent fills as an import side effect, so after a reset the
    // content has to be re-imported before anything reads the registry --
    // otherwise the walk is empty and every provider falls back to a bare list
    // of boxes, which is precisely the regression these tests exist to catch.
    await import('./setupStepsContent');
    InlineProviderSetup = (await import('./InlineProviderSetup')).default;
    getProviderCatalog.mockResolvedValue(AUTH0);
    getCloudIdentity.mockResolvedValue({ attached: false, provider: null, identity: null, skippable_keys: [] });
    saveProvider.mockResolvedValue({ ok: true, provider: 'auth0', warnings: [] });
    testProvider.mockResolvedValue({ ok: true, detail: 'Signed a test token.' });
});

afterEach(async () => {
    await act(async () => { root?.unmount(); });
    container?.remove();
});

const inputs = () => Array.from(container.querySelectorAll('input'));
const labels = () => Array.from(container.querySelectorAll('label')).map(l => l.textContent || '');

describe('the guide sets a provider up where it describes it', () => {
    it('renders one input per credential the catalog declares', async () => {
        await mount(<InlineProviderSetup cap="identity" provider="auth0" />);

        // Three credentials in, three boxes out. The failure this guards is a
        // step naming a key the catalog does not have, which renders nothing
        // and looks identical to a step that needs no input.
        expect(inputs()).toHaveLength(3);
        const text = labels().join(' | ');
        expect(text).toContain('Auth0 Domain');
        expect(text).toContain('Client ID');
        expect(text).toContain('Client Secret');
    });

    it('renders the console walk, not just the boxes', async () => {
        await mount(<InlineProviderSetup cap="identity" provider="auth0" />);
        // The numbered steps come from setupStepsContent. Boxes without them is
        // the state this whole change exists to move away from.
        const numbered = container.querySelectorAll('span.rounded-full');
        expect(numbered.length).toBeGreaterThan(0);
        expect(container.textContent).toMatch(/auth0\.com|Applications|Application/i);
    });

    it('still renders a credential no step claims', async () => {
        /* The documented guarantee: adding a key to a catalog can never make it
         * silently unreachable, even before anybody writes the step that
         * explains it. Without this, a new credential appears in the backend,
         * the save endpoint expects it, and the only place to enter it does not
         * exist -- which reads to a clerk as a provider that simply refuses to
         * work.
         *
         * Auth0's three fields are all claimed by steps, so a fourth is added
         * here that none of them mentions. */
        getProviderCatalog.mockResolvedValue({
            ...AUTH0,
            providers: [{
                ...AUTH0.providers[0],
                credential_fields: [
                    ...AUTH0.providers[0].credential_fields,
                    { key: 'AUTH0_ORGANIZATION', label: 'Organization ID', secret: false },
                ],
            }],
        });
        await mount(<InlineProviderSetup cap="identity" provider="auth0" />);

        expect(inputs()).toHaveLength(4);
        expect(labels().join(' | ')).toContain('Organization ID');
    });

    it('marks a secret field as a password so it is not shoulder-read', async () => {
        await mount(<InlineProviderSetup cap="identity" provider="auth0" />);
        const secret = inputs().find(i => i.type === 'password');
        expect(secret).toBeTruthy();
    });

    it('posts what was typed, then verifies it', async () => {
        await mount(<InlineProviderSetup cap="identity" provider="auth0" />);

        const domain = inputs()[0];
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
        await act(async () => {
            setter.call(domain, '  town.us.auth0.com  ');
            domain.dispatchEvent(new Event('input', { bubbles: true }));
        });

        const save = Array.from(container.querySelectorAll('button'))
            .find(b => (b.textContent || '').includes('Save'))!;
        await act(async () => { save.click(); });
        await act(async () => { await Promise.resolve(); });

        expect(saveProvider).toHaveBeenCalledTimes(1);
        const [cap, body] = saveProvider.mock.calls[0] as [string, any];
        expect(cap).toBe('identity');
        expect(body.provider).toBe('auth0');
        // Trimmed: a stray space from a copy-paste is the commonest reason a
        // correct credential is rejected.
        expect(body.settings.AUTH0_DOMAIN).toBe('town.us.auth0.com');
        // Untouched boxes are not sent, so saving one field cannot blank another.
        expect(body.settings.AUTH0_CLIENT_SECRET).toBeUndefined();

        // A save that is not verified is the silent failure this page exists to
        // avoid, so the test call is part of saving rather than a second button.
        expect(testProvider).toHaveBeenCalledWith('identity');
        expect(container.textContent).toContain('Signed a test token.');
    });

    it('reports a failed verification instead of claiming success', async () => {
        testProvider.mockResolvedValue({ ok: false, detail: 'Auth0 rejected the client secret.' });
        await mount(<InlineProviderSetup cap="identity" provider="auth0" />);

        const save = Array.from(container.querySelectorAll('button'))
            .find(b => (b.textContent || '').includes('Save'))!;
        await act(async () => { save.click(); });
        await act(async () => { await Promise.resolve(); });

        expect(container.textContent).toContain('Auth0 rejected the client secret.');
    });

    it('says there is nothing to type when the server has an attached identity', async () => {
        getCloudIdentity.mockResolvedValue({
            attached: true, provider: 'google', identity: 'pinpoint@town.iam.gserviceaccount.com',
            skippable_keys: ['AUTH0_CLIENT_SECRET'],
        });
        await mount(<InlineProviderSetup cap="identity" provider="auth0" />);

        expect(container.textContent).toContain('nothing to enter');
        // The box is replaced, not merely annotated -- leaving it would invite
        // someone to paste a long-lived key that the platform already replaces.
        expect(inputs()).toHaveLength(2);
    });

    it('does not offer a provider this deployment has no catalog entry for', async () => {
        await mount(<InlineProviderSetup cap="identity" provider="okta" />);
        expect(inputs()).toHaveLength(0);
        expect(container.textContent).toContain('does not offer that option');
    });

    it('falls back to the card rather than rendering an empty section', async () => {
        getProviderCatalog.mockRejectedValue(new Error('offline'));
        await mount(<InlineProviderSetup cap="identity" provider="auth0" />);
        expect(container.textContent).toContain('card further down the page');
    });
});
