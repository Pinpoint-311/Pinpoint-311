// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * "I pressed Print Work Order and nothing happened."
 *
 * A blocked pop-up returned early in silence, so the button behaved exactly
 * like a button that had worked. The only signal was the browser's own
 * blocked-pop-up indicator, which is not in the page and not in the
 * accessibility tree.
 *
 * The other half is the sheet itself: it is a whole document, generated here,
 * and it went out with no `lang` and with every photo carrying the same alt.
 */

import PrintWorkOrder from './PrintWorkOrder';
import { AccessibilityProvider } from '../context/AccessibilityContext';

if (!window.matchMedia) {
    (window as any).matchMedia = (query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: () => { }, removeEventListener: () => { },
        addListener: () => { }, removeListener: () => { }, dispatchEvent: () => false,
    });
}

const request = {
    service_request_id: 'REQ-77',
    service_name: 'Pothole',
    service_code: 'pothole',
    status: 'open',
    closed_substatus: null,
    description: 'Deep pothole near the crosswalk',
    address: '12 Main St',
    lat: null,
    long: null,
    requested_datetime: '2026-06-03T10:00:00Z',
    updated_datetime: '2026-06-04T10:00:00Z',
    closed_datetime: null,
    email: 'resident@example.test',
    first_name: 'Ada',
    last_name: 'Lovelace',
    source: 'resident_portal',
    media_urls: ['https://town.example/a.jpg', 'https://town.example/b.jpg'],
    ai_analysis: null,
    manual_priority_score: null,
} as any;

const mount = () => render(
    <AccessibilityProvider>
        <PrintWorkOrder request={request} />
    </AccessibilityProvider>,
);

const printButton = () => screen.getByRole('button', { name: /print work order/i });

let written: string;

/** A stand-in for the pop-up, capturing what gets written into it. */
const fakeWindow = () => {
    written = '';
    return {
        document: {
            write: (html: string) => { written += html; },
            close: () => { },
        },
        print: vi.fn(),
        onload: null as null | (() => void),
    };
};

beforeEach(() => { written = ''; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('PrintWorkOrder when the pop-up is blocked', () => {
    it('says so, visibly and out loud, instead of doing nothing', async () => {
        const user = userEvent.setup();
        vi.spyOn(window, 'open').mockReturnValue(null);
        mount();

        await user.click(printButton());

        /* By id: the shared assertive live region carries the same sentence a
         * moment later, so a text or role query matches two nodes depending on
         * how the timers land. */
        const message = await waitFor(() => {
            const el = document.getElementById('print-work-order-error')!;
            expect(el).toBeTruthy();
            return el;
        });
        expect(message.getAttribute('role')).toBe('alert');
        expect(message.textContent).toMatch(/blocked the print window/i);
        // The button points at the explanation, so arriving back on it says why.
        expect(printButton().getAttribute('aria-describedby')).toBe(message.id);

        await waitFor(() => {
            expect(document.getElementById('aria-live-region-assertive')!.textContent)
                .toMatch(/blocked the print window/i);
        });
    });

    it('clears the message once printing works', async () => {
        const user = userEvent.setup();
        const open = vi.spyOn(window, 'open').mockReturnValue(null);
        mount();
        await user.click(printButton());
        await waitFor(() => expect(document.getElementById('print-work-order-error')).toBeTruthy());

        open.mockReturnValue(fakeWindow() as any);
        await user.click(printButton());

        // Queried by id: the live region still holds the spoken copy of the
        // earlier message for a few seconds, and that is not what is asserted.
        expect(document.getElementById('print-work-order-error')).toBeNull();
        expect(printButton().getAttribute('aria-describedby')).toBeNull();
    });
});

describe('the generated work order document', () => {
    it('declares a language', async () => {
        const user = userEvent.setup();
        document.documentElement.lang = 'en';
        vi.spyOn(window, 'open').mockReturnValue(fakeWindow() as any);
        mount();

        await user.click(printButton());
        expect(written).toContain('<html lang="en">');
    });

    it('gives each photo an alt that tells it from the others', async () => {
        const user = userEvent.setup();
        vi.spyOn(window, 'open').mockReturnValue(fakeWindow() as any);
        mount();

        await user.click(printButton());

        expect(written).toContain('alt="Photo 1 of 2 submitted with request REQ-77"');
        expect(written).toContain('alt="Photo 2 of 2 submitted with request REQ-77"');
        expect(written).not.toContain('alt="Issue photo"');
    });
});
