// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * The town has to be asked where its credentials go, before it has any.
 *
 * The backend refuses the save either way; this panel is what makes the refusal
 * something a clerk can act on rather than something they hit. The two things
 * it has to get right are that the encrypted database is offered as a real
 * answer -- otherwise the gate dead-ends a town with no cloud account -- and
 * that choosing it says what it means for backups, which is the entire reason
 * the question is worth asking.
 */

let response: any = null;
const chosen: string[] = [];
let refuseWith: string | null = null;

vi.mock('../services/api', () => {
    const api: any = new Proxy({}, {
        get: (_t, prop: string) => {
            if (prop === 'getSecretStore') return vi.fn(async () => response);
            if (prop === 'chooseSecretStore') {
                return vi.fn(async (store: string) => {
                    if (refuseWith) throw new Error(refuseWith);
                    chosen.push(store);
                    return { chosen: true, store, options: [], reachable: true };
                });
            }
            return vi.fn().mockResolvedValue({});
        },
    });
    return { default: api, api };
});

const UNCHOSEN = {
    chosen: false, store: null,
    options: ['google', 'azure', 'aws', 'database'], reachable: false,
};

let host: HTMLDivElement;
let root: Root;

async function mount() {
    const { default: Gate } = await import('./SecretStoreGate');
    await act(async () => { root.render(React.createElement(Gate)); });
    return host.textContent || '';
}

function button(pattern: RegExp): HTMLElement {
    const el = Array.from(host.querySelectorAll('button'))
        .find(b => pattern.test(b.textContent || ''));
    if (!el) throw new Error(`no button matching ${pattern}`);
    return el as HTMLElement;
}

async function click(pattern: RegExp) {
    await act(async () => { button(pattern).click(); });
}

beforeEach(() => {
    response = UNCHOSEN;
    chosen.length = 0;
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

describe('choosing where credentials are kept', () => {
    it('asks before anything below can be filled in', async () => {
        const text = await mount();
        expect(text).toContain('where should this town’s credentials be kept');
        expect(text).toMatch(/will accept a key until this is answered/i);
    });

    it('offers the encrypted database as a real answer', async () => {
        // Not a fallback a town discovers it landed in. Without this the gate
        // dead-ends anyone whose cloud procurement is unfinished, and the point
        // is consent, not capability.
        expect(await mount()).toContain('This server’s own encrypted database');
    });

    it('says what the database choice means for backups, before it is made', async () => {
        await mount();
        expect(host.textContent).not.toMatch(/every .{0,10}backup/i);

        await click(/encrypted database/);

        // The specific consequence, in the specific words that matter: the keys
        // are in every backup, and backups leave this server.
        expect(host.textContent).toMatch(/backup/i);
        expect(host.textContent).toMatch(/copied off this server/i);
    });

    it('records the choice', async () => {
        await mount();
        await click(/encrypted database/);
        await click(/Use this store/);

        expect(chosen).toEqual(['database']);
    });

    it('will not submit until something is picked', async () => {
        await mount();
        expect((button(/Use this store/) as HTMLButtonElement).disabled).toBe(true);
    });

    it('does not require the chosen vault to be working yet', async () => {
        // The credentials that make a vault reachable are entered on this same
        // page, so gating on reachability would be a loop with no way in.
        await mount();
        await click(/Azure Key Vault/);
        expect((button(/Use this store/) as HTMLButtonElement).disabled).toBe(false);
    });

    it('gets out of the way once answered', async () => {
        response = { chosen: true, store: 'azure', options: [], reachable: true };
        const text = await mount();

        expect(text).not.toMatch(/where should this town/i);
        expect(text).toContain('Azure Key Vault');
    });

    it('says when the chosen vault is not reachable yet', async () => {
        // Because anything saved now waits in the encrypted database, which is
        // the window this whole gate is about.
        response = { chosen: true, store: 'azure', options: [], reachable: false };
        expect(await mount()).toMatch(/not reachable yet/i);
    });

    it('says nothing about reachability once the database is the store', async () => {
        // It is the database. There is nowhere for anything to move to.
        response = { chosen: true, store: 'database', options: [], reachable: false };
        expect(await mount()).not.toMatch(/not reachable/i);
    });

    it('reports a refused choice rather than looking like it took', async () => {
        await mount();
        await click(/AWS Secrets Manager/);
        refuseWith = 'the store is pinned by this deployment';
        await click(/Use this store/);

        expect(host.textContent).toContain('pinned by this deployment');
        expect(host.textContent).toMatch(/where should this town/i);
    });
});
