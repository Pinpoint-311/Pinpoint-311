// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

/**
 * The detail map's two markers are mouse-only, and one of them was the only
 * copy of its content on the page.
 *
 * The request pin's popup gives the coordinates and the matched-asset pin's
 * popup gives that asset's property rows; both open on click, on a marker the
 * provider paints into a canvas. Nothing else on the resident's Track Requests
 * page repeats any of it, so without a pointer that content did not exist.
 *
 * The contract now: the same facts are in the DOM as text, next to the map.
 */

const markers: any[] = [];

const fakeMap = {
    createPopup: () => ({ setContent: vi.fn(), openAt: vi.fn(), close: vi.fn() }),
    addMarker: (options: any) => { markers.push(options); return { remove: vi.fn() }; },
    addGeoJsonLayer: () => ({ remove: vi.fn() }),
    setCenter: vi.fn(),
    destroy: vi.fn(),
};

vi.mock('../maps', async () => {
    const actual = await vi.importActual<any>('../maps');
    return {
        ...actual,
        hasMapCredential: () => true,
        createMap: vi.fn(async () => fakeMap),
    };
});

import RequestDetailMap from './RequestDetailMap';

const hydrantLayer: any = {
    id: 1,
    name: 'Hydrants',
    fill_color: '#22c55e',
    stroke_color: '#22c55e',
    geojson: {
        type: 'FeatureCollection',
        features: [{
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [-74.0125, 40.2201] },
            properties: { id: 'HYD-77', name: 'Hydrant 77', flow_rate: 1200, last_inspected: '2026-03-02' },
        }],
    },
};

const matchedAsset: any = {
    layer_name: 'Hydrants',
    asset_id: 'HYD-77',
    asset_type: 'hydrant',
    distance_meters: 4.2,
    properties: { id: 'HYD-77', name: 'Hydrant 77', flow_rate: 1200, last_inspected: '2026-03-02' },
};

beforeEach(() => {
    markers.length = 0;
});
afterEach(cleanup);

describe('RequestDetailMap text equivalent', () => {
    it('states the reported location in text, not only as a pin', async () => {
        render(
            <RequestDetailMap
                config={{ provider: 'google', apiKey: 'k' } as any}
                lat={40.22}
                lng={-74.01}
                mapLayers={[]}
            />,
        );

        expect(await screen.findByText(/Reported location: latitude 40\.220000, longitude -74\.010000\./)).toBeTruthy();
    });

    it('gives the request pin an accessible name that says where it is', async () => {
        render(
            <RequestDetailMap
                config={{ provider: 'google', apiKey: 'k' } as any}
                lat={40.22}
                lng={-74.01}
                mapLayers={[]}
            />,
        );

        await waitFor(() => expect(markers.length).toBeGreaterThan(0));
        expect(markers[0].title).toBe('Request location: 40.220000, -74.010000');
    });

    it('renders the matched-asset popup content, which exists nowhere else', async () => {
        render(
            <RequestDetailMap
                config={{ provider: 'google', apiKey: 'k' } as any}
                lat={40.22}
                lng={-74.01}
                matchedAsset={matchedAsset}
                mapLayers={[hydrantLayer]}
            />,
        );

        expect(await screen.findByText(/Matched asset marker: Hydrants/)).toBeTruthy();
        expect(screen.getByText('Asset ID: HYD-77')).toBeTruthy();
        // The staff panel below this map drops purely numeric properties, so
        // this row has no other home on the page.
        expect(screen.getByText('flow_rate: 1200')).toBeTruthy();
        expect(screen.getByText('last_inspected: 2026-03-02')).toBeTruthy();
        // Same trimming as the popup: id and name are already said above.
        expect(screen.queryByText(/^name:/)).toBeNull();

        expect(await screen.findByText(
            /Asset marker location: latitude 40\.220100, longitude -74\.012500\./,
        )).toBeTruthy();
    });

    it('says nothing about an asset when there is none', async () => {
        render(
            <RequestDetailMap
                config={{ provider: 'google', apiKey: 'k' } as any}
                lat={40.22}
                lng={-74.01}
                mapLayers={[hydrantLayer]}
            />,
        );

        await screen.findByText(/Reported location/);
        expect(screen.queryByText(/Matched asset marker/)).toBeNull();
    });
});
