// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';

/**
 * The report form's map shows a resident the parcels or zones that matter to
 * the category they are reporting in: the polygon layers an admin put on the
 * portal for that category (or for every category), from the public
 * geometry-only route. Nothing for a layer scoped to other categories, and
 * nothing at all until a category is given.
 */

const fake = vi.hoisted(() => {
    // Any method the picker calls on the map answers with a harmless stub; the
    // few the outline hook reads answer with a viewport at parcel zoom.
    const stub: any = new Proxy(function () { /* noop */ }, {
        get: (_t, key) => (key === 'then' ? undefined : stub),
        apply: () => stub,
    });
    const map = new Proxy({
        getBounds: () => ({ north: 40.01, south: 40.0, east: -74.0, west: -74.01 }),
        getZoom: () => 17,
        on: () => () => { /* off */ },
        addGeoJsonLayer: () => ({ remove: () => { /* gone */ } }),
        destroy: () => { /* gone */ },
    } as Record<string, unknown>, {
        get: (t, key) => (key in t ? t[key as string] : key === 'then' ? undefined : stub),
    });
    return { map };
});

vi.mock('../maps', async () => {
    const actual = await vi.importActual<any>('../maps');
    return {
        ...actual,
        hasMapCredential: () => true,
        createMap: vi.fn(async () => fake.map),
        createGeocoder: vi.fn(async () => null),
    };
});

const api = vi.hoisted(() => ({
    getMapLayers: vi.fn(),
    getPublicLayerOutlines: vi.fn(),
    geocodeAddress: vi.fn(async () => null),
    reverseGeocode: vi.fn(async () => null),
}));
vi.mock('../services/api', () => ({ api, default: api }));

import LocationPicker from './LocationPicker';

const polygon = (id: number, resident_service_codes: string[] | null) => ({
    id, name: `Springfield layer ${id}`, fill_color: '#fff', stroke_color: '#000', fill_opacity: 0.1,
    stroke_width: 1, geojson: { type: 'FeatureCollection', features: [] }, is_active: true,
    show_on_resident_portal: true, visible_on_map: true, feature_storage: 'table', resident_service_codes,
});

beforeEach(() => {
    api.getMapLayers.mockResolvedValue([
        polygon(1, []), polygon(2, ['potholes']), polygon(3, ['streetlights']),
        // A point layer from the same list is never an outline.
        { ...polygon(4, []), feature_storage: 'inline', layer_type: 'point' },
    ]);
    api.getPublicLayerOutlines.mockResolvedValue({ type: 'FeatureCollection', features: [], zoom_in: false, limit: 1 });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const requested = () => [...new Set(api.getPublicLayerOutlines.mock.calls.map(c => c[0]))].sort();

describe('report form outlines', () => {
    it('requests outlines only for the layers that apply to the chosen category', async () => {
        render(<LocationPicker config={{ provider: 'google', apiKey: 'k' } as any} onChange={() => {}} outlineCategory="potholes" />);
        await waitFor(() => expect(requested()).toEqual([1, 2]));
    });

    it('draws no outlines without a category', async () => {
        render(<LocationPicker config={{ provider: 'google', apiKey: 'k' } as any} onChange={() => {}} />);
        await new Promise(r => setTimeout(r, 400));
        expect(api.getMapLayers).not.toHaveBeenCalled();
        expect(api.getPublicLayerOutlines).not.toHaveBeenCalled();
    });
});
