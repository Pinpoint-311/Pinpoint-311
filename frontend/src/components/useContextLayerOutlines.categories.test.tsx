import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { renderHook, waitFor, cleanup } from '@testing-library/react';

const api = vi.hoisted(() => ({
    getMapLayers: vi.fn(),
    getContextLayers: vi.fn(),
    getPublicLayerOutlines: vi.fn(),
    getContextLayerFeatures: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));

import { layerAppliesToCategories, useContextLayerOutlines } from './useContextLayerOutlines';

/** Enough of a MapRenderer for the hook: a viewport at parcel zoom. */
function fakeMap() {
    return {
        getBounds: () => ({ north: 40.01, south: 40.0, east: -74.0, west: -74.01 }),
        getZoom: () => 17,
        on: vi.fn(() => () => {}),
        addGeoJsonLayer: vi.fn(() => ({ remove: vi.fn() })),
    };
}

const polygon = (id: number, resident_service_codes: string[] | null) => ({
    id, name: `Layer ${id}`, fill_color: '#fff', stroke_color: '#000', fill_opacity: 0.1, stroke_width: 1,
    geojson: { type: 'FeatureCollection', features: [] }, is_active: true, show_on_resident_portal: true,
    visible_on_map: true, feature_storage: 'table', resident_service_codes,
});

beforeEach(() => {
    api.getMapLayers.mockResolvedValue([
        polygon(1, []), polygon(2, ['potholes']), polygon(3, ['streetlights', 'graffiti']), polygon(4, null),
    ]);
    api.getPublicLayerOutlines.mockResolvedValue({ type: 'FeatureCollection', features: [], zoom_in: false, limit: 1 });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const requested = () => [...new Set(api.getPublicLayerOutlines.mock.calls.map(c => c[0]))].sort();

describe('layerAppliesToCategories', () => {
    it('treats an empty or missing list as every category, and null categories as no filter', () => {
        expect(layerAppliesToCategories({ resident_service_codes: [] }, ['potholes'])).toBe(true);
        expect(layerAppliesToCategories({ resident_service_codes: null }, ['potholes'])).toBe(true);
        expect(layerAppliesToCategories({ resident_service_codes: ['potholes'] }, null)).toBe(true);
        expect(layerAppliesToCategories({ resident_service_codes: ['potholes'] }, ['potholes', 'graffiti'])).toBe(true);
        expect(layerAppliesToCategories({ resident_service_codes: ['potholes'] }, ['graffiti'])).toBe(false);
        // Nothing chosen: only the layers that apply everywhere.
        expect(layerAppliesToCategories({ resident_service_codes: ['potholes'] }, [])).toBe(false);
    });
});

describe('useContextLayerOutlines category filter', () => {
    const run = (categories?: string[] | null) => {
        const mapRef = { current: fakeMap() as any };
        const popupRef = { current: null };
        return renderHook(({ c }) => useContextLayerOutlines(mapRef, popupRef, true, 'public', c),
            { initialProps: { c: categories } });
    };

    it('draws only the layers that apply to the category', async () => {
        const { result } = run(['potholes']);
        await waitFor(() => expect(requested()).toEqual([1, 2, 4]));
        expect(result.current.layers.map(l => l.id)).toEqual([1, 2, 4]);
    });

    it('draws every layer without a filter, and follows the categories as they change', async () => {
        const { result, rerender } = run(null);
        await waitFor(() => expect(requested()).toEqual([1, 2, 3, 4]));
        api.getPublicLayerOutlines.mockClear();
        rerender({ c: ['graffiti'] });
        await waitFor(() => expect(requested()).toEqual([1, 3, 4]));
        expect(result.current.layers.map(l => l.id)).toEqual([1, 3, 4]);
    });

    it('leaves the staff map alone', async () => {
        api.getContextLayers.mockResolvedValue([{ ...polygon(9, ['potholes']), min_zoom: 15, feature_count: 1 }]);
        api.getContextLayerFeatures.mockResolvedValue({ type: 'FeatureCollection', features: [], zoom_in: false, limit: 1 });
        const mapRef = { current: fakeMap() as any };
        const { result } = renderHook(() => useContextLayerOutlines(mapRef, { current: null }, true, 'staff', ['graffiti']));
        await waitFor(() => expect(api.getContextLayerFeatures).toHaveBeenCalled());
        expect(result.current.layers.map(l => l.id)).toEqual([9]);
    });
});
