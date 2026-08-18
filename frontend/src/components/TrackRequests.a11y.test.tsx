// @vitest-environment jsdom
import type React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render as rtlRender, screen, cleanup, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * Three defects in the tracker that only show up without a mouse or without
 * sight:
 *
 *  - The status filters and the count tiles said which one was applied with a
 *    background colour and nothing else, so the accessible tree carried no
 *    state at all.
 *  - The count tiles built their Tailwind classes by interpolation
 *    (`from-${color}-500/10`). Tailwind resolves class names by scanning the
 *    source, so those names were never generated and the tiles rendered with no
 *    colour and no border whatsoever -- a rendering bug as much as a contrast
 *    one.
 *  - "Link Copied!" swapped the button's own label and swapped back two seconds
 *    later, which no screen reader reports.
 */

const { REQUESTS } = vi.hoisted(() => ({
    REQUESTS: [
        {
            service_request_id: 'REQ-001',
            service_code: 'pothole',
            service_name: 'Pothole',
            status: 'closed',
            description: 'Deep pothole near the crosswalk',
            address: '12 Main St',
            requested_datetime: '2026-06-03T10:00:00Z',
            photo_count: 0,
        },
        {
            service_request_id: 'REQ-002',
            service_code: 'streetlight',
            service_name: 'Streetlight Out',
            status: 'open',
            description: 'Light flickers all night',
            address: '4 Oak Ave',
            requested_datetime: '2026-06-04T10:00:00Z',
            photo_count: 0,
        },
    ],
}));

vi.mock('../services/api', () => {
    const api = {
        getPublicRequests: vi.fn().mockResolvedValue(REQUESTS),
        getPublicRequestDetail: vi.fn().mockImplementation(async (id: string) =>
            REQUESTS.find(r => r.service_request_id === id)),
        getPublicComments: vi.fn().mockResolvedValue([]),
        getPublicAuditLog: vi.fn().mockResolvedValue([]),
        getMapsConfig: vi.fn().mockResolvedValue({}),
    };
    return { api, default: api };
});

vi.mock('../hooks/useContentTranslation', () => ({
    useContentTranslation: (text: string) => ({ translatedText: text, isTranslating: false }),
}));
vi.mock('../context/TranslationContext', () => ({
    useTranslation: () => ({ language: 'en' }),
}));
vi.mock('./RequestDetailMap', () => ({ default: () => null }));

import { AccessibilityProvider } from '../context/AccessibilityContext';
import TrackRequests from './TrackRequests';

const render = (ui: React.ReactElement) => rtlRender(ui, { wrapper: AccessibilityProvider });

if (typeof window.PointerEvent === 'undefined') {
    (window as any).PointerEvent = class PointerEvent extends MouseEvent { };
}

beforeEach(() => {
    localStorage.clear();
    window.scrollTo = vi.fn();
    if (!window.matchMedia) {
        (window as any).matchMedia = () => ({
            matches: false,
            addEventListener: () => { },
            removeEventListener: () => { },
        });
    }
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('the status filters', () => {
    it('report which one is applied, not only which one is coloured', async () => {
        const user = userEvent.setup();
        render(<TrackRequests />);

        await screen.findByRole('group', { name: 'Filter by status' });
        const tabs = within(screen.getByRole('group', { name: 'Filter by status' }));
        // Each tab carries a wide and a narrow label, so match on a substring.
        const all = tabs.getByRole('button', { name: /All Requests/ });
        const open = tabs.getByRole('button', { name: /^Open/ });
        expect(all.getAttribute('aria-pressed')).toBe('true');
        expect(open.getAttribute('aria-pressed')).toBe('false');

        await user.click(open);

        await waitFor(() => expect(open.getAttribute('aria-pressed')).toBe('true'));
        expect(all.getAttribute('aria-pressed')).toBe('false');
    });

    it('gives the count tiles class names that Tailwind can actually generate', async () => {
        render(<TrackRequests />);
        await screen.findByRole('group', { name: 'Filter by status' });

        // Every class on these tiles has to be a literal that exists in the
        // source. An interpolated one leaves the element unstyled at runtime.
        const tiles = screen.getAllByRole('button')
            .filter(b => /^\d+/.test(b.textContent ?? ''));
        expect(tiles.length).toBe(3);
        for (const tile of tiles) {
            expect(tile.className).not.toMatch(/\$\{|\bundefined\b/);
            expect(tile.className).toMatch(/from-(amber|blue|emerald)-500\/10/);
            expect(tile.className).toMatch(/border-(amber|blue|emerald)-500\/20/);
        }
    });
});

describe('copying a tracking link', () => {
    it('says so through the live region rather than only on the button', async () => {
        const user = userEvent.setup();
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', {
            value: { writeText }, configurable: true, writable: true,
        });

        render(<TrackRequests />);
        const card = await screen.findByRole('button', { name: /Pothole, at 12 Main St/ });
        await user.click(card);

        const share = await screen.findByRole('button', { name: /Share/ });
        await user.click(share);

        expect(writeText).toHaveBeenCalled();
        // The provider's polite region, which is the app's only general-purpose
        // live region: two of them updating together get neither announced.
        await waitFor(
            () => expect(document.getElementById('aria-live-region')!.textContent)
                .toContain('Link copied'),
            { timeout: 2000 },
        );
    });
});

describe('the comment thread', () => {
    it('is a named region the keyboard can enter and scroll', async () => {
        const user = userEvent.setup();
        render(<TrackRequests />);

        await user.click(await screen.findByRole('button', { name: /Pothole, at 12 Main St/ }));

        const region = await screen.findByRole('region', { name: 'Comments' });
        // A scroll container with no focusable children cannot be scrolled by
        // keyboard at all unless it is focusable itself.
        expect(region.tabIndex).toBe(0);
        // And the height cap is relative, so it survives 200% zoom.
        expect(region.className).not.toMatch(/max-h-\[\d+px\]/);
    });
});
