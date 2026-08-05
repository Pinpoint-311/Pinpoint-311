// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Two things the task list has to get right, both reported as bugs.
 *
 * "Everything you picked is set up" appeared when it was not true. It rendered
 * whenever nothing was open, and nothing is open after collapsing a row -- so
 * clicking the current task shut congratulated a town that had configured
 * nothing.
 *
 * And switching a provider left the task ticked. Done-ness was read per
 * capability, where "maps is set up" meant any map provider had a key, so a
 * town that configured Google Maps and switched to Esri kept a green tick
 * against a provider with no credentials.
 *
 * Both are about the list, not about credentials, so this renders the wizard
 * with its provider setup stubbed out.
 */

vi.mock('./InlineProviderSetup', () => ({
    default: ({ cap, provider, onSaved }: { cap: string; provider: string; onSaved?: (v: boolean) => void }) =>
        React.createElement('div', { 'data-setup': `${cap}:${provider}` },
            React.createElement('button', {
                'data-pass': `${cap}`, onClick: () => onSaved?.(true),
            }, 'pass'),
            React.createElement('button', {
                'data-fail': `${cap}`, onClick: () => onSaved?.(false),
            }, 'fail')),
}));

let SetupWizard: typeof import('./SetupWizard').default;
let container: HTMLDivElement;
let root: Root;

const BASE = {
    cloud: 'azure' as const,
    idp: 'entra' as const,
    maps: 'google' as string,
    aiProvider: 'azure',
    emailProvider: 'acs',
    smsProvider: 'acs',
    redactionProvider: 'azure',
    wanted: new Set<string>(),
    isDone: () => false,
    secretValues: {},
    onSecretChange: () => {},
    onSaveSecrets: async () => {},
    savingSecret: null,
    isSecretConfigured: () => false,
    onRefresh: () => {},
    publicOrigin: 'https://311.example.gov',
    renderFoundation: () => null,
};

/** Everything configured, for whichever providers are named. */
const statusFor = (pairs: Record<string, string[]>) =>
    Object.fromEntries(Object.entries(pairs).map(([cap, provs]) => [
        cap, { current_provider: provs[0] ?? null, configured: Object.fromEntries(provs.map(p => [p, true])) },
    ]));

async function render(props: Partial<typeof BASE> & { status: any }) {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => { root.render(React.createElement(SetupWizard as any, { ...BASE, ...props })); });
    await act(async () => { await Promise.resolve(); });
}

const text = () => container.textContent || '';
const rows = () => Array.from(container.querySelectorAll<HTMLButtonElement>('nav button'));

beforeEach(async () => {
    vi.resetModules();
    await import('./setupStepsContent');
    SetupWizard = (await import('./SetupWizard')).default;
});

afterEach(async () => {
    await act(async () => { root?.unmount(); });
    container?.remove();
});

describe('the completion message means completion', () => {
    it('does not claim everything is set up when nothing is', async () => {
        await render({ status: {} });
        expect(text()).not.toContain('Everything you picked is set up');
    });

    it('still does not claim it after the open task is collapsed', async () => {
        /* The reported bug. Collapsing a row leaves nothing open, and the done
         * panel was shown for "nothing open" rather than for "nothing left". */
        await render({ status: {} });
        // The first unfinished task opens itself.
        expect(rows()[0].getAttribute('aria-current')).toBe('step');

        await act(async () => { rows()[0].click(); });

        // Collapsed: nothing is the current step any more.
        expect(rows().every(r => r.getAttribute('aria-current') === null)).toBe(true);
        // ...and that state is not congratulation. This is the reported bug.
        expect(text()).not.toContain('Everything you picked is set up');
        expect(text()).toContain('2 left');

        /* Not asserting that the idle panel has appeared. AnimatePresence runs
         * `mode="wait"`, so the outgoing panel is held in the DOM until its exit
         * animation finishes -- which it does in a browser and never does under
         * jsdom, where no frames are produced. What matters here is what the
         * page claims, and it no longer claims to be finished. */
    });

    it('says it only when every task really is done', async () => {
        await render({
            status: statusFor({ identity: ['entra'], maps: ['google'] }),
        });
        expect(text()).toContain('Everything you picked is set up');
    });
});

describe('switching a provider', () => {
    it('marks the task unfinished when the new provider has no credentials', async () => {
        // Google Maps is set up; Esri is not. Same capability.
        const status = statusFor({ identity: ['entra'], maps: ['google'] });
        await render({ status });
        expect(text()).toContain('Everything you picked is set up');

        await act(async () => {
            root.render(React.createElement(SetupWizard as any, { ...BASE, status, maps: 'esri' }));
        });
        await act(async () => { await Promise.resolve(); });

        // No longer finished, and no longer claiming to be.
        expect(text()).not.toContain('Everything you picked is set up');
        expect(text()).toContain('1 left');
    });

    it('opens the task whose provider changed', async () => {
        const status = statusFor({ identity: ['entra'], maps: ['google'] });
        await render({ status });

        await act(async () => {
            root.render(React.createElement(SetupWizard as any, { ...BASE, status, maps: 'esri' }));
        });
        await act(async () => { await Promise.resolve(); });

        // Esri is its own login, so it becomes its own task -- and it is the
        // one now open, showing the boxes for the provider just chosen.
        expect(container.querySelector('[data-setup="maps:esri"]')).toBeTruthy();
    });
});

describe('the task list', () => {
    it('counts what is left rather than what exists', async () => {
        await render({ status: statusFor({ identity: ['entra'] }) });
        expect(text()).toContain('1 left');   // maps still outstanding
    });

    it('does not tick a capability just because some other provider is set up', async () => {
        /* The heart of the bug: `configured` keyed by provider, not capability.
         * Google Maps configured while the town is on Esri must not read as
         * done. */
        const status = {
            identity: { current_provider: 'entra', configured: { entra: true } },
            maps: { current_provider: 'google', configured: { google: true, esri: false } },
        };
        await render({ status, maps: 'esri' });
        expect(text()).not.toContain('Everything you picked is set up');
    });
});


describe('one item open at a time', () => {
    /* Grouping by login turned four visits into one and then put all four on
     * the screen at once: the Azure task rendered about six thousand pixels
     * tall while the rail said "1 left". Items collapse for the same reason
     * tasks do. */
    const AZURE_WORK = { wanted: new Set(['ai', 'translation', 'kms']) };

    const itemHeaders = () =>
        Array.from(container.querySelectorAll<HTMLButtonElement>('section button[aria-expanded]'));
    const expandedItems = () => itemHeaders().filter(b => b.getAttribute('aria-expanded') === 'true');
    const openSetup = () => container.querySelector('[data-setup]')?.getAttribute('data-setup');

    it('shows every item but expands only one', async () => {
        await render({ ...AZURE_WORK, status: {} });
        // Sign-in, AI, translation and key management are all one Azure trip.
        expect(itemHeaders().length).toBe(4);
        expect(expandedItems().length).toBe(1);
    });

    it('opens the first unfinished item — key management leads', async () => {
        // Kms sits first inside the task: the key service and the secret
        // store have to be reachable before the credentials they protect.
        await render({ ...AZURE_WORK, status: {} });
        expect(openSetup()).toBe('kms:azure');
    });

    it('skips past items already set up', async () => {
        await render({
            ...AZURE_WORK,
            status: statusFor({ identity: ['entra'], ai: ['azure'], maps: ['google'], kms: ['azure'] }),
        });
        expect(openSetup()).toBe('translation:azure');
    });

    it('opens the next item when one is finished and verified', async () => {
        await render({ ...AZURE_WORK, status: {} });
        expect(openSetup()).toBe('kms:azure');

        await act(async () => {
            container.querySelector<HTMLButtonElement>('[data-pass="kms"]')!.click();
        });
        expect(openSetup()).toBe('identity:entra');
    });

    it('does not move on when the test failed', async () => {
        /* The whole point of advancing on the test rather than the save.
         * Moving somebody past a credential that does not work reads as
         * confirmation that it does. */
        await render({ ...AZURE_WORK, status: {} });
        await act(async () => {
            container.querySelector<HTMLButtonElement>('[data-fail="kms"]')!.click();
        });
        expect(openSetup()).toBe('kms:azure');
    });

    it('collapses and expands on click', async () => {
        await render({ ...AZURE_WORK, status: {} });
        const [first, second] = itemHeaders();

        await act(async () => { second.click(); });
        expect(openSetup()).toBe('identity:entra');

        await act(async () => { itemHeaders()[1].click(); });   // same one again
        expect(expandedItems().length).toBe(0);

        await act(async () => { itemHeaders()[0].click(); });
        expect(openSetup()).toBe('kms:azure');
        expect(first).toBeTruthy();
    });

    it('leaves the task once its last item passes', async () => {
        // Only sign-in is outstanding in the Azure task; maps is a separate one.
        await render({
            ...AZURE_WORK,
            status: statusFor({ ai: ['azure'], translation: ['azure'], kms: ['azure'] }),
        });
        expect(openSetup()).toBe('identity:entra');

        await act(async () => {
            container.querySelector<HTMLButtonElement>('[data-pass="identity"]')!.click();
        });

        /* Asserted on the rail, not the panel. Crossing to another task swaps
         * the panel through AnimatePresence `mode="wait"`, which holds the
         * outgoing one until its exit animation finishes -- and jsdom produces
         * no frames, so it never does. The rail is outside that animation and
         * says which task is current. */
        const current = rows().find(r => r.getAttribute('aria-current') === 'step');
        expect(current?.textContent).toContain('Google Cloud');
    });
});
