import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, waitFor, cleanup } from '@testing-library/react';

const api = vi.hoisted(() => ({
    getMapLayers: vi.fn(),
    getContextLayers: vi.fn(),
    getContextLayerFeatures: vi.fn(),
    getPublicLayerOutlines: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));

import { useContextLayerOutlines } from './useContextLayerOutlines';

const base = { fill_color: '#f59e0b', stroke_color: '#b45309', fill_opacity: 0.3, stroke_width: 2, is_active: true, show_on_resident_portal: true, geojson: { type: 'FeatureCollection', features: [] } };

function fakeMap(zoom = 16) {
    return {
        getBounds: () => ({ west: -74.01, south: 40.0, east: -74.0, north: 40.01 }),
        getZoom: () => zoom,
        on: vi.fn(() => () => {}),
        addGeoJsonLayer: vi.fn(() => ({ remove: vi.fn(), setStyle: vi.fn(), setVisible: vi.fn() })),
    };
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('resident map outlines', () => {
    it('asks the public route for resident-visible polygon layers only, and draws them plain', async () => {
        // The public list holds only what the admin put on the portal.
        api.getMapLayers.mockResolvedValue([
            { ...base, id: 1, name: 'Tax Parcels', layer_type: 'polygon', feature_storage: 'table', visible_on_map: true },
            { ...base, id: 2, name: 'Hydrants', layer_type: 'point', feature_storage: 'inline', visible_on_map: true },
            { ...base, id: 3, name: 'Hidden zones', layer_type: 'polygon', feature_storage: 'table', visible_on_map: false },
        ]);
        api.getPublicLayerOutlines.mockResolvedValue({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: {} }], zoom_in: false, limit: 500 });
        const map = fakeMap();
        renderHook(() => useContextLayerOutlines({ current: map as any }, { current: null }, true, 'public'));
        await waitFor(() => expect(map.addGeoJsonLayer).toHaveBeenCalledTimes(1));
        expect(api.getPublicLayerOutlines).toHaveBeenCalledTimes(1);
        expect(api.getPublicLayerOutlines.mock.calls[0][0]).toBe(1);
        expect(api.getContextLayers).not.toHaveBeenCalled();
        expect(api.getContextLayerFeatures).not.toHaveBeenCalled();
        const opts = (map.addGeoJsonLayer.mock.calls[0] as any[])[0];
        expect(opts.onFeatureClick).toBeUndefined();              // no popup with attributes
        // Readable over satellite imagery, but still faint enough not to look
        // like a report, and never in the way of the pin.
        expect(opts.style.strokeWidth).toBe(2);
        expect(opts.style.fillOpacity).toBeLessThan(0.1);
        expect(opts.style.clickable).toBe(false);
    });

    it('asks nothing below parcel zoom', async () => {
        api.getMapLayers.mockResolvedValue([{ ...base, id: 1, name: 'Tax Parcels', feature_storage: 'table', visible_on_map: true }]);
        const map = fakeMap(12);
        const { result } = renderHook(() => useContextLayerOutlines({ current: map as any }, { current: null }, true, 'public'));
        await waitFor(() => expect(result.current.status[1]).toBe('zoom_in'));
        expect(api.getPublicLayerOutlines).not.toHaveBeenCalled();
    });

    it('does nothing when off', async () => {
        renderHook(() => useContextLayerOutlines({ current: fakeMap() as any }, { current: null }, true, 'off'));
        await new Promise(r => setTimeout(r, 300));
        expect(api.getMapLayers).not.toHaveBeenCalled();
        expect(api.getContextLayers).not.toHaveBeenCalled();
    });

    it('staff mode uses the staff routes', async () => {
        api.getContextLayers.mockResolvedValue([{ ...base, id: 5, name: 'Parcels', visible_on_map: true, feature_count: 10, min_zoom: 15 }]);
        api.getContextLayerFeatures.mockResolvedValue({ type: 'FeatureCollection', features: [], zoom_in: false, limit: 500 });
        const map = fakeMap();
        renderHook(() => useContextLayerOutlines({ current: map as any }, { current: null }, true, 'staff'));
        await waitFor(() => expect(api.getContextLayerFeatures).toHaveBeenCalled());
        expect(api.getMapLayers).not.toHaveBeenCalled();
        expect(api.getPublicLayerOutlines).not.toHaveBeenCalled();
    });
});

describe('the Community Requests map', () => {
    it('keeps point asset layers off and turns resident outlines on', async () => {
        const src = (await import('../pages/ResidentPortal.tsx?raw')).default as string;
        const map = src.slice(src.indexOf('<StaffDashboardMap'), src.indexOf('/>', src.indexOf('<StaffDashboardMap')));
        expect(map).toContain('mapLayers={[]}');
        expect(map).toContain('residentOutlines');
        expect(map).not.toContain('operationalFilters');
    });
});
