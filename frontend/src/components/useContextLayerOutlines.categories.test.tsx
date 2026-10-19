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
        await waitFor(() => expect(result.current.layers.map(l => l.id)).toEqual([1, 3, 4]));
        // Same viewport: the outlines come from what was already fetched.
        expect(api.getPublicLayerOutlines).not.toHaveBeenCalled();
    });

    it('filters the staff map by the categories the layer is recorded on, not the resident ones', async () => {
        api.getContextLayers.mockResolvedValue([
            { ...polygon(9, ['potholes']), service_codes: [], min_zoom: 15, feature_count: 1 },
            { ...polygon(10, []), service_codes: ['tax'], min_zoom: 15, feature_count: 1 },
        ]);
        api.getContextLayerFeatures.mockResolvedValue({ type: 'FeatureCollection', features: [], zoom_in: false, limit: 1 });
        const mapRef = { current: fakeMap() as any };
        const { result } = renderHook(() => useContextLayerOutlines(mapRef, { current: null }, true, 'staff', ['graffiti']));
        await waitFor(() => expect(api.getContextLayerFeatures).toHaveBeenCalled());
        expect(result.current.layers.map(l => l.id)).toEqual([9]);
    });
});

/** A map whose viewport the test moves, and which fires its idle handlers on demand. */
function movableMap(box = { north: 40.01, south: 40.0, east: -74.0, west: -74.01 }, zoom = 17) {
    const idle: (() => void)[] = [];
    const map = {
        box, zoom,
        getBounds: () => map.box,
        getZoom: () => map.zoom,
        on: vi.fn((_e: string, h: () => void) => { idle.push(h); return () => {}; }),
        addGeoJsonLayer: vi.fn((_opts: any) => ({ remove: vi.fn() })),
        settle: () => idle.forEach(h => h()),
    };
    return map;
}

describe('useContextLayerOutlines speed', () => {
    beforeEach(() => {
        api.getMapLayers.mockResolvedValue([polygon(1, [])]);
    });

    it('fetches a margin around the screen and redraws small pans from it', async () => {
        const map = movableMap();
        renderHook(() => useContextLayerOutlines({ current: map as any }, { current: null }, true, 'public'));
        await waitFor(() => expect(api.getPublicLayerOutlines).toHaveBeenCalledTimes(1));
        const asked = api.getPublicLayerOutlines.mock.calls[0][1];
        expect(asked.north - asked.south).toBeCloseTo(0.015, 6);  // a quarter screen more each side

        map.box = { north: 40.012, south: 40.002, east: -73.998, west: -74.008 };  // within the margin
        map.settle();
        await new Promise(r => setTimeout(r, 150));
        expect(api.getPublicLayerOutlines).toHaveBeenCalledTimes(1);

        map.box = { north: 40.05, south: 40.04, east: -73.95, west: -73.96 };  // well outside it
        map.settle();
        await waitFor(() => expect(api.getPublicLayerOutlines).toHaveBeenCalledTimes(2));
    });

    it('falls back to just the screen when the margin holds too many features', async () => {
        api.getPublicLayerOutlines
            .mockResolvedValueOnce({ type: 'FeatureCollection', features: [], zoom_in: true, limit: 1 })
            .mockResolvedValueOnce({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: {}, properties: {} }], zoom_in: false, limit: 1 });
        const map = movableMap();
        const { result } = renderHook(() => useContextLayerOutlines({ current: map as any }, { current: null }, true, 'public'));
        await waitFor(() => expect(result.current.status[1]).toBe('shown'));
        const [wide, exact] = api.getPublicLayerOutlines.mock.calls.map(c => c[1]);
        expect(exact).toEqual(map.box);
        expect(wide.north).toBeGreaterThan(exact.north);
    });

    it("draws a report's own parcel stronger on the staff map, and resident outlines never take clicks", async () => {
        api.getContextLayers.mockResolvedValue([{ ...polygon(5, []), service_codes: [], min_zoom: 15, feature_count: 2 }]);
        api.getContextLayerFeatures.mockResolvedValue({ type: 'FeatureCollection', features: [], zoom_in: false, limit: 1 });
        const staff = movableMap();
        renderHook(() => useContextLayerOutlines({ current: staff as any }, { current: null }, true, 'staff', ['tax'],
            [{ layer_id: 5, feature_key: '12-4' }]));
        await waitFor(() => expect(staff.addGeoJsonLayer).toHaveBeenCalled());
        const style = staff.addGeoJsonLayer.mock.calls[0][0].style;
        const mine = style({ properties: { feature_key: '12-4' } });
        const other = style({ properties: { feature_key: '12-5' } });
        expect(mine.strokeWidth).toBeGreaterThan(other.strokeWidth);
        expect(mine.fillOpacity).toBeGreaterThan(other.fillOpacity);

        const resident = movableMap();
        renderHook(() => useContextLayerOutlines({ current: resident as any }, { current: null }, true, 'public'));
        await waitFor(() => expect(resident.addGeoJsonLayer).toHaveBeenCalled());
        const opts = resident.addGeoJsonLayer.mock.calls[0][0];
        expect(opts.style.clickable).toBe(false);
        expect(opts.onFeatureClick).toBeUndefined();
        expect(opts.style.strokeWidth).toBeGreaterThanOrEqual(2);
    });
});
