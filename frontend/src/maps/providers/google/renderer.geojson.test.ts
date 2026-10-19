import { describe, it, expect, beforeEach } from 'vitest';
import { GoogleMapRenderer } from './renderer';

/**
 * A GeoJSON shape must not eat the click that places a pin.
 *
 * A google.maps.Data feature is clickable by default, and a click on it never
 * reaches the map's own click listener. Once resident parcel outlines were
 * drawn on the report form's map, tapping anywhere inside a parcel did nothing:
 * the pin could only be dropped on a road. Shapes are clickable only when the
 * caller asked for feature clicks.
 */

class FakeData {
    styler: ((feature: any) => any) | null = null;
    listeners: string[] = [];
    addGeoJson() { }
    setStyle(fn: (feature: any) => any) { this.styler = fn; }
    addListener(name: string) { this.listeners.push(name); return { remove() { } }; }
    setMap() { }
}

const created: FakeData[] = [];
const fakeFeature = {
    getGeometry: () => ({ getType: () => 'Polygon' }),
    forEachProperty: () => { },
};
const parcel = {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] } }],
};

beforeEach(() => {
    created.length = 0;
    (window as any).google = {
        maps: {
            Map: class { addListener() { return { remove() { } }; } },
            Data: class extends FakeData { constructor() { super(); created.push(this); } },
            event: { removeListener() { }, clearInstanceListeners() { } },
        },
    };
});

const renderer = () => new GoogleMapRenderer(document.createElement('div'), { center: { lat: 0, lng: 0 }, zoom: 15 });

describe('Google GeoJSON layers and map clicks', () => {
    it('a shape with no click handler lets the click through to the map', () => {
        renderer().addGeoJsonLayer({ data: parcel, style: { strokeColor: '#b45309' } });
        expect(created[0].styler!(fakeFeature).clickable).toBe(false);
        expect(created[0].listeners).not.toContain('click');
    });

    it('a shape with a click handler is clickable', () => {
        renderer().addGeoJsonLayer({ data: parcel, onFeatureClick: () => { } });
        expect(created[0].styler!(fakeFeature).clickable).toBe(true);
        expect(created[0].listeners).toContain('click');
    });

    it('an explicit style wins either way', () => {
        renderer().addGeoJsonLayer({ data: parcel, style: { clickable: false }, onFeatureClick: () => { } });
        expect(created[0].styler!(fakeFeature).clickable).toBe(false);
    });
});
