// @vitest-environment jsdom
import type React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render as rtlRender, screen, cleanup, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The keyboard and screen-reader contract for the staff request queue.
 *
 * Four things were broken here, and each one ends a keyboard-only or
 * screen-reader shift rather than merely slowing it down:
 *
 *  - Evidence photos were bare `<img onClick>`: not focusable, no role, no key
 *    handler. A staff member without a mouse could read a report about a
 *    flooded basement and never open a single photo of it.
 *  - The lightbox those photos opened had no dialog role, moved no focus,
 *    trapped none, handled no Escape, and told the user on screen to "click
 *    anywhere to close" -- an instruction that is simply false without a
 *    pointer.
 *  - Selecting a request scrolled the detail panel and left focus on the list
 *    row. Below 1024px, where the panel is a `fixed inset-0` overlay, the next
 *    Tab then walked the list *behind* it: no focus ring anywhere on screen.
 *  - Filtering the list said nothing and showed no count, so there was nothing
 *    to hear and nothing to go back and read.
 *
 * Real key presses throughout: a synthetic click cannot tell you where focus
 * went, and where focus went is the entire subject.
 */

const { REQUESTS, DETAIL } = vi.hoisted(() => {
    const REQUESTS = [
        {
            id: 1,
            service_request_id: 'SR-001',
            service_code: 'pothole',
            service_name: 'Pothole',
            status: 'open',
            description: 'Deep pothole near the crosswalk',
            address: '12 Main St',
            requested_datetime: '2026-06-03T10:00:00Z',
            assigned_to: null,
            assigned_department_id: null,
        },
        {
            id: 2,
            service_request_id: 'SR-002',
            service_code: 'streetlight',
            service_name: 'Streetlight Out',
            status: 'open',
            description: 'Light flickers all night',
            address: '4 Oak Ave',
            requested_datetime: '2026-06-04T10:00:00Z',
            assigned_to: null,
            assigned_department_id: null,
        },
    ];
    const DETAIL = {
        ...REQUESTS[0],
        email: 'resident@example.test',
        phone: null,
        first_name: 'Ada',
        last_name: 'Lovelace',
        lat: null,
        long: null,
        media_urls: ['https://town.example/photos/1.jpg', 'https://town.example/photos/2.jpg'],
        ai_analysis: null,
        ai_summary: null,
        custom_fields: null,
        external_links: [],
    };
    return { REQUESTS, DETAIL };
});

vi.mock('../services/api', () => {
    const api = {
        getRequests: vi.fn().mockResolvedValue(REQUESTS),
        getServices: vi.fn().mockResolvedValue([
            { id: 1, service_code: 'pothole', service_name: 'Pothole' },
            { id: 2, service_code: 'streetlight', service_name: 'Streetlight Out' },
        ]),
        getDepartments: vi.fn().mockResolvedValue([]),
        getStaffMembers: vi.fn().mockResolvedValue([]),
        getMapLayers: vi.fn().mockResolvedValue([]),
        getMapsConfig: vi.fn().mockResolvedValue({}),
        getRequestDetail: vi.fn().mockResolvedValue(DETAIL),
        getComments: vi.fn().mockResolvedValue([]),
        getAuditLog: vi.fn().mockResolvedValue([]),
        getRequestIntegrationLinks: vi.fn().mockResolvedValue([]),
        getAssetRelatedRequests: vi.fn().mockResolvedValue([]),
        updateRequest: vi.fn().mockResolvedValue(DETAIL),
        setPublicArchived: vi.fn().mockResolvedValue(DETAIL),
        acceptAiPriority: vi.fn().mockResolvedValue({}),
        deleteRequest: vi.fn().mockResolvedValue({}),
        createComment: vi.fn().mockResolvedValue({}),
        createManualIntake: vi.fn().mockResolvedValue({}),
        refreshRequestWorkOrder: vi.fn().mockResolvedValue({ ok: true, detail: 'Up to date.' }),
        exportRequests: vi.fn().mockResolvedValue({}),
        exportStatistics: vi.fn().mockResolvedValue({}),
        getStatistics: vi.fn().mockResolvedValue({}),
        getAdvancedStatistics: vi.fn().mockResolvedValue({}),
        getHeatmapData: vi.fn().mockResolvedValue(null),
        getSlaPerformance: vi.fn().mockResolvedValue(null),
        getRedirectedStatistics: vi.fn().mockResolvedValue(null),
        uploadImage: vi.fn().mockResolvedValue({ url: '' }),
        analyticsChat: vi.fn().mockResolvedValue({ response: '' }),
    };
    return { api, default: api };
});

// Map canvases, the print window and the side panels are each covered by their
// own suites; what is under test is the queue's own keyboard behaviour.
vi.mock('../components/StaffDashboardMap', () => ({ default: () => null }));
vi.mock('../components/RequestDetailMap', () => ({ default: () => null }));
vi.mock('../components/SpatialBiasHeatmap', () => ({ default: () => null }));
vi.mock('../components/PrintWorkOrder', () => ({ default: () => null }));
vi.mock('../components/ActivityFeed', () => ({ default: () => null }));
vi.mock('../components/ManualIntake', () => ({ default: () => null }));
vi.mock('../components/NotificationSettings', () => ({ default: () => null }));
vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { township_name: 'Testville', modules: {} }, isLoading: false }),
}));
vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({
        user: { id: 1, username: 'clerk', full_name: 'Casey Clerk', role: 'staff', departments: [] },
        logout: vi.fn(),
    }),
}));

import { MemoryRouter } from 'react-router-dom';
import { AccessibilityProvider } from '../context/AccessibilityContext';
import StaffDashboard from './StaffDashboard';

const render = (ui: React.ReactElement) =>
    rtlRender(ui, {
        wrapper: ({ children }) => (
            <MemoryRouter>
                <AccessibilityProvider>{children}</AccessibilityProvider>
            </MemoryRouter>
        ),
    });

// jsdom has no PointerEvent; framer-motion fires one when Enter lands on a
// whileTap element, which every request row is.
if (typeof window.PointerEvent === 'undefined') {
    (window as any).PointerEvent = class PointerEvent extends MouseEvent { };
}

beforeEach(() => {
    localStorage.clear();
    window.history.replaceState(null, '', '/');
    window.scrollTo = vi.fn();
    Element.prototype.scrollTo = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
    if (!window.matchMedia) {
        (window as any).matchMedia = () => ({
            matches: false,
            addEventListener: () => { },
            removeEventListener: () => { },
        });
    }
    // The focus moves are scheduled on rAF so they land after React commits.
    // Running it synchronously puts them inside act() where the test can see them.
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { cb(0); return 0; });
    vi.stubGlobal('cancelAnimationFrame', () => { });
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
});

/** Leave the map dashboard for the queue, which is where the list lives. */
const gotoQueue = async (user: ReturnType<typeof userEvent.setup>) => {
    const nav = screen.getByRole('navigation', { name: 'Main' });
    await user.click(await within(nav).findByRole('button', { name: /^Open \d+ requests$/ }));
};

/**
 * The queue opens scoped to "My Requests", and the fixture is unassigned, so
 * every test that needs rows has to widen the scope first.
 */
const openQueue = async (user: ReturnType<typeof userEvent.setup>) => {
    await gotoQueue(user);
    const group = await screen.findByRole('group', { name: 'Filter by assignment' });
    await user.click(within(group).getByRole('button', { name: /All Requests/ }));
    return screen.findByRole('button', { name: /Pothole/ });
};

const politeRegion = () => document.getElementById('aria-live-region')!;

describe('the request list', () => {
    it('names the current view in a single h1 and marks the open nav item', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        await gotoQueue(user);

        const h1s = await screen.findAllByRole('heading', { level: 1 });
        expect(h1s).toHaveLength(1);
        expect(h1s[0].textContent).toContain('Open Requests');

        const nav = screen.getByRole('navigation', { name: 'Main' });
        expect(within(nav).getByRole('button', { name: /^Open \d+ requests$/ })
            .getAttribute('aria-current')).toBe('page');
    });

    it('shows a result count and announces it when a filter changes', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        await openQueue(user);

        // The count has to be on the page, not only spoken, so it can be re-read.
        expect(screen.getByRole('heading', { name: /Incidents \(2\)/ })).toBeTruthy();

        await user.click(screen.getByRole('textbox', { name: /Search requests/ }));
        await user.keyboard('pothole');

        await waitFor(() => {
            expect(screen.getByRole('heading', { name: /Incidents \(1\)/ })).toBeTruthy();
        });
        await waitFor(() => {
            expect(politeRegion().textContent).toMatch(/1 incident matches the current filters/);
        }, { timeout: 3000 });
    });

    it('exposes the assignment scope as pressed toggles, not colour alone', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        await gotoQueue(user);

        const group = await screen.findByRole('group', { name: 'Filter by assignment' });
        const mine = within(group).getByRole('button', { name: /My Requests/ });
        const all = within(group).getByRole('button', { name: /All Requests/ });

        expect(mine.getAttribute('aria-pressed')).toBe('true');
        expect(all.getAttribute('aria-pressed')).toBe('false');

        all.focus();
        await user.keyboard('{Enter}');

        await waitFor(() => expect(all.getAttribute('aria-pressed')).toBe('true'));
        expect(mine.getAttribute('aria-pressed')).toBe('false');
    });
});

describe('opening and closing a request', () => {
    it('moves focus to the detail heading, and back to the originating row on close', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        const row = await openQueue(user);

        row.focus();
        await user.keyboard('{Enter}');

        const heading = await screen.findByRole('heading', { level: 2, name: /Pothole/ });
        expect(heading.textContent).toContain('SR-001');
        await waitFor(() => expect(document.activeElement).toBe(heading));

        await user.click(screen.getByRole('button', { name: /Back to List/ }));

        // Back on the row the user left, not on <body> — from which the next Tab
        // would restart at the top of the document.
        await waitFor(() => expect(document.activeElement).toBe(row));
    });

    it('restores the document title when the request is closed again', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        const row = await openQueue(user);

        await user.click(row);
        await waitFor(() => expect(document.title).toMatch(/Request SR-001/));

        await user.click(screen.getByRole('button', { name: /Back to List/ }));
        await waitFor(() => expect(document.title).not.toMatch(/Request SR-001/));
        expect(document.title).toMatch(/Open Requests/);
    });
});

describe('evidence photos', () => {
    const openFirstPhoto = async (user: ReturnType<typeof userEvent.setup>) => {
        const row = await openQueue(user);
        await user.click(row);
        const thumb = await screen.findByRole('button', { name: 'Open photo 1 of 2 full size' });
        thumb.focus();
        expect(document.activeElement).toBe(thumb);
        await user.keyboard('{Enter}');
        return thumb;
    };

    it('gives every photo a real button a keyboard can reach and activate', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        await openQueue(user).then(row => user.click(row));

        const thumbs = await screen.findAllByRole('button', { name: /Open photo \d of 2 full size/ });
        expect(thumbs).toHaveLength(2);
        // A real button, not a div wearing a role: it is in the tab sequence
        // without anyone having to set tabindex on it.
        thumbs.forEach(t => expect(t.tagName).toBe('BUTTON'));
    });

    it('opens the lightbox as a modal dialog and puts focus inside it', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        await openFirstPhoto(user);

        const dialog = await screen.findByRole('dialog');
        expect(dialog.getAttribute('aria-modal')).toBe('true');
        expect(dialog.getAttribute('aria-label')).toBe('Photo preview');

        await waitFor(() => {
            expect(dialog.contains(document.activeElement)).toBe(true);
        }, { timeout: 2000 });
    });

    it('closes on Escape and returns focus to the thumbnail that opened it', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        const thumb = await openFirstPhoto(user);

        const dialog = await screen.findByRole('dialog');
        await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true), { timeout: 2000 });

        await user.keyboard('{Escape}');

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        // Not <body>: the user goes back to the photo they were looking at.
        await waitFor(() => expect(document.activeElement).toBe(thumb));
    });
});
