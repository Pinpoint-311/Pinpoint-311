import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * Feature clicks on an Esri GeoJSON layer.
 *
 * The road corridor editor (RoadCorridorMap.tsx) hands the *same*
 * FeatureCollection object to addGeoJsonLayer twice: once for the invisible
 * wide buffer and once for the centreline, and only the centreline carries
 * onFeatureClick. On Esri, clicking a road did nothing at all -- no stretch
 * selected, so no trim handles, no exclude button, nothing. Everything else on
 * the map (the canvas overlay, the boundary, fitBounds) was working, which is
 * why it looked like a missing layer method rather than what it was.
 *
 * Two things conspired, both measured against the real ArcGIS SDK 4.29 in a
 * browser:
 *
 *  - the adapter wrote its synthetic style key back onto the caller's own
 *    feature properties, so the second layer's idea of "this feature's
 *    properties" already contained the first layer's style key; and
 *  - GeoJSONLayer renames any field whose name starts with an underscore or a
 *    digit, so `__ppStyle` comes back off a clicked graphic as `F__ppStyle`.
 *    (The renderer still worked, because the SDK rewrites the renderer's field
 *    name the same way -- only code reading attributes by name was affected.)
 *
 * Matching a clicked graphic by whole-property equality could not survive
 * either, so the match now goes through an index stamped on the copy that is
 * served to the SDK. The fakes below reproduce the SDK's field renaming and its
 * copying of attributes; every assertion is about what the adapter does.
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

/** url -> the GeoJSON text the adapter serialised into the object URL. */
const servedByUrl = new Map<string, string>();

class FakeGeoJSONLayer {
    declaredClass = 'esri.layers.GeoJSONLayer';
    visible = true;
    renderer: any;
    constructor(public props: any) { this.renderer = props.renderer; }
    destroy() {}

    /** The features this layer was actually given, as served. */
    served(): any[] {
        return JSON.parse(servedByUrl.get(this.props.url) ?? '{"features":[]}').features;
    }

    /**
     * What `view.hitTest` hands back for one of this layer's features: a fresh
     * graphic whose attributes are a *copy* of the served properties, with the
     * SDK's own OBJECTID and its field renaming applied.
     */
    graphicFor(index: number): any {
        const feature = this.served()[index];
        const attributes: Record<string, unknown> = { __OBJECTID: index + 1 };
        for (const [key, value] of Object.entries(feature.properties ?? {})) {
            attributes[/^[A-Za-z]/.test(key) ? key : `F${key}`] = value;
        }
        return { layer: this, attributes };
    }
}

const clickHandlers: ((event: any) => void)[] = [];
let hitGraphic: any = null;

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
    popupEnabled: boolean;
    constructor(props: any) {
        this.map = props.map;
        this.container = props.container ?? { style: {} };
        this.center = props.center;
        this.zoom = props.zoom;
        this.popupEnabled = props.popupEnabled ?? true;
    }
    on(event: string, handler: (e: any) => void) {
        if (event === 'click') clickHandlers.push(handler);
        return { remove: vi.fn() };
    }
    when(resolve: () => void) { resolve(); return Promise.resolve(); }
    hitTest() { return Promise.resolve({ results: hitGraphic ? [{ graphic: hitGraphic }] : [] }); }
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
    GraphicsLayer: class { constructor(public props: any) {} destroy() {} },
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
import { GeoFeature, VectorStyle } from '../../types';

/** Two road centrelines, the shape /gis/roads/geometry returns. */
function roadCollection() {
    return {
        type: 'FeatureCollection',
        features: [
            {
                type: 'Feature',
                properties: { feature_id: 'NJ-1', name: 'Grand Ave' },
                geometry: { type: 'LineString', coordinates: [[-74.30, 40.75], [-74.28, 40.74]] },
            },
            {
                type: 'Feature',
                properties: { feature_id: 'NJ-2', name: 'Grand Ave' },
                geometry: { type: 'LineString', coordinates: [[-74.28, 40.74], [-74.26, 40.73]] },
            },
        ],
    };
}

function build() {
    const container = document.createElement('div');
    const renderer = new EsriMapRenderer(container, {
        center: { lat: 40.74, lng: -74.28 },
        zoom: 14,
    });
    return { renderer, map: (renderer as any).view.map as FakeMap };
}

/** Fire the SDK's click event with `graphic` under the pointer. */
async function clickGraphic(graphic: any) {
    hitGraphic = graphic;
    for (const handler of clickHandlers) {
        handler({ mapPoint: { latitude: 40.74, longitude: -74.28 }, x: 10, y: 10 });
    }
    // installInteraction resolves view.hitTest() before dispatching.
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
}

/** A Blob that keeps its text readable synchronously, so the object URL the
 *  adapter serves the SDK can be inspected. */
class TextBlob {
    text: string;
    constructor(parts: string[], public options?: unknown) { this.text = parts.join(''); }
}

beforeEach(() => {
    clickHandlers.length = 0;
    hitGraphic = null;
    servedByUrl.clear();
    let n = 0;
    vi.stubGlobal('Blob', TextBlob);
    vi.stubGlobal('URL', Object.assign(URL, {
        createObjectURL: (blob: TextBlob) => {
            const url = `blob:test/${n++}`;
            servedByUrl.set(url, blob.text);
            return url;
        },
        revokeObjectURL: () => undefined,
    }));
});

describe('Esri GeoJSON layer feature clicks', () => {
    it('reports clicks on a layer built from a FeatureCollection another layer already used', async () => {
        const { renderer, map } = build();
        const collection = roadCollection();

        const style = (feature: GeoFeature): VectorStyle => ({
            strokeColor: feature.properties.feature_id === 'NJ-2' ? '#64748b' : '#ef4444',
            strokeOpacity: 0,
        });

        // Exactly what RoadCorridorMap does: the buffer first, then the
        // clickable centreline, both over the same object.
        renderer.addGeoJsonLayer({ data: collection, style });

        const clicked: GeoFeature[] = [];
        renderer.addGeoJsonLayer({
            data: collection,
            style,
            onFeatureClick: feature => clicked.push(feature),
        });

        const centreline = map.layers.items[1] as FakeGeoJSONLayer;
        await clickGraphic(centreline.graphicFor(1));

        expect(clicked).toHaveLength(1);
        expect(clicked[0].properties.feature_id).toBe('NJ-2');
    });

    it('leaves the caller\'s GeoJSON unmodified', () => {
        const { renderer } = build();
        const collection = roadCollection();
        const before = JSON.parse(JSON.stringify(collection));

        renderer.addGeoJsonLayer({ data: collection, style: () => ({ strokeColor: '#ef4444' }) });

        expect(collection).toEqual(before);
    });

    it('matches a feature whose properties contain a nested value', async () => {
        const { renderer, map } = build();
        const collection = {
            type: 'FeatureCollection',
            features: [{
                type: 'Feature',
                // A nested value never compares equal across the SDK round trip,
                // which is what whole-property matching relied on.
                properties: { feature_id: 'NJ-9', tags: ['county', 'paved'] },
                geometry: { type: 'LineString', coordinates: [[-74.30, 40.75], [-74.28, 40.74]] },
            }],
        };

        const clicked: GeoFeature[] = [];
        renderer.addGeoJsonLayer({
            data: collection,
            onFeatureClick: feature => clicked.push(feature),
        });

        const layer = map.layers.items[0] as FakeGeoJSONLayer;
        await clickGraphic(layer.graphicFor(0));

        expect(clicked.map(f => f.properties.feature_id)).toEqual(['NJ-9']);
    });
});
