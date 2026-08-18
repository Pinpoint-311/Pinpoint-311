// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * A capability card is a disclosure, and it used to describe itself as one
 * without ever being one.
 *
 * The collapsed bubble and the opened card are two different branches of the
 * same component, so the button that said `aria-expanded` was replaced by a
 * different button the moment it was pressed: the one that survived carried no
 * expanded state at all, and both named a panel that only existed while open.
 * A screen-reader user got a control that never changed and a reference that
 * pointed at nothing, on the one page in the console where every action is
 * "open this and paste a credential in".
 *
 * Separately: the sentence explaining that switching a capability off keeps its
 * credentials was `hidden sm:block` and attached to nothing, so on a phone it
 * did not exist and anywhere else it was never read out beside the switch it
 * was written for.
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

async function mount() {
    const { default: ServiceProviders } = await import('./ServiceProviders');
    await act(async () => {
        root.render(React.createElement(ServiceProviders as any, {
            show: new Set(['ai', 'email']),
            onSwitch: vi.fn().mockResolvedValue(undefined),
        }));
    });
    await act(async () => { await Promise.resolve(); });
}

const buttons = () => Array.from(host.querySelectorAll('button'));
/* jsdom here has no CSS.escape, and one of these ids is a React useId with
 * colons in it, so references are resolved by attribute rather than by
 * building a selector out of them. */
const byId = (id: string) => host.querySelector(`[id="${id}"]`) as HTMLElement | null;
const cardToggle = () => buttons().find(b => b.getAttribute('aria-controls') === 'prov-ai')!;

describe('a capability card as a disclosure', () => {
    it('never names a panel that is not in the document', async () => {
        await mount();
        const referring = buttons().filter(b => b.getAttribute('aria-controls'));
        expect(referring.length).toBeGreaterThan(0);
        for (const b of referring) {
            expect(byId(b.getAttribute('aria-controls')!)).not.toBeNull();
        }
    });

    it('reports open as open, from whichever control is on screen', async () => {
        await mount();

        const collapsed = cardToggle();
        expect(collapsed.getAttribute('aria-expanded')).toBe('false');
        const panelId = collapsed.getAttribute('aria-controls')!;
        // Present but hidden, which is what makes the reference resolve.
        expect(byId(panelId)!.hidden).toBe(true);

        await act(async () => { collapsed.click(); });
        await act(async () => { await Promise.resolve(); });

        // The control that replaces it has to carry the true, or an open card
        // still announces itself as shut.
        const open = buttons().find(b => b.getAttribute('aria-controls') === panelId
            && b.getAttribute('aria-expanded') === 'true');
        expect(open).toBeTruthy();
        expect(byId(panelId)!.hidden).toBe(false);
    });

    it('attaches the switch-off explanation to the switch, at every width', async () => {
        await mount();
        await act(async () => { cardToggle().click(); });
        await act(async () => { await Promise.resolve(); });

        const sw = host.querySelector('[role="switch"]') as HTMLElement;
        expect(sw).not.toBeNull();
        const note = byId(sw.getAttribute('aria-describedby')!)!;
        expect(note).not.toBeNull();
        expect(note.textContent).toMatch(/keeps the credentials saved/i);
        // It was `hidden sm:block`: below the sm breakpoint the explanation of
        // an alarming-looking toggle simply was not on the page.
        expect(note.className).not.toMatch(/\bhidden\b/);
    });

    it('leaves the speaking to the shared region', async () => {
        await mount();
        // The Save & Test verdict lands in the same React batch as the status
        // the card reports upwards, which drives the pill's announcement. Two
        // polite regions written in one tick are announced as neither, so this
        // page carries none of its own.
        expect(host.querySelectorAll('[role="status"], [aria-live], [role="alert"]')).toHaveLength(0);
    });
});
