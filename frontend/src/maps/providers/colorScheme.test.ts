import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * `MapInitOptions.colorScheme: 'dark'` has to reach every vendor.
 *
 * The bias heatmap asked for a dark base map by passing Google's style array
 * through `vendorOptions`, which by definition only Google could read. A town
 * on Esri, Azure or Apple got the panel's dark chrome wrapped around a bright
 * white street map, with heat gradients mixed for a dark base washing out over
 * it -- and nothing anywhere said the request had been dropped.
 *
 * Each case asserts the *vendor* option the adapter set, so a provider that
 * quietly ignores colorScheme fails here rather than on somebody's screen.
 */

// --- Esri -----------------------------------------------------------------

const esriViews: any[] = [];
const esriMods: any = {
    esriConfig: { apiKey: null, request: { trustedServers: [], corsEnabledServers: [] } },
    Map: class { basemap: any; layers = { items: [] as any[] }; constructor(p: any) { this.basemap = p?.basemap; } add() {} remove() {} },
    Basemap: class { constructor(public props: any) {} },
    MapView: class {
        map: any; container: any; ui = { add: vi.fn(), remove: vi.fn(), components: [] };
        width = 400; height = 300; extent = null; stationary = true;
        constructor(public props: any) { this.map = props.map; this.container = props.container; esriViews.push(this); }
        on() { return { remove: vi.fn() }; }
        when(resolve: () => void) { resolve(); return Promise.resolve(); }
        hitTest() { return Promise.resolve({ results: [] }); }
        goTo() { return Promise.resolve(); }
        destroy() {}
    },
    Graphic: class { constructor(p: any) { Object.assign(this, p); } },
    GraphicsLayer: class { constructor(public props: any) {} destroy() {} },
    FeatureLayer: class { constructor(public props: any) {} destroy() {} },
    GeoJSONLayer: class { constructor(public props: any) {} destroy() {} },
    TileLayer: class { constructor(public props: any) {} },
    VectorTileLayer: class { constructor(public props: any) {} },
    Point: class { constructor(p: any) { Object.assign(this, p); } },
    Polygon: class { constructor(p: any) { Object.assign(this, p); } },
    Extent: class { constructor(p: any) { Object.assign(this, p); } expand() { return this; } },
    SpatialReference: { WGS84: { wkid: 4326 } },
    webMercatorUtils: { webMercatorToGeographic: (p: any) => p },
    SimpleMarkerSymbol: class { constructor(public p: any) {} },
    PictureMarkerSymbol: class { constructor(public p: any) {} },
    TextSymbol: class { constructor(public p: any) {} },
    SimpleFillSymbol: class { constructor(public p: any) {} },
    SimpleLineSymbol: class { constructor(public p: any) {} },
    SimpleRenderer: class { constructor(public p: any) {} },
    UniqueValueRenderer: class { constructor(public p: any) {} },
    ClassBreaksRenderer: class { constructor(public p: any) {} },
    reactiveUtils: { watch: () => ({ remove: vi.fn() }) },
    Zoom: class { constructor(public p: any) {} },
    Fullscreen: class { constructor(public p: any) {} },
    Compass: class { constructor(public p: any) {} },
};
vi.mock('./esri/loader', () => ({ esriModules: () => esriMods, loadEsri: async () => esriMods }));

// --- Azure ----------------------------------------------------------------

const azureMaps: any[] = [];
const atlas: any = {
    Map: class {
        constructor(public container: any, public options: any) { azureMaps.push(this); }
        events = { add: () => {} };
        controls = { add: () => {} };
        getCanvasContainer() { return document.createElement('div'); }
        getCanvas() { return document.createElement('canvas'); }
    },
    AuthenticationType: { subscriptionKey: 'subscriptionKey' },
    control: {
        ZoomControl: class {}, CompassControl: class {}, StyleControl: class {}, PitchControl: class {},
    },
    ControlPosition: {},
};
vi.mock('./azure/sdk', () => ({ atlasSdk: () => atlas, loadAzureMaps: async () => undefined }));

// --- Apple ----------------------------------------------------------------

const appleMaps: any[] = [];
const mapkit: any = {
    Map: Object.assign(
        class {
            center: any;
            region: any;
            constructor(public container: any, public options: any) {
                this.center = options.center;
                appleMaps.push(this);
            }
            addEventListener() {}
        },
        { ColorSchemes: { Light: 'mk-light', Dark: 'mk-dark' }, MapTypes: { Standard: 'std', Satellite: 'sat', Hybrid: 'hyb' } },
    ),
    Coordinate: class { constructor(public latitude: number, public longitude: number) {} },
    CoordinateRegion: class { constructor(public c: any, public s: any) {} },
    CoordinateSpan: class { constructor(public la: number, public lo: number) {} },
    FeatureVisibility: { Visible: 'v', Hidden: 'h' },
};
vi.mock('./apple/loader', () => ({ appleMapKit: () => mapkit, loadAppleMapKit: async () => mapkit }));

import { EsriMapRenderer } from './esri/renderer';
import { AzureMapRenderer } from './azure/renderer';
import { AppleMapRenderer } from './apple/renderer';
import { GoogleMapRenderer } from './google/renderer';

const div = () => document.createElement('div');
const base = { center: { lat: 40.74, lng: -74.28 }, zoom: 13 } as const;

let googleMaps: any[] = [];

beforeEach(() => {
    esriViews.length = 0;
    azureMaps.length = 0;
    appleMaps.length = 0;
    googleMaps = [];
    (window as any).google = {
        maps: {
            Map: class { constructor(public container: any, public options: any) { googleMaps.push(this); } addListener() { return { remove() {} }; } },
            Data: class { setStyle() {} addListener() { return { remove() {} }; } addGeoJson() {} setMap() {} },
            event: { removeListener() {}, clearInstanceListeners() {} },
            MapTypeControlStyle: { HORIZONTAL_BAR: 1 },
        },
    };
});

describe('colorScheme reaches every map provider', () => {
    it('Google swaps in a dark style array', () => {
        new GoogleMapRenderer(div(), { ...base, colorScheme: 'dark' });
        const styles = googleMaps[0].options.styles as any[];
        expect(Array.isArray(styles)).toBe(true);
        expect(styles.length).toBeGreaterThan(0);

        new GoogleMapRenderer(div(), { ...base });
        expect(googleMaps[1].options.styles).toBeUndefined();
    });

    it('Esri swaps in a dark basemap', () => {
        new EsriMapRenderer(div(), { ...base, colorScheme: 'dark' });
        const dark = esriViews[0].props.map.basemap;

        new EsriMapRenderer(div(), { ...base });
        const light = esriViews[1].props.map.basemap;

        expect(dark).not.toEqual(light);
        expect(String(dark)).toMatch(/dark/);
    });

    it('Esri still lets the town\'s own basemap win', () => {
        new EsriMapRenderer(div(), { ...base, colorScheme: 'dark', styleId: 'a-town-basemap' });
        expect(esriViews[0].props.map.basemap).toBe('a-town-basemap');
    });

    it('Azure swaps in a dark style', () => {
        new AzureMapRenderer(div(), 'key', {}, { ...base, colorScheme: 'dark' });
        const dark = azureMaps[0].options.style;

        new AzureMapRenderer(div(), 'key', {}, { ...base });
        expect(dark).not.toBe(azureMaps[1].options.style);
        expect(String(dark)).toMatch(/dark/);
    });

    it('Apple asks MapKit for its dark colour scheme', () => {
        new AppleMapRenderer(div(), { ...base, colorScheme: 'dark' });
        expect(appleMaps[0].options.colorScheme).toBe('mk-dark');

        new AppleMapRenderer(div(), { ...base });
        expect(appleMaps[1].options.colorScheme).toBeUndefined();
    });
});
