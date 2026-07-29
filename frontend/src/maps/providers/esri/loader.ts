/**
 * Guarded CDN loader for the ArcGIS Maps SDK for JavaScript.
 *
 * The @arcgis/core npm package is enormous (tens of MB unpacked, and its
 * lazily-imported internals defeat naive tree-shaking). Pinpoint is a 311 app
 * that most towns will run on Google or MapLibre, so paying that bundle cost
 * for everyone — or even paying a large chunk cost for Esri towns — is not
 * worth it. Loading the SDK's AMD build from js.arcgis.com keeps *zero* Esri
 * bytes in our own output: the only thing shipped is this adapter.
 *
 * Same single-inclusion contract as src/utils/googleMaps.ts: the SDK must be
 * put on the page exactly once no matter how many maps mount, so everything
 * funnels through one cached promise.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

const DEFAULT_VERSION = '4.31';
const SCRIPT_MARKER = 'data-arcgis-sdk';
const CSS_MARKER = 'data-arcgis-css';

/**
 * Every SDK class this adapter can possibly need, resolved up front in a single
 * AMD require. It has to be up front because MapProviderFactory.createRenderer
 * is synchronous — see the comment on EsriMapRenderer's constructor.
 */
export interface EsriModules {
    esriConfig: any;
    Map: any;
    Basemap: any;
    MapView: any;
    Graphic: any;
    GraphicsLayer: any;
    FeatureLayer: any;
    GeoJSONLayer: any;
    TileLayer: any;
    VectorTileLayer: any;
    Point: any;
    Polygon: any;
    Extent: any;
    SpatialReference: any;
    webMercatorUtils: any;
    SimpleMarkerSymbol: any;
    PictureMarkerSymbol: any;
    TextSymbol: any;
    SimpleFillSymbol: any;
    SimpleLineSymbol: any;
    SimpleRenderer: any;
    UniqueValueRenderer: any;
    ClassBreaksRenderer: any;
    reactiveUtils: any;
    Zoom: any;
    Fullscreen: any;
    Compass: any;
}

const MODULE_PATHS = [
    'esri/config',
    'esri/Map',
    'esri/Basemap',
    'esri/views/MapView',
    'esri/Graphic',
    'esri/layers/GraphicsLayer',
    'esri/layers/FeatureLayer',
    'esri/layers/GeoJSONLayer',
    'esri/layers/TileLayer',
    'esri/layers/VectorTileLayer',
    'esri/geometry/Point',
    'esri/geometry/Polygon',
    'esri/geometry/Extent',
    'esri/geometry/SpatialReference',
    'esri/geometry/support/webMercatorUtils',
    'esri/symbols/SimpleMarkerSymbol',
    'esri/symbols/PictureMarkerSymbol',
    'esri/symbols/TextSymbol',
    'esri/symbols/SimpleFillSymbol',
    'esri/symbols/SimpleLineSymbol',
    'esri/renderers/SimpleRenderer',
    'esri/renderers/UniqueValueRenderer',
    'esri/renderers/ClassBreaksRenderer',
    'esri/core/reactiveUtils',
    'esri/widgets/Zoom',
    'esri/widgets/Fullscreen',
    'esri/widgets/Compass',
];

const MODULE_KEYS: (keyof EsriModules)[] = [
    'esriConfig', 'Map', 'Basemap', 'MapView', 'Graphic', 'GraphicsLayer',
    'FeatureLayer', 'GeoJSONLayer', 'TileLayer', 'VectorTileLayer', 'Point',
    'Polygon', 'Extent', 'SpatialReference', 'webMercatorUtils',
    'SimpleMarkerSymbol', 'PictureMarkerSymbol', 'TextSymbol',
    'SimpleFillSymbol', 'SimpleLineSymbol', 'SimpleRenderer',
    'UniqueValueRenderer', 'ClassBreaksRenderer', 'reactiveUtils', 'Zoom',
    'Fullscreen', 'Compass',
];

export interface EsriLoadOptions {
    /** ArcGIS SDK version on the CDN, e.g. '4.31'. Ignored if scriptUrl is set. */
    version?: string;
    /** Full override, for towns pinned to an internally mirrored SDK build. */
    scriptUrl?: string;
    /** Theme CSS. Defaults to the light theme for the chosen version. */
    cssUrl?: string;
    /** ArcGIS Location Platform API key, for Esri-hosted basemaps/services. */
    apiKey?: string | null;
    /** Extra esriConfig.request.trustedServers entries for on-prem ArcGIS Server. */
    trustedServers?: string[];
    /** CORS-enabled server hostnames (older on-prem ArcGIS Server deployments). */
    corsEnabledServers?: string[];
}

let loadPromise: Promise<EsriModules> | null = null;
let cached: EsriModules | null = null;

function ensureCss(url: string): void {
    if (document.querySelector(`link[${CSS_MARKER}]`)) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    link.setAttribute(CSS_MARKER, 'true');
    document.head.appendChild(link);
}

function ensureScript(url: string): Promise<void> {
    const existing = document.querySelector(`script[${SCRIPT_MARKER}]`) as HTMLScriptElement | null;
    if (existing) {
        // A second map mounted before the first script finished; ride the same tag.
        if ((window as any).require) return Promise.resolve();
        return new Promise((resolve, reject) => {
            existing.addEventListener('load', () => resolve());
            existing.addEventListener('error', () => reject(new Error('Failed to load the ArcGIS Maps SDK')));
        });
    }

    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = url;
        script.async = true;
        script.setAttribute(SCRIPT_MARKER, 'true');
        script.onload = () => resolve();
        script.onerror = () => reject(new Error('Failed to load the ArcGIS Maps SDK'));
        document.head.appendChild(script);
    });
}

function amdRequire(paths: string[]): Promise<any[]> {
    const req = (window as any).require;
    if (typeof req !== 'function') {
        return Promise.reject(new Error('ArcGIS AMD loader is not available'));
    }
    return new Promise((resolve, reject) => {
        req(paths, (...mods: any[]) => resolve(mods), (err: any) => reject(err));
    });
}

export function loadEsri(options: EsriLoadOptions = {}): Promise<EsriModules> {
    if (loadPromise) return loadPromise;

    const version = options.version || DEFAULT_VERSION;
    const scriptUrl = options.scriptUrl || `https://js.arcgis.com/${version}/`;
    const cssUrl = options.cssUrl || `https://js.arcgis.com/${version}/esri/themes/light/main.css`;

    loadPromise = (async () => {
        ensureCss(cssUrl);
        await ensureScript(scriptUrl);

        const resolved = await amdRequire(MODULE_PATHS);
        const mods = {} as EsriModules;
        MODULE_KEYS.forEach((key, i) => { (mods as any)[key] = resolved[i]; });

        if (options.apiKey) mods.esriConfig.apiKey = options.apiKey;
        for (const server of options.trustedServers || []) {
            mods.esriConfig.request.trustedServers.push(server);
        }
        for (const server of options.corsEnabledServers || []) {
            mods.esriConfig.request.corsEnabledServers.push(server);
        }

        cached = mods;
        return mods;
    })().catch(err => {
        // Let a transient network failure be retried instead of poisoning the
        // provider for the rest of the session.
        loadPromise = null;
        throw err;
    });

    return loadPromise;
}

/** Modules for code paths that run after load() and cannot await (constructors). */
export function esriModules(): EsriModules {
    if (!cached) throw new Error('ArcGIS SDK not loaded — call loadEsri() first');
    return cached;
}
