import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * Markers and overlays reach the map's layer collection.
 *
 * On a live Esri deployment the basemap drew and nothing else did -- no request
 * pin, no asset markers, no boundary overlay -- and the first hypothesis was
 * that `addMarker`'s default GraphicsLayer was built but never added to
 * `view.map`. It was not that: the real cause was the edge Content-Security
 * Policy, whose `connect-src` did not allow the `data:` URLs the SDK fetches for
 * a PictureMarkerSymbol or the `blob:` URLs a GeoJSONLayer re-reads itself
 * through (see backend/tests/test_map_csp.py).
 *
 * That makes this file worth having twice over: it pins the invariant that was
 * suspected, so the same wrong turn does not have to be taken again, and it
 * fails loudly if a later refactor really does leave a layer detached -- a
 * failure whose only symptom on screen is an empty map.
 *
 * The fakes here stand in for the ArcGIS classes rather than for our own code:
 * every assertion is about what the renderer did to the map.
 */

class FakeCollection {
    items: any[] = [];
    get length() { return this.items.length; }
    add(item: any) { this.items.push(item); }
    remove(item: any) { this.items = this.items.filter(i => i !== item); }
    addMany(items: any[]) { this.items.push(...items); }
    removeMany(items: any[]) { this.items = this.items.filter(i => !items.includes(i)); }
    removeAll() { this.items = []; }
    map(fn: (i: any) => any) { return this.items.map(fn); }
}

class FakeMap {
    layers = new FakeCollection();
    basemap: any;
    constructor(props: any) { this.basemap = props?.basemap; }
    add(layer: any) { this.layers.add(layer); }
    remove(layer: any) { this.layers.remove(layer); }
}

class FakeGraphicsLayer {
    declaredClass = 'esri.layers.GraphicsLayer';
    graphics = new FakeCollection();
    visible = true;
    constructor(public props: any) {}
    add(g: any) { this.graphics.add(g); }
    addMany(g: any[]) { this.graphics.addMany(g); }
    removeMany(g: any[]) { this.graphics.removeMany(g); }
    removeAll() { this.graphics.removeAll(); }
    destroy() {}
}

class FakeGeoJSONLayer {
    declaredClass = 'esri.layers.GeoJSONLayer';
    visible = true;
    constructor(public props: any) {}
    destroy() {}
}

const readyCallbacks: (() => void)[] = [];

class FakeMapView {
    map: FakeMap;
    container: any;
    ui = { add: vi.fn(), remove: vi.fn(), components: [] as any[] };
    center: any;
    zoom: number;
    extent: any = null;
    width = 400;
    height = 300;
    stationary = true;
    props: any;
    popupEnabled: boolean;
    constructor(props: any) {
        this.props = props;
        this.map = props.map;
        this.container = props.container ?? { style: {} };
        this.center = props.center;
        this.zoom = props.zoom;
        this.popupEnabled = props.popupEnabled ?? true;
    }
    on() { return { remove: vi.fn() }; }
    when(resolve: () => void) { readyCallbacks.push(resolve); return Promise.resolve(); }
    hitTest() { return Promise.resolve({ results: [] }); }
    goTo() { return Promise.resolve(); }
    toMap() { return null; }
    destroy() {}
}

const symbol = (kind: string) => class {
    kind = kind;
    constructor(public props: any) {}
};

const mods: any = {
    esriConfig: { apiKey: null, request: { trustedServers: [], corsEnabledServers: [] } },
    Map: FakeMap,
    Basemap: class { constructor(public props: any) {} },
    MapView: FakeMapView,
    Graphic: class { constructor(public props: any) { Object.assign(this, props); } },
    GraphicsLayer: FakeGraphicsLayer,
    FeatureLayer: class { constructor(public props: any) {} destroy() {} },
    GeoJSONLayer: FakeGeoJSONLayer,
    TileLayer: class { constructor(public props: any) {} },
    VectorTileLayer: class { constructor(public props: any) {} },
    Point: class { constructor(public props: any) { Object.assign(this, props); } },
    Polygon: class { constructor(public props: any) { Object.assign(this, props); } },
    Extent: class {
        constructor(public props: any) { Object.assign(this, props); }
        expand() { return this; }
    },
    SpatialReference: { WGS84: { wkid: 4326 } },
    webMercatorUtils: { webMercatorToGeographic: (p: any) => p },
    SimpleMarkerSymbol: symbol('simple-marker'),
    PictureMarkerSymbol: symbol('picture-marker'),
    TextSymbol: symbol('text'),
    SimpleFillSymbol: symbol('fill'),
    SimpleLineSymbol: symbol('line'),
    SimpleRenderer: class { constructor(public props: any) {} },
    UniqueValueRenderer: class { constructor(public props: any) {} },
    ClassBreaksRenderer: class { constructor(public props: any) {} },
    reactiveUtils: { watch: () => ({ remove: vi.fn() }) },
    Zoom: class { constructor(public props: any) {} },
    Fullscreen: class { constructor(public props: any) {} },
    Compass: class { constructor(public props: any) {} },
};

vi.mock('./loader', () => ({
    esriModules: () => mods,
    loadEsri: async () => mods,
}));

import { EsriMapRenderer } from './renderer';
import { locationPinIcon, assetIcon } from '../../markerIcons';

function build() {
    readyCallbacks.length = 0;
    const container = document.createElement('div');
    const renderer = new EsriMapRenderer(container, {
        center: { lat: 40.7441, lng: -74.2915 },
        zoom: 18,
    });
    // The renderer defers camera work until view.when resolves; layer work is
    // not deferred, but run the queue so the object is in its normal state.
    readyCallbacks.forEach(fn => fn());
    const map = (renderer as any).view.map as FakeMap;
    return { renderer, map };
}

/** The GraphicsLayer instances currently in the map's layer collection. */
const graphicsLayers = (map: FakeMap) =>
    map.layers.items.filter(l => l instanceof FakeGraphicsLayer) as FakeGraphicsLayer[];

/** One real feature: the layer builder groups by geometry kind, so an empty
 *  collection legitimately produces no layer at all. */
const outline = {
    type: 'FeatureCollection',
    features: [{
        type: 'Feature',
        properties: {},
        geometry: {
            type: 'Polygon',
            coordinates: [[[-74.30, 40.75], [-74.28, 40.75], [-74.28, 40.73], [-74.30, 40.75]]],
        },
    }],
};

beforeEach(() => {
    readyCallbacks.length = 0;
    // jsdom has no object-URL implementation; the adapter's use of one is the
    // behaviour under test, so stand one up rather than working around it.
    if (!URL.createObjectURL) {
        vi.stubGlobal('URL', Object.assign(URL, {
            createObjectURL: () => `blob:test/${Math.random().toString(36).slice(2)}`,
            revokeObjectURL: () => undefined,
        }));
    }
});

describe('EsriMapRenderer marker layers', () => {
    it('attaches the default marker layer to the map, not just to itself', async () => {
        const { renderer, map } = build();
        expect(graphicsLayers(map)).toHaveLength(0);

        renderer.addMarker({ position: { lat: 40.7441, lng: -74.2915 }, icon: locationPinIcon('#ef4444') });

        // The whole failure mode this guards: a layer that exists, holds the
        // graphic, and was never handed to the map, so nothing is ever drawn.
        const layers = graphicsLayers(map);
        expect(layers).toHaveLength(1);
        expect(layers[0].graphics.length).toBe(1);
    });

    it('reuses one default layer across markers instead of one layer each', async () => {
        const { renderer, map } = build();
        renderer.addMarker({ position: { lat: 40.74, lng: -74.29 }, icon: assetIcon('#22c55e') });
        renderer.addMarker({ position: { lat: 40.75, lng: -74.28 }, icon: assetIcon('#22c55e') });

        const layers = graphicsLayers(map);
        expect(layers).toHaveLength(1);
        expect(layers[0].graphics.length).toBe(2);
    });

    it('draws a marker built by createMarkerLayer through an attached layer too', async () => {
        const { renderer, map } = build();
        const layer = renderer.createMarkerLayer();
        expect(graphicsLayers(map)).toHaveLength(1);

        layer.setMarkers([
            { position: { lat: 40.74, lng: -74.29 } },
            { position: { lat: 40.75, lng: -74.28 } },
        ]);
        expect(graphicsLayers(map)[0].graphics.length).toBe(2);
    });

    it('renders every marker icon as a picture symbol, the shared-glyph contract', async () => {
        const { renderer, map } = build();
        renderer.addMarker({ position: { lat: 40.7441, lng: -74.2915 }, icon: locationPinIcon('#ef4444') });

        const graphic: any = graphicsLayers(map)[0].graphics.items[0];
        // markerIcons.ts returns `image` for everything on purpose, so that the
        // same pin is identical pixels on every provider. A provider-native
        // vector symbol here would silently reintroduce per-vendor pins.
        expect(graphic.symbol.kind).toBe('picture-marker');
        expect(graphic.symbol.props.url).toMatch(/^data:image\/svg\+xml/);
    });

    it('adds a GeoJSON overlay to the map, sourced from a blob: URL', async () => {
        const { renderer, map } = build();
        renderer.addGeoJsonLayer({ data: outline, style: { fillColor: '#6366f1', strokeColor: '#6366f1' } });

        const layers = map.layers.items.filter(l => l instanceof FakeGeoJSONLayer) as FakeGeoJSONLayer[];
        expect(layers).toHaveLength(1);

        // Named here because it is the reason overlays vanished on a live
        // deployment: the SDK re-reads this URL with fetch, so the edge policy's
        // connect-src has to allow blob: or the layer never loads. It is not an
        // implementation detail this adapter is free to change quietly.
        expect(layers[0].props.url).toMatch(/^blob:/);
    });

    it('takes its layers back off the map when a marker layer is removed', async () => {
        const { renderer, map } = build();
        const layer = renderer.createMarkerLayer();
        layer.addMarker({ position: { lat: 40.74, lng: -74.29 } });
        expect(graphicsLayers(map)).toHaveLength(1);

        layer.remove();
        expect(graphicsLayers(map)).toHaveLength(0);
    });

    it('draws the township outline handed to addPolygon', async () => {
        const { renderer, map } = build();
        renderer.addPolygon({
            paths: [[
                { lat: 40.75, lng: -74.30 },
                { lat: 40.75, lng: -74.28 },
                { lat: 40.73, lng: -74.28 },
                { lat: 40.75, lng: -74.30 },
            ]],
            style: { fillColor: '#6366f1', clickable: false },
        });

        const layers = graphicsLayers(map);
        expect(layers).toHaveLength(1);
        expect(layers[0].graphics.length).toBe(1);
    });

    it('leaves nothing attached after destroy', async () => {
        const { renderer, map } = build();
        renderer.addMarker({ position: { lat: 40.74, lng: -74.29 } });
        renderer.addGeoJsonLayer({ data: outline });
        expect(map.layers.length).toBeGreaterThan(0);

        renderer.destroy();
        expect(map.layers.length).toBe(0);
    });
});

describe('the view does not run its own click-to-popup behaviour', () => {
    /**
     * Every popup in this app is opened explicitly, from a marker's onClick.
     * Leave ArcGIS's own click handling on and it runs for the same click,
     * finds no popupTemplate on any layer (they are all created with
     * popupEnabled: false) and closes the popup we just opened. Markers then
     * look correct and do nothing when clicked -- which is what the live Esri
     * deployment did, on request pins and town asset pins alike.
     *
     * Measured against demo.pinpoint311.org: opening a popup from inside a
     * click renders nothing while this is true -- immediately or deferred a
     * tick -- and renders as soon as it is false.
     */
    it('turns the view popup off, so an app-opened popup survives the click', () => {
        const { renderer } = build();
        expect((renderer as any).view.props.popupEnabled).toBe(false);
    });
});
