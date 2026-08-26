// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';

/**
 * The town outline reaches the request detail map.
 *
 * It rendered on the resident submission page and vanished on the tracker,
 * which reads as a rendering bug and is not one: LocationPicker takes a
 * `townshipBoundary` prop and draws it, and this component simply had no such
 * prop, so neither caller could have passed one. A resident who had just placed
 * a pin inside a visible outline looked their request up and found the outline
 * gone.
 *
 * These assert what was drawn -- the polygon rings, and the camera the map is
 * left on -- rather than that the prop exists. A test that only checked for the
 * prop, or for the word "boundary" in the source, would pass against a
 * component that accepted it and threw it away.
 */

/** One ring, plus a hole, so the ring-flattening path is the one under test. */
const boundary = {
    type: 'FeatureCollection',
    features: [{
        type: 'Feature',
        properties: {},
        geometry: {
            type: 'Polygon',
            coordinates: [
                [[-74.30, 40.75], [-74.28, 40.75], [-74.28, 40.73], [-74.30, 40.73], [-74.30, 40.75]],
                [[-74.295, 40.745], [-74.290, 40.745], [-74.290, 40.740], [-74.295, 40.740], [-74.295, 40.745]],
            ],
        },
    }],
};

/**
 * A boundary the ring flattener cannot reduce to one polygon: an outline
 * published as lines rather than as an area, which is how some county GIS
 * exports arrive.
 */
const lineBoundary = {
    type: 'FeatureCollection',
    features: [{
        type: 'Feature',
        properties: {},
        geometry: {
            type: 'MultiLineString',
            coordinates: [[[-74.30, 40.75], [-74.28, 40.75], [-74.28, 40.73], [-74.30, 40.73], [-74.30, 40.75]]],
        },
    }],
};

const calls = {
    polygons: [] as any[],
    geoJsonLayers: [] as any[],
    markers: [] as any[],
    fitBounds: [] as any[],
    setCenter: [] as any[],
    setZoom: [] as any[],
};

const handle = () => ({ remove: vi.fn() });

const fakeMap = {
    createPopup: () => ({ setContent: vi.fn(), openAt: vi.fn(), close: vi.fn() }),
    addMarker: (options: any) => { calls.markers.push(options); return handle(); },
    addPolygon: (options: any) => { calls.polygons.push(options); return handle(); },
    addGeoJsonLayer: (options: any) => { calls.geoJsonLayers.push(options); return handle(); },
    fitBounds: (bounds: any, options?: any) => { calls.fitBounds.push({ bounds, options }); },
    setCenter: (center: any) => { calls.setCenter.push(center); },
    setZoom: (zoom: number) => { calls.setZoom.push(zoom); },
    panTo: vi.fn(),
    getBounds: () => null,
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

const config = { provider: 'esri', apiKey: 'k' } as any;

beforeEach(() => {
    calls.polygons.length = 0;
    calls.geoJsonLayers.length = 0;
    calls.markers.length = 0;
    calls.fitBounds.length = 0;
    calls.setCenter.length = 0;
    calls.setZoom.length = 0;
});
afterEach(cleanup);

describe('RequestDetailMap township boundary', () => {
    it('draws the outline it is given, holes and all', async () => {
        render(
            <RequestDetailMap
                config={config}
                lat={40.7441}
                lng={-74.2915}
                mapLayers={[]}
                townshipBoundary={boundary}
            />,
        );

        await waitFor(() => expect(calls.polygons).toHaveLength(1));

        // Both rings, as LatLng paths: the outer boundary and the hole. One
        // ring only would render a filled shape over the hole.
        const paths = calls.polygons[0].paths;
        expect(paths).toHaveLength(2);
        expect(paths[0]).toHaveLength(5);
        expect(paths[0][0]).toEqual({ lat: 40.75, lng: -74.30 });
        expect(paths[1]).toHaveLength(5);

        // Visible, and not swallowing clicks meant for the map underneath.
        expect(calls.polygons[0].style.strokeOpacity).toBeGreaterThan(0);
        expect(calls.polygons[0].style.clickable).toBe(false);
    });

    it('keeps the camera on the request rather than fitting the whole town', async () => {
        render(
            <RequestDetailMap
                config={config}
                lat={40.7441}
                lng={-74.2915}
                mapLayers={[]}
                townshipBoundary={boundary}
            />,
        );

        await waitFor(() => expect(calls.polygons).toHaveLength(1));
        await waitFor(() => expect(calls.markers).toHaveLength(1));

        // The whole point of this map is one request at street level. Fitting
        // the municipality would shrink the pin the resident came to look at.
        expect(calls.fitBounds).toHaveLength(0);
        expect(calls.setCenter).toContainEqual({ lat: 40.7441, lng: -74.2915 });
        expect(calls.markers[0].position).toEqual({ lat: 40.7441, lng: -74.2915 });
    });

    it('falls back to a GeoJSON layer for an outline that is not one polygon', async () => {
        render(
            <RequestDetailMap
                config={config}
                lat={40.7441}
                lng={-74.2915}
                mapLayers={[]}
                townshipBoundary={lineBoundary}
            />,
        );

        await waitFor(() => expect(calls.geoJsonLayers).toHaveLength(1));
        expect(calls.geoJsonLayers[0].data).toBe(lineBoundary);
        expect(calls.polygons).toHaveLength(0);
    });

    it('draws nothing when the town has no boundary configured', async () => {
        render(
            <RequestDetailMap
                config={config}
                lat={40.7441}
                lng={-74.2915}
                mapLayers={[]}
                townshipBoundary={null}
            />,
        );

        await waitFor(() => expect(calls.markers).toHaveLength(1));
        expect(calls.polygons).toHaveLength(0);
        expect(calls.geoJsonLayers).toHaveLength(0);
    });
});
