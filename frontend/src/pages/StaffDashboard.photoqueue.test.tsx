// @vitest-environment jsdom
import type React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render as rtlRender, screen, cleanup, within } from '@testing-library/react';
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
            photos_pending_review: 0,
        },
        {
            id: 2,
            service_request_id: 'SR-002',
            service_code: 'streetlight',
            service_name: 'Streetlight Out',
            // Closed AND unassigned: the two states that used to hide a held
            // photo from the only person who could act on it.
            status: 'closed',
            photos_pending_review: 2,
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

// No widen-the-scope helper here, deliberately. The keyboard suite needs one
// because the queue opens scoped to "My Requests" and its fixtures are
// unassigned; these tests must reach the held photo WITHOUT widening anything,
// because that is the thing that was broken.

/**
 * Finding a photo the blur could not clear.
 *
 * The withholding was already right: such a photo is kept out of `media_urls`
 * so no public surface can render it, and the report goes through regardless.
 * What was missing was any way to find one. `media_pending_review` was read in
 * exactly one place -- an amber panel inside a report's detail view -- with no
 * badge, count or filter anywhere, so a held photo on a report nobody opened
 * was reviewed only by accident. Measured on the live demo: the resident was
 * shown "A staff member will review this photo" and nothing in the staff
 * portal was asking anyone to.
 *
 * That is not a rare case. A town whose cloud detector has no usable
 * credentials falls back to on-server detection, and every photo that
 * fallback cannot clear takes this path.
 *
 * The fixture is deliberately hostile: the held photo is on a report that is
 * CLOSED and assigned to NOBODY, while the queue opens scoped to "My
 * Requests" and to open reports. Those are the filters that hid it.
 */

describe('the withheld-photo queue', () => {
    it('says how many photos are waiting, without being asked', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        await gotoQueue(user);

        // No filter touched, no report opened, default scope. The point of the
        // number is to reach somebody who is not looking for it.
        const banner = await screen.findByRole('button', { name: /photos? (is|are) waiting for your review/i });
        expect(banner.textContent).toMatch(/2 photos are waiting/);
        expect(banner.getAttribute('aria-pressed')).toBe('false');
    });

    it('opens a list that matches the number it advertised', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        await gotoQueue(user);

        const banner = await screen.findByRole('button', { name: /waiting for your review/i });
        await user.click(banner);

        expect(banner.getAttribute('aria-pressed')).toBe('true');
        // The held photo is on the CLOSED, UNASSIGNED report. Composing this
        // filter with the default "My Requests" scope and the "Open" status
        // view -- which is what a tidier implementation does -- showed an empty
        // list under a banner promising two photos, which teaches people to
        // ignore the banner.
        expect(await screen.findByRole('button', { name: /Streetlight Out/ })).toBeTruthy();
        expect(screen.queryByRole('button', { name: /Pothole/ })).toBeNull();
    });

    it('marks the report in the list, in words and not only in colour', async () => {
        const user = userEvent.setup();
        render(<StaffDashboard />);
        await gotoQueue(user);
        await user.click(await screen.findByRole('button', { name: /waiting for your review/i }));

        const row = await screen.findByRole('button', { name: /Streetlight Out/ });
        // An amber pill says nothing to a screen reader, and nothing to anyone
        // who is not already looking for it (WCAG 1.4.1).
        expect(row.textContent).toMatch(/2 PHOTOS TO REVIEW/i);
    });

    it('stays out of the way when there is nothing to review', async () => {
        // The banner is worth seeing because it is unusual. One that is always
        // there is furniture.
        const { api } = await import('../services/api');
        (api.getRequests as any).mockResolvedValueOnce(
            REQUESTS.map(r => ({ ...r, photos_pending_review: 0 })));

        const user = userEvent.setup();
        render(<StaffDashboard />);
        await gotoQueue(user);
        await screen.findByRole('group', { name: 'Filter by assignment' });

        expect(screen.queryByRole('button', { name: /waiting for your review/i })).toBeNull();
    });
});
