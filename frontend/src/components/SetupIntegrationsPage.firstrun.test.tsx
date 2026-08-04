// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * A fresh install has to be shown the guide, and a finished town has to be left
 * alone.
 *
 * Nothing detected a fresh install. The guide opened itself on
 * `!signInConfigured || !mapsConfigured`, which is "is everything set up"
 * wearing a disguise -- and that never goes true for a town that deliberately
 * switches most things off, so the guide would greet it on every login forever.
 * A banner that never goes away is one people stop reading.
 *
 * Being finished is a thing a person says, and this is where they say it.
 */

let setupState: { completed: boolean; completed_at: string | null } = {
    completed: false, completed_at: null,
};
const marked: string[] = [];
let refuseMark: string | null = null;

/* framer-motion, reduced to plain elements.
 *
 * The setup guide's body lives inside an `AnimatePresence`, and in jsdom no
 * animation ever completes -- so the subtree it is holding stops reflecting
 * state and every assertion after a click reads a frozen snapshot. That is an
 * artifact of the animation library in a headless DOM, not behaviour worth
 * testing, and leaving it in place makes these tests pass for the wrong reason:
 * a chip that never changes looks exactly like a chip that correctly rolled
 * back. */
vi.mock('framer-motion', async () => {
    const React = await import('react');
    const passthrough = (tag: string) => ({ children, ...props }: any) => {
        const {
            initial, animate, exit, transition, variants, whileHover, whileTap,
            whileInView, layout, layoutId, drag, onAnimationComplete, ...rest
        } = props;
        return React.createElement(tag, rest, children);
    };
    /* Cached per tag. A Proxy that builds a fresh component on every access
     * hands React a new element *type* on every render, which remounts the
     * subtree every time -- an infinite loop, not a passthrough. */
    const cache = new Map<string, any>();
    const motion: any = new Proxy({}, {
        get: (_t, tag: string) => {
            if (!cache.has(tag)) cache.set(tag, passthrough(tag));
            return cache.get(tag);
        },
    });
    return {
        motion,
        AnimatePresence: ({ children }: any) => React.createElement(React.Fragment, null, children),
        useReducedMotion: () => true,
    };
});

vi.mock('../services/api', () => {
    const shapes: Record<string, unknown> = {
        getConfig: { public_origin: 'https://town.gov' },
        getProviderStatus: {},
        getConnectorHealth: { connectors: [] },
        getCloudIdentity: null,
        getSecretStore: { chosen: true, store: 'database', options: [], reachable: false },
        getStorageStatus: { secrets: { store: 'database', count: 0, reachable: false }, pii: {} },
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
        get: (_t, prop: string) => {
            if (prop === 'getSetupState') return vi.fn(async () => setupState);
            if (prop === 'markSetupComplete') {
                return vi.fn(async () => {
                    if (refuseMark) throw new Error(refuseMark);
                    marked.push('done');
                    setupState = { completed: true, completed_at: '2026-08-04T00:00:00Z' };
                    return setupState;
                });
            }
            return vi.fn().mockResolvedValue(
                prop in shapes ? shapes[prop] : listish.test(prop) ? [] : {},
            );
        },
    });
    return { default: api, api };
});

let host: HTMLDivElement;
let root: Root;

const props: any = {
    // Non-empty, because the old trigger waited on it and a regression to that
    // shape should not be masked by the prop being empty.
    secrets: [{ id: 1, key_name: 'AUTH0_DOMAIN', is_configured: true }],
    onSaveSecret: vi.fn().mockResolvedValue(undefined),
    onRefresh: vi.fn(),
};

async function mount() {
    const { default: Page } = await import('./SetupIntegrationsPage');
    await act(async () => { root.render(React.createElement(Page, props)); });
    return host.textContent || '';
}

/** The guide's body is only in the DOM when it is open. */
function guideIsOpen() {
    return /Answer a few questions and we will hide the rest/.test(host.textContent || '');
}

function button(pattern: RegExp): HTMLElement | undefined {
    return Array.from(host.querySelectorAll('button'))
        .find(b => pattern.test(b.textContent || '')) as HTMLElement | undefined;
}

beforeEach(() => {
    setupState = { completed: false, completed_at: null };
    marked.length = 0;
    refuseMark = null;
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
});
afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.clearAllMocks();
});

describe('the first-run guide', () => {
    it('opens itself when nobody has said setup is finished', async () => {
        await mount();
        expect(guideIsOpen()).toBe(true);
    });

    it('stays shut once somebody has', async () => {
        setupState = { completed: true, completed_at: '2026-01-01T00:00:00Z' };
        await mount();
        expect(guideIsOpen()).toBe(false);
    });

    it('stays shut even with everything still unconfigured', async () => {
        // The old trigger, and the case it got wrong. `getProviderStatus`
        // answers `{}` here, so nothing on this page is set up -- a town that
        // switched most things off deliberately looks exactly like this, and
        // was greeted by the guide on every login forever.
        setupState = { completed: true, completed_at: '2026-01-01T00:00:00Z' };
        const text = await mount();

        expect(text).toMatch(/still to set up|still need credentials/i);
        expect(guideIsOpen()).toBe(false);
    });

    it('offers a way to say so, and stops opening after it is used', async () => {
        await mount();
        expect(guideIsOpen()).toBe(true);

        const finish = button(/done with setup/i);
        expect(finish).toBeTruthy();
        await act(async () => { finish!.click(); });

        expect(marked).toEqual(['done']);

        /* The promise is about the *next* sign-in, so check the next one.
         *
         * Not the DOM in this session: the panel is inside an AnimatePresence,
         * which holds the outgoing children until an exit animation that jsdom
         * never runs. Asserting on them would be asserting on the animation
         * library. The flag is the thing that has to survive. */
        await act(async () => { root.unmount(); });
        root = createRoot(host);
        await mount();
        expect(guideIsOpen()).toBe(false);
        expect(button(/done with setup/i)).toBeUndefined();
    });

    it('does not offer it to a town that has already finished', async () => {
        setupState = { completed: true, completed_at: '2026-01-01T00:00:00Z' };
        await mount();
        // Reopen by hand -- the tab is still here and the panel still opens.
        const header = Array.from(host.querySelectorAll('button'))
            .find(b => /Setup Instructions/.test(b.textContent || '')) as HTMLElement;
        await act(async () => { header.click(); });

        expect(guideIsOpen()).toBe(true);
        expect(button(/done with setup/i)).toBeUndefined();
    });

    it('does not gate finishing on the checklist being green', async () => {
        // Two things are actually required and the panel says which. A guide
        // that will not let go until a count reaches zero is the thing standing
        // between somebody and their console.
        await mount();
        expect((button(/done with setup/i) as HTMLButtonElement).disabled).toBe(false);
    });

    it('stays shut when the server cannot be asked', async () => {
        // Unknown is not "unfinished". A failed request must not throw the
        // guide open over the top of a console somebody is trying to use.
        setupState = null as any;
        await mount();
        expect(guideIsOpen()).toBe(false);
    });

    it('says what closing it actually does', async () => {
        // It is not "hide this forever": the tab is still there and the panel
        // still opens. All the flag settles is what happens on sign-in, and a
        // button that reads like a permanent dismissal does not get pressed.
        await mount();
        expect(host.textContent).toMatch(/come back to it from this tab/i);
    });
});
