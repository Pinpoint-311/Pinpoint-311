// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

/**
 * The whole point of this check is the case a server gets backwards.
 *
 * A Google key restricted to "IP addresses" accepts a server call and fails in
 * every resident's browser with RefererNotAllowedMapError: grey map, dead
 * address box, evidence only in the console. A key restricted to "Websites" is
 * correct and *rejects* the server. So the server-side verdict was inverted
 * exactly where it mattered, and the page could only hedge about it.
 *
 * These pin the behaviour that makes the browser check worth having: that a
 * provider which reports failure out-of-band is caught, that one which throws is
 * caught, and that the check puts back the global it borrowed.
 */

const loadMapProvider = vi.fn();
vi.mock('./registry', () => ({ loadMapProvider: (id: string) => loadMapProvider(id) }));

import { checkMapInBrowser } from './browserCheck';

type Hooks = { gm_authFailure?: (() => void) | undefined };

/** A factory whose SDK fails the way Google's does: silently, via a global. */
function silentlyRefusingFactory(delayMs = 0) {
    return {
        id: 'google',
        watchAuthFailure() {
            const host = window as unknown as Hooks;
            const previous = host.gm_authFailure;
            let failed = false;
            host.gm_authFailure = () => { failed = true; };
            return { failed: () => failed, stop: () => { host.gm_authFailure = previous; } };
        },
        load: vi.fn().mockResolvedValue(undefined),
        createRenderer: () => {
            // The map is built and returned intact; the refusal lands afterwards.
            setTimeout(() => (window as unknown as Hooks).gm_authFailure?.(), delayMs);
            return { destroy: vi.fn() };
        },
    };
}

const CONFIG = { provider: 'google' as const, apiKey: 'k' };

beforeEach(() => { loadMapProvider.mockReset(); });
afterEach(() => {
    delete (window as unknown as Record<string, unknown>).gm_authFailure;
    document.body.innerHTML = '';
});

describe('a provider that refuses without throwing', () => {
    it('is caught, not reported as working', async () => {
        loadMapProvider.mockResolvedValue(silentlyRefusingFactory(0));
        const v = await checkMapInBrowser(CONFIG, { settleMs: 800 });

        expect(v.ok).toBe(false);
        expect(v.conclusive).toBe(true);
        expect(v.detail).toMatch(/will not draw for residents/i);
    });

    it('says what to change, naming this origin', async () => {
        // A verdict a clerk cannot act on is the state this replaced.
        loadMapProvider.mockResolvedValue(silentlyRefusingFactory(0));
        const v = await checkMapInBrowser(CONFIG, { settleMs: 800 });

        expect(v.detail).toContain(window.location.origin);
        expect(v.detail).toMatch(/Websites/);
        expect(v.detail).toMatch(/IP addresses/);
    });

    it('waits for a refusal that arrives after the map was built', async () => {
        /* The failure is asynchronous by nature -- it comes back with the first
         * refused tile. Returning as soon as the constructor did would report
         * success on precisely the key this exists to catch. */
        loadMapProvider.mockResolvedValue(silentlyRefusingFactory(250));
        const v = await checkMapInBrowser(CONFIG, { settleMs: 3000 });

        expect(v.ok).toBe(false);
    });
});

describe('a provider that throws instead', () => {
    it('is reported, with the CSP possibility named', async () => {
        // Esri, Azure and MapKit all reject rather than using a global hook, so
        // this is the path every other provider takes.
        loadMapProvider.mockResolvedValue({
            id: 'esri',
            load: vi.fn().mockRejectedValue(new Error('script blocked')),
            createRenderer: vi.fn(),
        });
        const v = await checkMapInBrowser({ provider: 'esri' as const, apiKey: 'k' });

        expect(v.ok).toBe(false);
        expect(v.conclusive).toBe(true);
        expect(v.detail).toMatch(/script blocked/);
        expect(v.detail).toMatch(/Content-Security-Policy/);
    });
});

describe('a provider that works', () => {
    it('passes, and destroys the probe map', async () => {
        const destroy = vi.fn();
        loadMapProvider.mockResolvedValue({
            id: 'esri',
            load: vi.fn().mockResolvedValue(undefined),
            createRenderer: () => ({ destroy }),
        });
        const v = await checkMapInBrowser({ provider: 'esri' as const, apiKey: 'k' });

        expect(v.ok).toBe(true);
        expect(v.detail).toContain(window.location.origin);
        expect(destroy).toHaveBeenCalled();
    });
});

describe('housekeeping', () => {
    it('puts back the global it borrowed, and removes the probe container', async () => {
        /* A hook left behind routes every later failure into a check that has
         * finished, and an orphaned 320x240 div accumulates one per press. */
        const sentinel = () => undefined;
        (window as unknown as Hooks).gm_authFailure = sentinel;
        loadMapProvider.mockResolvedValue(silentlyRefusingFactory(0));

        await checkMapInBrowser(CONFIG, { settleMs: 400 });

        expect((window as unknown as Hooks).gm_authFailure).toBe(sentinel);
        expect(document.body.querySelectorAll('div').length).toBe(0);
    });

    it('gives up rather than failing when there is no provider selected', async () => {
        const v = await checkMapInBrowser({ provider: '' as never });
        expect(v.conclusive).toBe(false);
        expect(loadMapProvider).not.toHaveBeenCalled();
    });

    it('lays the probe out, so the map actually requests tiles', async () => {
        /* A map in a zero-size or display:none container never asks the provider
         * for anything, so it would pass this check without testing the thing
         * being tested. */
        let seen: { w: string; display: string } | null = null;
        loadMapProvider.mockResolvedValue({
            id: 'esri',
            load: vi.fn().mockResolvedValue(undefined),
            createRenderer: (el: HTMLElement) => {
                seen = { w: el.style.width, display: el.style.display };
                return { destroy: vi.fn() };
            },
        });
        await checkMapInBrowser({ provider: 'esri' as const, apiKey: 'k' });

        expect(seen!.w).toBe('320px');
        expect(seen!.display).not.toBe('none');
    });
});
