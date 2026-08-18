// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AccessibilityProvider } from '../context/AccessibilityContext';

/**
 * The staff map had no keyboard path to a single request.
 *
 * Every pin is drawn by the map provider onto a canvas and opens its popup on
 * click; the popup's "View Full Details" is a DOM button synthesised into an
 * overlay nothing puts focus into. A staff member working without a mouse could
 * see the map, could not open anything on it, and got no signal at all when a
 * filter added or removed forty pins.
 *
 * The contract now: the plotted requests are also real <button>s in the tab
 * order calling the same onRequestSelect the popup calls, built from the same
 * filtered array the markers are, and every filter change is both counted on
 * screen and spoken through the app's single live region.
 */

/**
 * Every set of *request* markers handed to the map, newest last. The component
 * makes two marker layers -- the clustered one is the requests, the plain one
 * is the asset layers -- so the cluster option is what tells them apart.
 */
const markerSets: any[][] = [];

const fakeMap = {
    createPopup: () => ({ setContent: vi.fn(), openAt: vi.fn(), close: vi.fn() }),
    createMarkerLayer: (options?: any) => ({
        setMarkers: (markers: any[]) => {
            if (options?.cluster) markerSets.push(markers);
            return [];
        },
        addMarker: vi.fn(),
        clear: vi.fn(),
    }),
    on: vi.fn(),
    addGeoJsonLayer: () => ({ remove: vi.fn() }),
    fitBounds: vi.fn(),
    setCenter: vi.fn(),
    destroy: vi.fn(),
};

// The SDK is not under test; the icon helpers are real, because the pin shapes
// this file asserts on come from them.
vi.mock('../maps', async () => {
    const actual = await vi.importActual<any>('../maps');
    return {
        ...actual,
        hasMapCredential: () => true,
        createMap: vi.fn(async () => fakeMap),
    };
});

vi.mock('../context/TranslationContext', () => ({
    useTranslation: () => ({ language: 'en' }),
}));

import StaffDashboardMap from './StaffDashboardMap';

const requests: any[] = [
    {
        service_request_id: 'REQ-001',
        service_code: 'pothole',
        service_name: 'Pothole',
        status: 'open',
        description: 'Deep pothole near the crosswalk',
        address: '12 Main St',
        requested_datetime: '2026-06-03T10:00:00Z',
        lat: 40.22,
        long: -74.01,
    },
    {
        service_request_id: 'REQ-002',
        service_code: 'streetlight',
        service_name: 'Streetlight Out',
        status: 'closed',
        description: 'Light flickers all night',
        address: '4 Oak Ave',
        requested_datetime: '2026-06-04T10:00:00Z',
        lat: 40.23,
        long: -74.02,
    },
];

const services: any[] = [
    { service_code: 'pothole', service_name: 'Pothole' },
    { service_code: 'streetlight', service_name: 'Streetlight Out' },
];

const renderMap = (onRequestSelect = vi.fn()) => {
    render(
        <AccessibilityProvider>
            <StaffDashboardMap
                config={{ provider: 'google', apiKey: 'k' } as any}
                requests={requests}
                services={services}
                departments={[]}
                users={[]}
                mapLayers={[]}
                onRequestSelect={onRequestSelect}
            />
        </AccessibilityProvider>,
    );
    return onRequestSelect;
};

const listToggle = () => screen.getByRole('button', { name: /plotted requests/i });

beforeEach(() => {
    markerSets.length = 0;
    // The panel starts open only above the mobile breakpoint.
    (window as any).innerWidth = 1280;
    // jsdom ships no matchMedia; AccessibilityProvider reads the motion and
    // contrast preferences on mount.
    (window as any).matchMedia = vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
    });
});
afterEach(cleanup);

describe('StaffDashboardMap keyboard access to the plotted requests', () => {
    it('opens the request list from the keyboard and reports its state', async () => {
        const user = userEvent.setup();
        renderMap();

        const toggle = listToggle();
        expect(toggle.getAttribute('aria-expanded')).toBe('false');
        expect(toggle.getAttribute('aria-controls')).toBe('map-request-list');

        toggle.focus();
        expect(document.activeElement).toBe(toggle);
        await user.keyboard('{Enter}');

        expect(toggle.getAttribute('aria-expanded')).toBe('true');
        expect(document.getElementById('map-request-list')).toBeTruthy();
    });

    it('reaches every plotted request by Tab, in list order', async () => {
        const user = userEvent.setup();
        renderMap();

        listToggle().focus();
        await user.keyboard('{Enter}');

        const list = document.getElementById('map-request-list')!;
        const items = within(list).getAllByRole('button');
        expect(items).toHaveLength(2);

        // From the section header, Tab must land on the first request rather
        // than skipping the list for the status filters below it.
        listToggle().focus();
        const reached: Element[] = [];
        for (let i = 0; i < 4 && !reached.includes(items[1]); i++) {
            await user.tab();
            reached.push(document.activeElement!);
        }
        expect(reached.indexOf(items[0])).toBe(0);
        expect(reached.indexOf(items[1])).toBe(1);
    });

    it('activates the same handler the pin popup calls, with Enter and with Space', async () => {
        const user = userEvent.setup();
        const onRequestSelect = renderMap();

        listToggle().focus();
        await user.keyboard('{Enter}');

        const list = document.getElementById('map-request-list')!;
        const [first, second] = within(list).getAllByRole('button');

        first.focus();
        await user.keyboard('{Enter}');
        expect(onRequestSelect).toHaveBeenLastCalledWith('REQ-001');

        second.focus();
        await user.keyboard(' ');
        expect(onRequestSelect).toHaveBeenLastCalledWith('REQ-002');
        expect(onRequestSelect).toHaveBeenCalledTimes(2);

        // The same handler the popup's "View Full Details" button is wired to:
        // the markers carry an onClick, and the list is built from the same
        // filtered array, so both routes end at onRequestSelect.
        expect(markerSets[markerSets.length - 1]).toHaveLength(2);
    });

    it('names each request by service, address, status and ID', async () => {
        const user = userEvent.setup();
        renderMap();
        listToggle().focus();
        await user.keyboard('{Enter}');

        const list = document.getElementById('map-request-list')!;
        expect(within(list).getByRole('button', { name: /Pothole.*12 Main St.*Open.*REQ-001/s })).toBeTruthy();
        expect(within(list).getByRole('button', { name: /Streetlight Out.*4 Oak Ave.*Closed.*REQ-002/s })).toBeTruthy();
    });

    it('keeps the list and the pins showing the same requests when a filter changes', async () => {
        const user = userEvent.setup();
        renderMap();
        listToggle().focus();
        await user.keyboard('{Enter}');

        const closedBox = screen.getByRole('checkbox', { name: /closed/i });
        closedBox.focus();
        await user.keyboard(' ');

        const list = document.getElementById('map-request-list')!;
        expect(within(list).getAllByRole('button')).toHaveLength(1);
        expect(markerSets[markerSets.length - 1]).toHaveLength(1);
        expect(listToggle().textContent).toContain('Plotted Requests (1)');
    });
});

describe('StaffDashboardMap filter status messages', () => {
    it('shows a visible count of what is plotted', () => {
        renderMap();
        expect(screen.getByText('2 of 2 requests plotted')).toBeTruthy();
    });

    it('announces the new count through the app live region when a filter changes', async () => {
        const user = userEvent.setup();
        renderMap();

        // Nothing is announced for the first render: that is a page loading,
        // not a status change.
        expect(document.getElementById('aria-live-region')!.textContent).toBe('');

        const openBox = screen.getByRole('checkbox', { name: /^open$/i });
        openBox.focus();
        await user.keyboard(' ');

        expect(screen.getByText('1 of 2 requests plotted')).toBeTruthy();
        const region = await screen.findByText('1 of 2 requests shown on the map');
        expect(region.id).toBe('aria-live-region');
        expect(region.getAttribute('aria-live')).toBe('polite');
    });
});

describe('StaffDashboardMap filter panel semantics', () => {
    it('gives every section header aria-expanded and the region it controls', async () => {
        const user = userEvent.setup();
        renderMap();

        const status = screen.getByRole('button', { name: 'Request Status' });
        expect(status.getAttribute('aria-expanded')).toBe('true');
        expect(status.getAttribute('aria-controls')).toBe('map-filter-status');

        const categories = screen.getByRole('button', { name: 'Categories' });
        expect(categories.getAttribute('aria-expanded')).toBe('false');
        categories.focus();
        await user.keyboard('{Enter}');
        expect(categories.getAttribute('aria-expanded')).toBe('true');
    });

    it('groups each checkbox list, so the checkboxes are not orphans', () => {
        renderMap();
        expect(screen.getByRole('group', { name: /request status/i })).toBeTruthy();
    });

    it('labels the search field, its helper text and its clear button', async () => {
        const user = userEvent.setup();
        renderMap();

        const search = screen.getByRole('button', { name: 'Search Requests' });
        search.focus();
        await user.keyboard('{Enter}');

        const input = screen.getByLabelText('Search requests');
        expect(input.getAttribute('aria-describedby')).toBe('map-request-search-help');
        expect(document.getElementById('map-request-search-help')!.textContent)
            .toContain('Filter by assigned staff');

        input.focus();
        await user.keyboard('oak');
        // The X had no accessible name at all: a screen reader read "button".
        const clear = screen.getByRole('button', { name: 'Clear search' });
        clear.focus();
        await user.keyboard('{Enter}');
        expect((input as HTMLInputElement).value).toBe('');
    });

    it('takes the closed panel out of the tab order instead of parking focus off-screen', async () => {
        const user = userEvent.setup();
        renderMap();

        const close = screen.getByRole('button', { name: /close requests and filters/i });
        close.focus();
        await user.keyboard('{Enter}');

        const panel = document.getElementById('map-filter-panel')!;
        expect(panel.hasAttribute('inert')).toBe(true);
        expect(panel.getAttribute('aria-hidden')).toBe('true');

        const reopen = screen.getByRole('button', { name: /show requests and filters/i });
        expect(reopen.getAttribute('aria-expanded')).toBe('false');
        expect(reopen.getAttribute('aria-controls')).toBe('map-filter-panel');
    });
});

describe('StaffDashboardMap markers', () => {
    it('varies pin shape by status, not only colour, and names each pin', async () => {
        renderMap();
        await waitFor(() => expect(markerSets.length).toBeGreaterThan(0));
        const markers = markerSets[markerSets.length - 1];
        const byId = (id: string) => markers.find(m => m.title.includes(id));

        const open = byId('REQ-001');
        const closed = byId('REQ-002');
        expect(open.title).toBe('Pothole, at 12 Main St, status Open, request REQ-001');
        expect(closed.title).toBe('Streetlight Out, at 4 Oak Ave, status Closed, request REQ-002');

        // Same size, different glyph: the closed puck is hollow, so the two
        // survive greyscale and the common colour vision deficiencies.
        expect(open.icon.url).not.toBe(closed.icon.url);
        const decode = (url: string) => decodeURIComponent(url.split(',')[1]);
        expect(decode(open.icon.url).match(/<circle/g)!.length)
            .toBeLessThan(decode(closed.icon.url).match(/<circle/g)!.length);
    });
});
