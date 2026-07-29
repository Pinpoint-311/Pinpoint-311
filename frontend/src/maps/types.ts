/**
 * Provider-neutral map interfaces.
 *
 * Pinpoint is self-hosted; a town may run Google, MapLibre, Esri, Apple MapKit
 * or Azure Maps. Nothing in this file may reference a vendor SDK, and no
 * function here may take or return a vendor object — coordinates are always
 * plain WGS84 `{lat, lng}` and everything the caller holds onto is an opaque
 * handle with `remove()`.
 *
 * Rendering and geocoding are deliberately two separate interfaces (see
 * GeocodingProvider below): a town must be able to render Esri basemaps while
 * geocoding against Google, or render MapLibre while geocoding against its
 * county's own address locator. Bundling them would make several adapters
 * useless in practice.
 */

export type MapProviderId = 'google' | 'esri' | 'apple' | 'azure';

export interface LatLng {
    lat: number;
    lng: number;
}

/** Axis-aligned WGS84 box. Not a vendor bounds object. */
export interface LatLngBounds {
    south: number;
    west: number;
    north: number;
    east: number;
}

/**
 * Top of the marker z-order stack. Google's Marker.MAX_ZINDEX is exactly this;
 * other providers should clamp to their own maximum. Callers that want "always
 * on top" (cluster bubbles) add a small offset to this instead of hardcoding.
 */
export const TOP_MARKER_Z_INDEX = 1000000;

export type BaseMapType = 'roadmap' | 'satellite' | 'hybrid' | 'terrain';

export type ControlPosition =
    | 'top-left' | 'top-center' | 'top-right'
    | 'left-top' | 'left-center' | 'left-bottom'
    | 'right-top' | 'right-center' | 'right-bottom'
    | 'bottom-left' | 'bottom-center' | 'bottom-right';

export interface ControlOptions {
    enabled: boolean;
    position?: ControlPosition;
}

export interface BaseMapControlOptions extends ControlOptions {
    types?: BaseMapType[];
}

export interface MapControlsOptions {
    baseMapSwitcher?: BaseMapControlOptions;
    zoom?: ControlOptions;
    fullscreen?: ControlOptions;
    rotate?: ControlOptions;
    /** Google-only surface; providers without a street-level mode ignore it. */
    streetView?: ControlOptions;
}

/**
 * Marker icons are *data*, never DOM or vendor symbols. That is what lets a
 * MapLibre adapter back a clustered marker layer with a GeoJSON source + symbol
 * layer instead of DOM markers — it can rasterise these descriptions itself.
 */
export type MarkerIcon =
    | {
        type: 'circle';
        /** Radius in screen pixels (matches Google's SymbolPath.CIRCLE `scale`). */
        radius: number;
        fillColor: string;
        fillOpacity?: number;
        strokeColor?: string;
        strokeWidth?: number;
    }
    | {
        type: 'image';
        /** Any URL, including a `data:` URI. */
        url: string;
        width: number;
        height: number;
        /** Pixel offset within the image that sits on the coordinate. */
        anchor?: { x: number; y: number };
    };

export interface MarkerLabel {
    text: string;
    color?: string;
    fontSize?: string;
    fontWeight?: string;
}

export interface MapPointerEvent {
    position: LatLng;
}

export interface MarkerOptions {
    position: LatLng;
    icon?: MarkerIcon;
    label?: MarkerLabel;
    /** Native tooltip / accessible name. */
    title?: string;
    zIndex?: number;
    draggable?: boolean;
    /** Cosmetic drop-in animation; providers without one simply place the pin. */
    dropAnimation?: boolean;
    /** The handle is passed back so popups can anchor to the marker itself. */
    onClick?: (e: MapPointerEvent, marker: MarkerHandle) => void;
    onDragEnd?: (position: LatLng) => void;
}

export interface MarkerHandle {
    getPosition(): LatLng;
    setPosition(position: LatLng): void;
    setIcon(icon: MarkerIcon): void;
    setVisible(visible: boolean): void;
    remove(): void;
}

/**
 * Clustering is part of the interface rather than a wrapper around one vendor's
 * package because the vendors disagree fundamentally: Google needs an external
 * clusterer driven in JS, MapLibre clusters inside the style spec, Esri has a
 * FeatureReduction on the layer. Expressing it as "a marker layer that may
 * cluster" is the one shape all three can implement.
 *
 * `style` is a plain function of the cluster size. Providers whose clustering is
 * expression-based must sample it at breakpoints (or render cluster bubbles as
 * ordinary markers over a clustered source) — the difference stays inside the
 * adapter.
 */
export interface ClusterOptions {
    style: (count: number) => { icon: MarkerIcon; label?: MarkerLabel; zIndex?: number };
}

export interface MarkerLayerOptions {
    cluster?: ClusterOptions;
}

/**
 * Markers are managed in bulk. Every call site in the app clears and rebuilds
 * its whole marker set when a filter changes, and bulk replacement is also the
 * only pattern that maps onto source-based providers without thrashing.
 */
export interface MarkerLayer {
    setMarkers(markers: MarkerOptions[]): MarkerHandle[];
    addMarker(marker: MarkerOptions): MarkerHandle;
    clear(): void;
    setVisible(visible: boolean): void;
    remove(): void;
}

export type GeometryType =
    | 'Point' | 'MultiPoint'
    | 'LineString' | 'MultiLineString'
    | 'Polygon' | 'MultiPolygon'
    | 'GeometryCollection';

export interface GeoFeature {
    geometryType: GeometryType;
    properties: Record<string, unknown>;
    /** Representative point — set for Point features, null otherwise. */
    position: LatLng | null;
}

export interface VectorStyle {
    fillColor?: string;
    fillOpacity?: number;
    strokeColor?: string;
    strokeOpacity?: number;
    strokeWidth?: number;
    visible?: boolean;
    clickable?: boolean;
    zIndex?: number;
}

export interface GeoJsonLayerOptions {
    /** Raw GeoJSON: FeatureCollection, Feature, or a bare geometry. */
    data: object;
    style?: VectorStyle | ((feature: GeoFeature) => VectorStyle);
    /**
     * Point features inside a GeoJSON layer render very differently per vendor,
     * so callers say what they want instead of inheriting whatever the SDK does.
     * 'hidden' means the caller will draw its own markers for points.
     */
    pointRendering?: 'default' | 'hidden';
    onFeatureClick?: (feature: GeoFeature, e: MapPointerEvent) => void;
}

export interface GeoJsonLayerHandle {
    setStyle(style: VectorStyle | ((feature: GeoFeature) => VectorStyle)): void;
    setVisible(visible: boolean): void;
    remove(): void;
}

export interface PolygonOptions {
    /** Ring 0 is the outer ring; the rest are holes. */
    paths: LatLng[][];
    style?: VectorStyle;
    onClick?: (e: MapPointerEvent) => void;
}

export interface PolygonHandle {
    setStyle(style: VectorStyle): void;
    setVisible(visible: boolean): void;
    remove(): void;
}

export interface PopupOptions {
    content?: string | HTMLElement;
}

/**
 * One popup object reused across many anchors, which is how every call site
 * already behaves (a single InfoWindow ref, re-targeted on each marker click)
 * and how MapLibre/Esri popups work too.
 */
export interface PopupHandle {
    setContent(content: string | HTMLElement): void;
    openAt(anchor: MarkerHandle | LatLng): void;
    close(): void;
    remove(): void;
}

/**
 * Viewport snapshot handed to a canvas overlay's draw callback. `project` maps
 * WGS84 to pixels in the canvas's own coordinate space, which is the only thing
 * the heatmap actually needs from Google's OverlayView projection.
 */
export interface OverlayViewport {
    width: number;
    height: number;
    bounds: LatLngBounds;
    zoom: number;
    project(position: LatLng): { x: number; y: number };
}

export interface CanvasOverlayOptions {
    draw(ctx: CanvasRenderingContext2D, view: OverlayViewport): void;
}

export interface CanvasOverlayHandle {
    redraw(): void;
    remove(): void;
}

export interface MapEventMap {
    click: MapPointerEvent;
    /** Camera has settled — the moment to read bounds/zoom. */
    idle: void;
    basemaptypechange: { type: BaseMapType };
}

export type Unsubscribe = () => void;

export interface CameraOptions {
    center?: LatLng;
    zoom?: number;
    /** Degrees clockwise from north. Ignored by providers without rotation. */
    heading?: number;
    /** Degrees from straight down. Ignored by providers without tilt. */
    tilt?: number;
}

export interface FitBoundsOptions {
    /** Uniform padding in screen pixels. */
    padding?: number;
    maxZoom?: number;
}

export interface MapInitOptions extends CameraOptions {
    baseMapType?: BaseMapType;
    controls?: MapControlsOptions;
    /**
     * Opaque vendor style/map identifier: a Google Map ID, a MapLibre style URL,
     * an Esri basemap id, an Azure style. Deliberately untyped beyond a string —
     * every provider has one and none of them mean the same thing.
     */
    styleId?: string | null;
    /**
     * Escape hatch for things this interface refuses to model (Google's style
     * JSON array, for instance). Anything set here is by definition
     * non-portable; prefer adding a real field if more than one provider can
     * honour it.
     */
    vendorOptions?: Record<string, unknown>;
}

export interface MapCapabilities {
    /** False on providers with no pixel-space overlay API (Apple MapKit JS). */
    canvasOverlay: boolean;
    clustering: boolean;
    tilt: boolean;
    rotation: boolean;
    baseMapTypes: BaseMapType[];
}

export interface MapRenderer {
    readonly providerId: MapProviderId;
    readonly capabilities: MapCapabilities;

    getCenter(): LatLng;
    setCenter(center: LatLng): void;
    panTo(center: LatLng): void;
    getZoom(): number;
    setZoom(zoom: number): void;
    getBounds(): LatLngBounds | null;
    fitBounds(bounds: LatLngBounds, options?: FitBoundsOptions): void;

    getBaseMapType(): BaseMapType;
    setBaseMapType(type: BaseMapType): void;

    createMarkerLayer(options?: MarkerLayerOptions): MarkerLayer;
    /** Sugar for a one-off pin; goes into a shared unclustered layer. */
    addMarker(options: MarkerOptions): MarkerHandle;
    addGeoJsonLayer(options: GeoJsonLayerOptions): GeoJsonLayerHandle;
    addPolygon(options: PolygonOptions): PolygonHandle;
    createPopup(options?: PopupOptions): PopupHandle;
    /** Null when `capabilities.canvasOverlay` is false. */
    addCanvasOverlay(options: CanvasOverlayOptions): CanvasOverlayHandle | null;

    on<K extends keyof MapEventMap>(event: K, handler: (payload: MapEventMap[K]) => void): Unsubscribe;

    destroy(): void;
}

// ---------------------------------------------------------------------------
// Geocoding — a separate provider, separately configurable.
// ---------------------------------------------------------------------------

export interface GeocodeResult {
    formattedAddress: string;
    position: LatLng;
    /** Suggested viewport for the result, when the provider supplies one. */
    viewport?: LatLngBounds | null;
    name?: string;
}

export interface AddressSuggestion {
    /** Provider-opaque token passed back to resolveSuggestion. */
    id: string;
    label: string;
    secondaryLabel?: string;
}

export interface SuggestOptions {
    /** ISO 3166-1 alpha-2 codes to restrict results to. */
    countries?: string[];
    biasBounds?: LatLngBounds | null;
    /** Restrict to street addresses rather than POIs/regions. */
    addressesOnly?: boolean;
}

export interface AutocompleteOptions extends SuggestOptions {
    onSelect: (result: GeocodeResult) => void;
}

/**
 * Live binding between a text input and a provider's own suggestion UI.
 * `setBiasBounds` exists so a *caller* can feed the map's viewport in without
 * the geocoder ever seeing a map object — that coupling is what keeps rendering
 * and geocoding independently swappable.
 */
export interface AutocompleteHandle {
    setBiasBounds(bounds: LatLngBounds | null): void;
    destroy(): void;
}

export interface GeocodingProvider {
    readonly id: string;
    reverseGeocode(position: LatLng): Promise<GeocodeResult | null>;
    geocode(query: string): Promise<GeocodeResult[]>;
    /** Data-in/data-out suggestions for callers rendering their own dropdown. */
    suggest?(query: string, options?: SuggestOptions): Promise<AddressSuggestion[]>;
    resolveSuggestion?(suggestion: AddressSuggestion): Promise<GeocodeResult | null>;
    /**
     * Attach the provider's native autocomplete widget to an input. Returns null
     * when the provider has no widget, in which case callers fall back to
     * suggest() + their own list.
     */
    attachAutocomplete?(input: HTMLInputElement, options: AutocompleteOptions): AutocompleteHandle | null;
}

// ---------------------------------------------------------------------------
// Provider registration
// ---------------------------------------------------------------------------

export interface MapProviderConfig {
    provider: MapProviderId;
    apiKey?: string | null;
    styleId?: string | null;
    options?: Record<string, unknown>;
}

export interface MapProviderFactory {
    readonly id: MapProviderId;
    readonly displayName: string;
    readonly capabilities: MapCapabilities;
    /** Guarded, single-inclusion SDK load. Must be safe to call concurrently. */
    load(config: MapProviderConfig): Promise<void>;
    createRenderer(container: HTMLElement, config: MapProviderConfig, options: MapInitOptions): MapRenderer;
    createGeocoder?(config: MapProviderConfig): GeocodingProvider;
}
