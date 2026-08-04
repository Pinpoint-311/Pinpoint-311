// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Unticking a feature has to leave the browser.
 *
 * It did not. The questionnaire held its answer in
 * `useState<Set<string>>(new Set(ALL_FEATURES))`, read by nothing outside the
 * render and written to nothing at all -- so unticking a feature hid a section
 * of the setup guide, survived until the next reload, and switched nothing off.
 * The label above the chips read "untick to remove it".
 *
 * The consequence is not cosmetic. A town could save an AI or email credential
 * and then decide not to use it, and had no way to say so: the only thing that
 * stopped a configured capability was deleting the key it had just been asked
 * to paste in.
 */

const calls: { switches: Record<string, boolean> }[] = [];
let statusResponse: Record<string, unknown> = {};
/* The mock is a Proxy whose `get` builds a fresh fn per access, so a test
 * cannot swap one method out by assigning to it. Refusal is a flag the mocked
 * method reads instead. */
let refuseWith: string | null = null;

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
        get: (_t, prop: string) => {
            if (prop === 'getProviderStatus') return vi.fn(async () => statusResponse);
            if (prop === 'setCapabilitySwitches') {
                return vi.fn(async (switches: Record<string, boolean>) => {
                    if (refuseWith) throw new Error(refuseWith);
                    calls.push({ switches });
                    return { switches };
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
    secrets: [],
    onSaveSecret: vi.fn().mockResolvedValue(undefined),
    onRefresh: vi.fn(),
};

async function mount() {
    const { default: Page } = await import('./SetupIntegrationsPage');
    await act(async () => { root.render(React.createElement(Page, props)); });
    await settle(2);
    /* The chips live inside the guide. It opens itself on a town that has not
     * said setup is finished -- which this one has not, because `getSetupState`
     * is unmocked here -- so clicking unconditionally would close it. */
    if (!/What do you want to switch on/.test(host.textContent || '')) {
        await click('Setup Instructions');
    }
}

function findByText(pattern: RegExp): HTMLElement | undefined {
    return Array.from(host.querySelectorAll('button, h3'))
        .find(el => pattern.test(el.textContent || '')) as HTMLElement | undefined;
}

async function click(text: string | RegExp) {
    const el = findByText(typeof text === 'string' ? new RegExp(`^\\s*(✓ )?${text}\\s*$`) : text);
    if (!el) throw new Error(`no clickable element matching ${text}`);
    await act(async () => { el.click(); });
    await settle();
}

/* The click handler is async and act does not await it, so the state update on
 * the far side of the round trip lands after act returns -- and React may
 * schedule the render itself a task later again. One tick is not reliably
 * enough: the refusal case passed alone and failed in a full run, which is the
 * worst kind of green. */
async function settle(ticks = 3) {
    for (let i = 0; i < ticks; i++) {
        await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    }
}

/** Wait for the DOM to say something, rather than guessing how many ticks. */
async function waitForText(pattern: RegExp, tries = 20) {
    for (let i = 0; i < tries; i++) {
        if (pattern.test(host.textContent || '')) return;
        await settle(1);
    }
    throw new Error(`never rendered ${pattern}. Text was: ${(host.textContent || '').slice(0, 400)}`);
}

beforeEach(() => {
    calls.length = 0;
    statusResponse = {};
    refuseWith = null;
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
});
afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.clearAllMocks();
});

describe('the feature ticks', () => {
    it('sends the change to the server', async () => {
        await mount();
        await click('AI triage');

        expect(calls).toEqual([{ switches: { ai: false } }]);
    });

    it('sends the capability id, not the question a clerk was asked', async () => {
        // "Screening and blurring" is the chip; `redaction` is the thing that
        // gets switched off. The two vocabularies meet in exactly one place.
        await mount();
        await click('Screening and blurring');

        expect(calls).toEqual([{ switches: { redaction: false } }]);
    });

    it('carries backups and crash reporting under their own ids', async () => {
        // They are switchable and have no provider catalog, so they were held
        // in the browser and nowhere else -- which is the pair somebody is most
        // likely to untick and then wonder where it went.
        await mount();
        await click('Backups');

        expect(calls).toEqual([{ switches: { backups: false } }]);
    });

    it('sends only what changed', async () => {
        // A town that has never been asked about photo redaction must not
        // acquire an answer to it because somebody unticked backups.
        await mount();
        await click('Backups');

        expect(Object.keys(calls[0].switches)).toEqual(['backups']);
    });

    it('starts from what the server says, not from everything ticked', async () => {
        // The reload half. Before this the initial value *was* the answer, so a
        // town that had switched AI off saw it ticked again on every load.
        statusResponse = { ai: { enabled: false }, email: { enabled: true } };
        await mount();

        const ai = findByText(/^\s*(✓ )?AI triage\s*$/);
        const email = findByText(/^\s*(✓ )?Email\s*$/);
        expect(ai?.getAttribute('aria-pressed')).toBe('false');
        expect(email?.getAttribute('aria-pressed')).toBe('true');
    });

    it('treats a capability the server said nothing about as on', async () => {
        // An absent answer must not read as "the town switched this off".
        statusResponse = { ai: {} };
        await mount();

        expect(findByText(/^\s*(✓ )?AI triage\s*$/)?.getAttribute('aria-pressed')).toBe('true');
    });

    it('puts the chip back when the write is refused', async () => {
        // A tick that stays ticked while the server has no record of it is the
        // original bug wearing a round trip.
        await mount();
        refuseWith = 'nope';
        await click('AI triage');

        await waitForText(/nope/);
        expect(findByText(/^\s*(✓ )?AI triage\s*$/)?.getAttribute('aria-pressed')).toBe('true');
    });

    it('says that switching one off does not delete what was entered', async () => {
        await mount();
        expect(host.textContent).toMatch(/stays saved/i);
    });
});
