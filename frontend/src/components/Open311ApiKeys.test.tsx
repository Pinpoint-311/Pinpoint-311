// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
// framer-motion measures layout through scrollTo, which jsdom does not implement.
window.scrollTo = (() => {}) as typeof window.scrollTo;

/**
 * Admin Console > Integrations > Open311 API keys.
 *
 * Pins the promises the screen makes: the key is shown once with a copy
 * button and a "you won't see it again" note, the list carries only the
 * prefix, revoking asks first, and the anonymous switch defaults off and
 * asks before turning on.
 */

const api = vi.hoisted(() => ({
    getOpen311Keys: vi.fn(),
    getOpen311Settings: vi.fn(),
    createOpen311Key: vi.fn(),
    revokeOpen311Key: vi.fn(),
    updateOpen311Settings: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));

const dialog = vi.hoisted(() => ({ confirm: vi.fn(), alert: vi.fn() }));
vi.mock('./DialogProvider', () => ({ useDialog: () => dialog }));

const SECRET = 'AbCdEfGh-the-rest-of-a-43-character-secret';

const existing = {
    id: 1, name: 'County app', contact_email: 'dev@county.example', key_prefix: 'Zz9Yy8Xx',
    rate_limit_per_minute: null, effective_rate_limit_per_minute: 60, created_by: 'admin',
    created_at: '2026-10-01T10:00:00Z', last_used_at: null, revoked_at: null, revoked_by: null,
    status: 'active' as const,
};
const settings = {
    allow_anonymous_submissions: false, jurisdiction_id: null,
    anonymous_rate_limit: '10/minute', default_key_rate_limit_per_minute: 60,
};

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    api.getOpen311Keys.mockResolvedValue([existing]);
    api.getOpen311Settings.mockResolvedValue(settings);
});
afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.clearAllMocks();
});

const flush = () => act(async () => { await new Promise(r => setTimeout(r, 0)); });

async function mount() {
    const { default: Open311ApiKeys } = await import('./Open311ApiKeys');
    await act(async () => { root.render(React.createElement(Open311ApiKeys)); });
    await flush();
    // Open the accordion.
    const header = Array.from(host.querySelectorAll('button')).find(b => b.textContent?.includes('Open311 API keys'))!;
    await act(async () => { header.click(); });
    await flush();
}

function setInput(input: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('Open311ApiKeys', () => {
    it('lists keys by prefix with created, last used and status', async () => {
        await mount();
        const text = host.textContent || '';
        expect(text).toContain('County app');
        expect(text).toContain('Zz9Yy8Xx…');
        expect(text).toContain('Never');          // last used
        expect(text).toContain('Active');
    });

    it('shows a new key once, with a copy button and a warning', async () => {
        api.createOpen311Key.mockResolvedValue({ ...existing, id: 2, name: 'Vendor', key_prefix: SECRET.slice(0, 8), api_key: SECRET });
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.assign(navigator, { clipboard: { writeText } });
        await mount();

        const [name, contact] = Array.from(host.querySelectorAll('form input')) as HTMLInputElement[];
        await act(async () => { setInput(name, 'Vendor'); setInput(contact, 'dev@vendor.example'); });
        const form = host.querySelector('form')!;
        await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
        await flush();

        expect(api.createOpen311Key).toHaveBeenCalledWith({ name: 'Vendor', contact_email: 'dev@vendor.example' });
        const panel = host.querySelector('[data-testid="open311-new-key"]')!;
        expect(panel.textContent).toContain(SECRET);
        expect(panel.textContent?.toLowerCase()).toContain("won't see it again");

        const copy = Array.from(panel.querySelectorAll('button')).find(b => b.textContent?.includes('Copy'))!;
        await act(async () => { copy.click(); });
        await flush();
        expect(writeText).toHaveBeenCalledWith(SECRET);
        expect(panel.textContent).toContain('Copied');

        // The table carries the prefix only, never the key.
        const table = host.querySelector('table')!;
        expect(table.textContent).not.toContain(SECRET);
        expect(table.textContent).toContain(`${SECRET.slice(0, 8)}…`);

        // Dismissed, the key is gone from the page.
        const done = Array.from(panel.querySelectorAll('button')).find(b => b.textContent === 'Done')!;
        await act(async () => { done.click(); });
        expect(host.textContent).not.toContain(SECRET);
    });

    it('asks before revoking, and does nothing when cancelled', async () => {
        dialog.confirm.mockResolvedValueOnce(false);
        await mount();
        const revoke = host.querySelector('button[aria-label="Revoke key for County app"]') as HTMLButtonElement;
        await act(async () => { revoke.click(); });
        await flush();
        expect(dialog.confirm).toHaveBeenCalled();
        expect(api.revokeOpen311Key).not.toHaveBeenCalled();

        dialog.confirm.mockResolvedValueOnce(true);
        api.revokeOpen311Key.mockResolvedValue({ ...existing, status: 'revoked', revoked_at: '2026-10-18T00:00:00Z' });
        await act(async () => { revoke.click(); });
        await flush();
        expect(api.revokeOpen311Key).toHaveBeenCalledWith(1);
        expect(host.textContent).toContain('Revoked');
        expect(host.querySelector('button[aria-label="Revoke key for County app"]')).toBeNull();
    });

    it('has the anonymous switch off by default and confirms before turning it on', async () => {
        await mount();
        const toggle = host.querySelector('button[role="switch"]') as HTMLButtonElement;
        expect(toggle.getAttribute('aria-checked')).toBe('false');

        dialog.confirm.mockResolvedValueOnce(true);
        api.updateOpen311Settings.mockResolvedValue({ ...settings, allow_anonymous_submissions: true });
        await act(async () => { toggle.click(); });
        await flush();
        expect(dialog.confirm).toHaveBeenCalled();
        expect(api.updateOpen311Settings).toHaveBeenCalledWith({ allow_anonymous_submissions: true });
        expect(toggle.getAttribute('aria-checked')).toBe('true');
    });
});
