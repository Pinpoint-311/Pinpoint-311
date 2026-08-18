// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The bias panel answered three questions entirely in colour: which layer is
 * showing, whether cluster markers are on, and how severe each flagged cluster
 * is. None of the three was exposed to assistive tech and none survived
 * greyscale (1.4.1 / 4.1.2). On top of that the heat surface is a `<canvas>` —
 * an empty rectangle to a screen reader — with no text alternative at all
 * (1.1.1), so the panel's whole finding was unavailable without sight.
 *
 * The map provider is mocked away: what is under test is the panel's own
 * controls and the words it puts next to the picture, not tile rendering.
 */

const markers: any[] = [];

vi.mock('../maps', () => {
    const layer = {
        setMarkers: (m: any[]) => { markers.length = 0; markers.push(...m); },
        remove: () => { },
    };
    const renderer = {
        capabilities: { canvasOverlay: true },
        createPopup: () => ({ setContent: () => { }, openAt: () => { } }),
        createMarkerLayer: () => layer,
        addCanvasOverlay: () => ({ remove: () => { } }),
        fitBounds: () => { },
        destroy: () => { },
    };
    return {
        createMap: vi.fn(async () => renderer),
        boundsOfPoints: () => null,
        CONTINENTAL_US_CENTER: { lat: 39, lng: -98 },
        el: (tag: string) => document.createElement(tag),
        hasMapCredential: () => true,
        popupRoot: () => document.createElement('div'),
        puckIcon: (options: any) => ({ type: 'image', url: 'data:,', width: 1, height: 1, ...options }),
    };
});

import SpatialBiasHeatmap from './SpatialBiasHeatmap';

afterEach(() => {
    cleanup();
    markers.length = 0;
});

const heatmapData: any = {
    total_reports: 30,
    total_unique_reporters: 6,
    report_points: Array.from({ length: 30 }, (_, i) => ({
        lat: 40 + (i % 3) * 0.002,
        lng: -74 + Math.floor(i / 3) * 0.002,
        weight: 0.5,
    })),
    reporter_points: Array.from({ length: 6 }, (_, i) => ({ lat: 40 + i * 0.002, lng: -74, weight: 0.5 })),
};

const hotspots: any = [
    { lat: 40, lng: -74, count: 25, unique_reporters: 5, sample_address: '12 Main St', top_categories: ['Pothole'] },
    { lat: 40.01, lng: -74.01, count: 9, unique_reporters: 3, sample_address: '4 Oak Ave', top_categories: [] },
];

const renderPanel = () => render(
    <SpatialBiasHeatmap heatmapData={heatmapData} hotspots={hotspots} config={{ provider: 'google', apiKey: 'k' } as any} />
);

describe('SpatialBiasHeatmap layer choice', () => {
    it('is a radio group, one tab stop, arrow keys moving the selection', async () => {
        const user = userEvent.setup();
        renderPanel();

        const group = await screen.findByRole('radiogroup', { name: 'Heat map layer' });
        const [reports, reporters] = screen.getAllByRole('radio');
        expect(group.contains(reports)).toBe(true);

        expect(reports.getAttribute('aria-checked')).toBe('true');
        expect(reporters.getAttribute('aria-checked')).toBe('false');
        expect((reports as HTMLButtonElement).tabIndex).toBe(0);
        expect((reporters as HTMLButtonElement).tabIndex).toBe(-1);

        reports.focus();
        await user.keyboard('{ArrowRight}');

        expect(document.activeElement).toBe(reporters);
        expect(reporters.getAttribute('aria-checked')).toBe('true');
        expect(reports.getAttribute('aria-checked')).toBe('false');
    });
});

describe('SpatialBiasHeatmap cluster toggle', () => {
    it('exposes its on/off state rather than only a fill colour', async () => {
        const user = userEvent.setup();
        renderPanel();

        const toggle = await screen.findByRole('button', { name: 'Clusters' });
        expect(toggle.getAttribute('aria-pressed')).toBe('true');

        toggle.focus();
        await user.keyboard('{Enter}');
        await waitFor(() => expect(toggle.getAttribute('aria-pressed')).toBe('false'));
    });
});

describe('SpatialBiasHeatmap text alternative', () => {
    it('describes the canvas heat surface in words', async () => {
        renderPanel();

        const summary = await screen.findByText(/Heat map of 30 reports/);
        expect(summary.textContent).toMatch(/areas of roughly 150 metres/);
        // The spread, which is the thing the picture is actually read for.
        expect(summary.textContent).toMatch(/concentrated|evenly spread/);
    });

    it('follows the selected layer, so the words never describe the other picture', async () => {
        const user = userEvent.setup();
        renderPanel();

        await screen.findByText(/Heat map of 30 reports/);

        const [, reporters] = screen.getAllByRole('radio');
        await user.click(reporters);

        await waitFor(() => expect(screen.getByText(/Heat map of 6 reporter locations/)).toBeTruthy());
    });
});

describe('SpatialBiasHeatmap severity', () => {
    it('puts the level in words in the flagged-cluster list, not only in a dot', async () => {
        renderPanel();

        // 25/5 = 5.0x -> high; 9/3 = 3.0x -> moderate.
        expect(await screen.findByText(/High bias, 5\.0x/)).toBeTruthy();
        expect(screen.getByText(/Moderate bias, 3\.0x/)).toBeTruthy();
    });

    it("names the level in each marker's accessible name and shapes it too", async () => {
        renderPanel();

        await waitFor(() => expect(markers.length).toBe(2));

        const high = markers.find(m => m.title.startsWith('High bias'));
        expect(high).toBeTruthy();
        expect(high.title).toMatch(/25 reports from 5 reporters \(5\.0 per reporter\) near 12 Main St/);
        // Filled puck for a flagged cluster; the ring is reserved for balanced.
        expect(high.icon.hollow).toBe(false);

        const moderate = markers.find(m => m.title.startsWith('Moderate bias'));
        expect(moderate).toBeTruthy();
        expect(moderate.icon.hollow).toBe(false);
    });
});
