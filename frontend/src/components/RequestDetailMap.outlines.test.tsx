// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';

/**
 * The staff incident map shows the parcels recorded on that category.
 *
 * A report's parcel was listed as text in the incident view but never drawn on
 * its map, so staff could not see which lot it meant or what was next to it.
 * The map now draws the context layers that apply to the report's category,
 * with the report's own parcel stronger. The resident tracker passes nothing
 * and draws no parcels.
 */

const api = vi.hoisted(() => ({
    getMapLayers: vi.fn(),
    getContextLayers: vi.fn(),
    getPublicLayerOutlines: vi.fn(),
    getContextLayerFeatures: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));

const geoJsonLayers: any[] = [];
const fakeMap = {
    createPopup: () => ({ setContent: vi.fn(), openAt: vi.fn(), close: vi.fn() }),
    addMarker: () => ({ remove: vi.fn() }),
    addPolygon: () => ({ remove: vi.fn() }),
    addGeoJsonLayer: (options: any) => { geoJsonLayers.push(options); return { remove: vi.fn() }; },
    fitBounds: vi.fn(), setCenter: vi.fn(), setZoom: vi.fn(), panTo: vi.fn(),
    getBounds: () => ({ north: 40.01, south: 40.0, east: -74.0, west: -74.01 }),
    getZoom: () => 18,
    on: () => () => { },
    destroy: vi.fn(),
};

vi.mock('../maps', async () => {
    const actual = await vi.importActual<any>('../maps');
    return { ...actual, hasMapCredential: () => true, createMap: vi.fn(async () => fakeMap) };
});

import RequestDetailMap from './RequestDetailMap';

const config = { provider: 'google', apiKey: 'k' } as any;
const layer = (id: number, service_codes: string[]) => ({
    id, name: `Layer ${id}`, fill_color: '#b45309', stroke_color: '#b45309', fill_opacity: 0.1, stroke_width: 1,
    visible_on_map: true, service_codes, resident_service_codes: [], feature_count: 10, min_zoom: 15,
});

afterEach(() => { cleanup(); vi.clearAllMocks(); geoJsonLayers.length = 0; });

describe('incident map context outlines', () => {
    it("draws the layers recorded on the report's category, with its own parcel stronger", async () => {
        api.getContextLayers.mockResolvedValue([layer(7, ['TAX']), layer(8, ['TRASH'])]);
        api.getContextLayerFeatures.mockResolvedValue({ type: 'FeatureCollection', features: [], zoom_in: false, limit: 1 });
        render(
            <RequestDetailMap config={config} lat={40.005} lng={-74.005} mapLayers={[]}
                outlines={{ category: 'TAX', highlight: [{ layer_id: 7, feature_key: '12-4' }] }} />,
        );
        await waitFor(() => expect(api.getContextLayerFeatures).toHaveBeenCalled());
        expect([...new Set(api.getContextLayerFeatures.mock.calls.map(c => c[0]))]).toEqual([7]);
        await waitFor(() => expect(geoJsonLayers.some(o => typeof o.style === 'function')).toBe(true));
        const style = geoJsonLayers.find(o => typeof o.style === 'function').style;
        expect(style({ properties: { feature_key: '12-4' } }).strokeWidth)
            .toBeGreaterThan(style({ properties: { feature_key: '9-9' } }).strokeWidth);
    });

    it('the resident tracker, which passes no outlines, fetches none', async () => {
        render(<RequestDetailMap config={config} lat={40.005} lng={-74.005} mapLayers={[]} />);
        await new Promise(r => setTimeout(r, 300));
        expect(api.getContextLayers).not.toHaveBeenCalled();
        expect(api.getPublicLayerOutlines).not.toHaveBeenCalled();
    });
});
