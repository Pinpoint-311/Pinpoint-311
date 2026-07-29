/**
 * Apple MapKit JS adapter for the MapRenderer interface.
 *
 * This is the least complete of Pinpoint's adapters and it is meant to be:
 * MapKit JS is a consumer mapping SDK, not a GIS one. Read capabilities before
 * reading anything else — every `false` there is a real hole, and the app is
 * expected to degrade around them rather than the adapter pretend.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

import {
    BaseMapType,
    CanvasOverlayHandle,
    CanvasOverlayOptions,
    ClusterOptions,
    FitBoundsOptions,
    GeoFeature,
    GeoJsonLayerHandle,
    GeoJsonLayerOptions,
    GeometryType,
    LatLng,
    LatLngBounds,
    MapCapabilities,
    MapEventMap,
    MapInitOptions,
    MapProviderId,
    MapRenderer,
    MarkerHandle,
    MarkerIcon,
    MarkerLayer,
    MarkerLayerOptions,
    MarkerOptions,
    PolygonHandle,
    PolygonOptions,
    PopupHandle,
    PopupOptions,
    Unsubscribe,
    VectorStyle,
} from '../../types';
import { anchorOffset, rasterise } from './icons';
import { appleMapKit } from './loader';

export const APPLE_CAPABILITIES: MapCapabilities = {
    // MapKit JS exposes no pixel-space projection hook that is usable for a
    // per-frame overlay. There is no overlay pane, no custom-layer API, and no
    // render-loop callback. convertCoordinateToPointOnPage() exists, but it is
    // page-space, it is only meaningful while the camera is at rest, and there
    // is no event that fires per animation frame — only region-change-start and
    // region-change-end. An external canvas driven off those would sit frozen
    // and misaligned throughout every pan, zoom and momentum scroll. A visibly
    // wrong heatmap is worse than no heatmap, so this returns null and the app
    // falls back to graduated markers.
    canvasOverlay: false,
    // Real, via annotation.clusteringIdentifier + map.annotationForCluster. Two
    // caveats, neither fatal: annotationForCluster is a property of the *Map*
    // rather than of an annotation set, so multiple clustered layers share one
    // callback (dispatched here by clustering identifier); and the clustering
    // distance is fixed by MapKit's collision logic and cannot be configured.
    clustering: true,
    // MapKit JS has cameraDistance and rotation but exposes no pitch/tilt on the
    // 2D web map. The 3D-looking Apple Maps camera is not available to MapKit JS.
    tilt: false,
    rotation: true,
    // Standard, Hybrid and Satellite are genuine map types. There is no terrain
    // type — MutedStandard is a desaturated street map, not topography — so
    // 'terrain' is absent rather than silently aliased to something else.
    baseMapTypes: ['roadmap', 'satellite', 'hybrid'],
};

const TILE_SIZE = 256;

function mapTypeFor(mapkit: any, type: BaseMapType): any {
    switch (type) {
        case 'satellite': return mapkit.Map.MapTypes.Satellite;
        case 'hybrid': return mapkit.Map.MapTypes.Hybrid;
        default: return mapkit.Map.MapTypes.Standard;
    }
}

function baseMapTypeOf(mapkit: any, value: any): BaseMapType {
    if (value === mapkit.Map.MapTypes.Satellite) return 'satellite';
    if (value === mapkit.Map.MapTypes.Hybrid) return 'hybrid';
    return 'roadmap';
}

/**
 * MapKit has no zoom level: the camera is a CoordinateRegion (a centre and a
 * span). Everything in MapRenderer is expressed in Google-style zoom levels, so
 * convert through the standard Web Mercator relation
 *   world width in pixels = 256 * 2^zoom.
 * Latitude is folded in for the vertical span because a degree of longitude
 * shrinks with cos(lat); without it a fitBounds in New Jersey overshoots.
 */
function zoomFromSpan(longitudeDelta: number, widthPx: number): number {
    if (!longitudeDelta || !widthPx) return 0;
    return Math.log2((360 * widthPx) / (TILE_SIZE * longitudeDelta));
}

function spanForZoom(zoom: number, widthPx: number): number {
    if (!widthPx) return 360;
    return (360 * widthPx) / (TILE_SIZE * Math.pow(2, zoom));
}

function styleFrom(mapkit: any, style: VectorStyle | undefined): any {
    return new mapkit.Style({
        fillColor: style?.fillColor ?? '#3b82f6',
        fillOpacity: style?.fillOpacity ?? 0.2,
        strokeColor: style?.strokeColor ?? '#1d4ed8',
        strokeOpacity: style?.strokeOpacity ?? 1,
        lineWidth: style?.strokeWidth ?? 2,
    });
}

interface AppleContext {
    mapkit: any;
    map: any;
    /** Coordinate of the most recent tap, for events MapKit gives no location. */
    lastTap(): LatLng;
    registerClusterStyle(id: string, style: ClusterOptions['style'] | null): void;
}

// ---------------------------------------------------------------------------
// Markers
// ---------------------------------------------------------------------------

class AppleMarker implements MarkerHandle {
    readonly annotation: any;
    private position: LatLng;

    constructor(
        private readonly ctx: AppleContext,
        options: MarkerOptions,
        clusteringIdentifier: string | null,
        private readonly onRemove: (m: AppleMarker) => void,
    ) {
        const { mapkit } = ctx;
        this.position = options.position;

        const icon = rasterise(options.icon, options.icon?.type === 'circle' ? options.label : undefined);
        const offset = anchorOffset(icon);

        this.annotation = new mapkit.ImageAnnotation(
            new mapkit.Coordinate(options.position.lat, options.position.lng),
            {
                url: { 1: icon.url },
                size: { width: icon.width, height: icon.height },
                anchorOffset: new DOMPoint(offset.x, offset.y),
                // A label that could not be composited into the artwork (image
                // icons) still has to reach assistive tech somehow.
                title: options.title ?? options.label?.text ?? '',
                // MapKit's priority band is 0-1000; TOP_MARKER_Z_INDEX and any
                // caller offset above it clamp to Required.
                displayPriority: Math.max(0, Math.min(1000, options.zIndex ?? 0)),
                animates: options.dropAnimation ?? false,
                draggable: options.draggable ?? false,
                clusteringIdentifier,
                collisionMode: null,
            },
        );

        if (options.onClick) {
            this.annotation.addEventListener('select', () => {
                options.onClick!({ position: this.position }, this);
            });
        }
        if (options.draggable) {
            this.annotation.addEventListener('drag-end', () => {
                const coord = this.annotation.coordinate;
                this.position = { lat: coord.latitude, lng: coord.longitude };
                options.onDragEnd?.(this.position);
            });
        }
    }

    getPosition(): LatLng {
        return this.position;
    }

    setPosition(position: LatLng): void {
        this.position = position;
        this.annotation.coordinate = new this.ctx.mapkit.Coordinate(position.lat, position.lng);
    }

    setIcon(icon: MarkerIcon): void {
        const raster = rasterise(icon);
        const offset = anchorOffset(raster);
        this.annotation.url = { 1: raster.url };
        this.annotation.size = { width: raster.width, height: raster.height };
        this.annotation.anchorOffset = new DOMPoint(offset.x, offset.y);
    }

    setVisible(visible: boolean): void {
        this.annotation.visible = visible;
    }

    remove(): void {
        this.ctx.map.removeAnnotation(this.annotation);
        this.onRemove(this);
    }
}

let clusterIdSeed = 0;

class AppleMarkerLayer implements MarkerLayer {
    private markers: AppleMarker[] = [];
    private visible = true;
    private readonly clusteringIdentifier: string | null;

    constructor(
        private readonly ctx: AppleContext,
        cluster: ClusterOptions | undefined,
        private readonly onRemove: (layer: AppleMarkerLayer) => void,
    ) {
        // MapKit clusters purely by shared clusteringIdentifier, so a unique one
        // per layer is what keeps two marker layers from merging into each other.
        this.clusteringIdentifier = cluster ? `pinpoint-layer-${++clusterIdSeed}` : null;
        if (cluster && this.clusteringIdentifier) {
            ctx.registerClusterStyle(this.clusteringIdentifier, cluster.style);
        }
    }

    private build(options: MarkerOptions): AppleMarker {
        return new AppleMarker(this.ctx, options, this.clusteringIdentifier, m => {
            this.markers = this.markers.filter(existing => existing !== m);
        });
    }

    setMarkers(markers: MarkerOptions[]): MarkerHandle[] {
        this.clear();
        this.markers = markers.map(m => this.build(m));
        if (this.visible && this.markers.length) {
            this.ctx.map.addAnnotations(this.markers.map(m => m.annotation));
        }
        return [...this.markers];
    }

    addMarker(marker: MarkerOptions): MarkerHandle {
        const handle = this.build(marker);
        this.markers.push(handle);
        if (this.visible) this.ctx.map.addAnnotation(handle.annotation);
        return handle;
    }

    clear(): void {
        if (this.markers.length) {
            this.ctx.map.removeAnnotations(this.markers.map(m => m.annotation));
        }
        this.markers = [];
    }

    setVisible(visible: boolean): void {
        if (visible === this.visible) return;
        this.visible = visible;
        const annotations = this.markers.map(m => m.annotation);
        if (!annotations.length) return;
        if (visible) this.ctx.map.addAnnotations(annotations);
        else this.ctx.map.removeAnnotations(annotations);
    }

    remove(): void {
        this.clear();
        if (this.clusteringIdentifier) this.ctx.registerClusterStyle(this.clusteringIdentifier, null);
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// GeoJSON
// ---------------------------------------------------------------------------

const GEOMETRY_TYPES = new Set([
    'Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon', 'GeometryCollection',
]);

function featureInfo(raw: any): GeoFeature {
    const type = raw?.geometry?.type as GeometryType;
    const coords = raw?.geometry?.coordinates;
    return {
        geometryType: GEOMETRY_TYPES.has(type) ? type : 'Point',
        properties: (raw?.properties || {}) as Record<string, unknown>,
        position: type === 'Point' && Array.isArray(coords) ? { lat: coords[1], lng: coords[0] } : null,
    };
}

/**
 * mapkit.importGeoJSON does the parsing, and its delegate is the only place a
 * per-feature style decision can be made — the resulting overlays keep no link
 * back to their source feature, so the mapping is captured here as items are
 * produced.
 */
class AppleGeoJsonLayer implements GeoJsonLayerHandle {
    private items: any[] = [];
    private readonly infoByItem = new Map<any, GeoFeature>();
    private style: VectorStyle | ((feature: GeoFeature) => VectorStyle);
    private visible = true;

    constructor(
        private readonly ctx: AppleContext,
        private readonly options: GeoJsonLayerOptions,
        private readonly onRemove: (layer: AppleGeoJsonLayer) => void,
    ) {
        this.style = options.style ?? {};
        this.visible = typeof this.style === 'function' ? true : (this.style.visible ?? true);
        this.build();
    }

    private styleFor(info: GeoFeature): VectorStyle {
        return typeof this.style === 'function' ? this.style(info) : this.style;
    }

    private build(): void {
        const { mapkit, map } = this.ctx;
        const hidePoints = this.options.pointRendering === 'hidden';

        // The delegate is called depth-first per feature; `pending` carries the
        // feature currently being converted so its properties reach the items.
        let pending: GeoFeature | null = null;

        const remember = (item: any): any => {
            if (item && pending) this.infoByItem.set(item, pending);
            return item;
        };

        const delegate: any = {
            itemForFeature: (item: any, geoJSON: any) => {
                pending = featureInfo(geoJSON);
                return remember(item);
            },
            itemForPoint: (coordinate: any) => {
                if (hidePoints) return null;
                const info = pending;
                const resolved = this.styleFor(info ?? { geometryType: 'Point', properties: {}, position: null });
                const icon = rasterise({
                    type: 'circle',
                    radius: 5,
                    fillColor: resolved.fillColor ?? '#1d4ed8',
                    fillOpacity: resolved.fillOpacity,
                    strokeColor: resolved.strokeColor ?? '#ffffff',
                    strokeWidth: resolved.strokeWidth ?? 1,
                });
                const offset = anchorOffset(icon);
                return remember(new mapkit.ImageAnnotation(coordinate, {
                    url: { 1: icon.url },
                    size: { width: icon.width, height: icon.height },
                    anchorOffset: new DOMPoint(offset.x, offset.y),
                }));
            },
            styleForOverlay: (overlay: any) => {
                const info = this.infoByItem.get(overlay) ?? pending;
                return styleFrom(mapkit, info ? this.styleFor(info) : (this.style as VectorStyle));
            },
            geoJSONDidComplete: (result: any) => {
                this.items = typeof result?.getFlattenedItemList === 'function'
                    ? result.getFlattenedItemList()
                    : [];
            },
            geoJSONDidError: (error: any) => {
                console.warn('MapKit failed to import GeoJSON layer:', error);
            },
        };

        // importGeoJSON accepts a parsed object as well as a URL, and is
        // synchronous in that form — geoJSONDidComplete has already run by here.
        mapkit.importGeoJSON(this.options.data, delegate);

        for (const item of this.items) {
            if (!this.infoByItem.has(item)) continue;
            if (this.options.onFeatureClick) {
                item.addEventListener?.('select', () => {
                    const info = this.infoByItem.get(item)!;
                    this.options.onFeatureClick!(info, { position: info.position ?? this.ctx.lastTap() });
                });
            }
        }

        if (this.items.length) map.addItems(this.items);
        if (!this.visible) this.setVisible(false);
    }

    setStyle(style: VectorStyle | ((feature: GeoFeature) => VectorStyle)): void {
        this.style = style;
        for (const item of this.items) {
            const info = this.infoByItem.get(item);
            if (!info) continue;
            // Only overlays carry a Style; point annotations are images and
            // would need re-rasterising, which setStyle does not attempt.
            if ('style' in item) item.style = styleFrom(this.ctx.mapkit, this.styleFor(info));
        }
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        for (const item of this.items) item.visible = visible;
    }

    remove(): void {
        if (this.items.length) this.ctx.map.removeItems(this.items);
        this.items = [];
        this.infoByItem.clear();
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// Polygons and popups
// ---------------------------------------------------------------------------

class ApplePolygon implements PolygonHandle {
    private readonly overlay: any;

    constructor(
        private readonly ctx: AppleContext,
        options: PolygonOptions,
        private readonly onRemove: (p: ApplePolygon) => void,
    ) {
        const { mapkit, map } = ctx;
        // PolygonOverlay takes an array of rings and fills with the even-odd
        // rule, so rings 1..n punch holes exactly as PolygonOptions specifies.
        const rings = options.paths.map(ring => ring.map(p => new mapkit.Coordinate(p.lat, p.lng)));

        this.overlay = new mapkit.PolygonOverlay(rings, {
            style: styleFrom(mapkit, options.style),
            visible: options.style?.visible ?? true,
            enabled: options.style?.clickable ?? true,
        });

        if (options.onClick) {
            this.overlay.addEventListener('select', () => {
                // MapKit's overlay select event carries no coordinate.
                options.onClick!({ position: ctx.lastTap() });
            });
        }
        map.addOverlay(this.overlay);
    }

    setStyle(style: VectorStyle): void {
        this.overlay.style = styleFrom(this.ctx.mapkit, style);
        if (style.visible !== undefined) this.overlay.visible = style.visible;
        if (style.clickable !== undefined) this.overlay.enabled = style.clickable;
    }

    setVisible(visible: boolean): void {
        this.overlay.visible = visible;
    }

    remove(): void {
        this.ctx.map.removeOverlay(this.overlay);
        this.onRemove(this);
    }
}

/**
 * MapKit has no free-floating popup: callouts belong to annotations and appear
 * when the annotation is selected. Anchoring to a MarkerHandle swaps that
 * annotation's callout delegate; anchoring to a bare coordinate needs an
 * invisible carrier annotation, created and destroyed with the popup.
 */
class ApplePopup implements PopupHandle {
    private content: string | HTMLElement | undefined;
    private carrier: any = null;
    private anchored: any = null;
    private previousCallout: any = undefined;

    constructor(
        private readonly ctx: AppleContext,
        options: PopupOptions | undefined,
        private readonly onRemove: (p: ApplePopup) => void,
    ) {
        this.content = options?.content;
    }

    private element(): HTMLElement {
        if (this.content instanceof HTMLElement) return this.content;
        const div = document.createElement('div');
        div.style.padding = '8px 10px';
        div.style.maxWidth = '280px';
        // String content matches Google's InfoWindow, which also accepts HTML.
        div.innerHTML = typeof this.content === 'string' ? this.content : '';
        return div;
    }

    private delegate(): any {
        return { calloutContentForAnnotation: () => this.element() };
    }

    setContent(content: string | HTMLElement): void {
        this.content = content;
        if (this.anchored) this.anchored.callout = this.delegate();
    }

    openAt(anchor: MarkerHandle | LatLng): void {
        this.close();
        const { mapkit, map } = this.ctx;

        if (anchor instanceof AppleMarker) {
            this.anchored = anchor.annotation;
            this.previousCallout = this.anchored.callout;
            this.anchored.callout = this.delegate();
            map.selectedAnnotation = this.anchored;
            return;
        }

        const position = 'getPosition' in anchor ? (anchor as MarkerHandle).getPosition() : anchor as LatLng;
        // A 1x1 transparent image: the callout needs something to hang off, but
        // nothing should be drawn at the coordinate.
        this.carrier = new mapkit.ImageAnnotation(
            new mapkit.Coordinate(position.lat, position.lng),
            {
                url: { 1: 'data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%221%22%20height%3D%221%22%2F%3E' },
                size: { width: 1, height: 1 },
                callout: this.delegate(),
            },
        );
        map.addAnnotation(this.carrier);
        this.anchored = this.carrier;
        map.selectedAnnotation = this.carrier;
    }

    close(): void {
        const { map } = this.ctx;
        if (this.anchored && map.selectedAnnotation === this.anchored) map.selectedAnnotation = null;
        if (this.anchored && this.anchored !== this.carrier) {
            this.anchored.callout = this.previousCallout;
        }
        if (this.carrier) {
            map.removeAnnotation(this.carrier);
            this.carrier = null;
        }
        this.anchored = null;
        this.previousCallout = undefined;
    }

    remove(): void {
        this.close();
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

export class AppleMapRenderer implements MapRenderer {
    readonly providerId: MapProviderId = 'apple';
    readonly capabilities = APPLE_CAPABILITIES;

    private readonly mapkit: any;
    private readonly map: any;
    private readonly container: HTMLElement;
    private readonly ctx: AppleContext;

    private readonly clusterStyles = new Map<string, ClusterOptions['style']>();
    private readonly markerLayers: AppleMarkerLayer[] = [];
    private readonly geoJsonLayers: AppleGeoJsonLayer[] = [];
    private readonly polygons: ApplePolygon[] = [];
    private readonly popups: ApplePopup[] = [];
    private defaultMarkerLayer: AppleMarkerLayer | null = null;

    private readonly emitters: { [K in keyof MapEventMap]: ((payload: any) => void)[] } = {
        click: [],
        idle: [],
        basemaptypechange: [],
    };

    private lastTapPosition: LatLng = { lat: 0, lng: 0 };
    private lastTapAt = 0;
    private readonly domListeners: (() => void)[] = [];

    constructor(container: HTMLElement, options: MapInitOptions) {
        const mapkit = appleMapKit();
        this.mapkit = mapkit;
        this.container = container;

        const controls = options.controls ?? {};
        const visibility = (enabled: boolean | undefined) =>
            enabled ? mapkit.FeatureVisibility.Visible : mapkit.FeatureVisibility.Hidden;

        this.map = new mapkit.Map(container, {
            center: new mapkit.Coordinate(options.center?.lat ?? 0, options.center?.lng ?? 0),
            mapType: mapTypeFor(mapkit, options.baseMapType ?? 'roadmap'),
            // Control *positions* are not configurable in MapKit JS at all; the
            // ControlOptions.position field is unavoidably ignored here.
            showsZoomControl: controls.zoom?.enabled ?? false,
            showsMapTypeControl: controls.baseMapSwitcher?.enabled ?? false,
            showsCompass: visibility(controls.rotate?.enabled),
            isRotationEnabled: controls.rotate?.enabled ?? true,
            showsScale: mapkit.FeatureVisibility.Hidden,
            // No fullscreen control exists; controls.fullscreen is ignored, and
            // controls.streetView has no MapKit equivalent (Look Around is not
            // exposed to MapKit JS).
            ...(options.vendorOptions as Record<string, unknown> | undefined),
        });

        if (options.zoom !== undefined) this.setZoom(options.zoom);
        if (options.heading !== undefined) this.map.rotation = options.heading;
        // options.tilt is silently dropped — see capabilities.tilt.

        this.ctx = {
            mapkit,
            map: this.map,
            lastTap: () => this.lastTapPosition,
            registerClusterStyle: (id, style) => {
                if (style) this.clusterStyles.set(id, style);
                else this.clusterStyles.delete(id);
            },
        };

        this.installClustering();
        this.installEvents();
    }

    /**
     * One callback per Map, so it dispatches on the cluster's clustering
     * identifier back to the layer that owns it. ClusterOptions.style is a plain
     * function of the count, which is exactly the shape this hook wants — this
     * is the one part of the interface MapKit fits better than Google does.
     */
    private installClustering(): void {
        const { mapkit } = this;
        this.map.annotationForCluster = (clusterAnnotation: any) => {
            const style = this.clusterStyles.get(clusterAnnotation.clusteringIdentifier);
            const count = clusterAnnotation.memberAnnotations?.length ?? 0;
            if (!style) return null;

            const spec = style(count);
            const icon = rasterise(spec.icon, spec.label ?? { text: String(count) });
            const offset = anchorOffset(icon);
            return new mapkit.ImageAnnotation(clusterAnnotation.coordinate, {
                url: { 1: icon.url },
                size: { width: icon.width, height: icon.height },
                anchorOffset: new DOMPoint(offset.x, offset.y),
                title: String(count),
                displayPriority: Math.max(0, Math.min(1000, spec.zIndex ?? 1000)),
                collisionMode: null,
            });
        };
    }

    private coordinateAt(pageX: number, pageY: number): LatLng | null {
        try {
            const coord = this.map.convertPointOnPageToCoordinate(new DOMPoint(pageX, pageY));
            return coord ? { lat: coord.latitude, lng: coord.longitude } : null;
        } catch {
            return null;
        }
    }

    private emitClick(position: LatLng): void {
        this.lastTapPosition = position;
        this.lastTapAt = Date.now();
        for (const emit of this.emitters.click) emit({ position });
    }

    private installEvents(): void {
        const map = this.map;

        // 'single-tap' is the documented map tap event and carries a page point.
        // It is not present in every MapKit build, and it does not fire at all
        // in some embedded WebViews, so a DOM click listener backs it up — with
        // a short dedupe window so a tap never fires the interface event twice.
        let hasSingleTap = false;
        try {
            map.addEventListener('single-tap', (event: any) => {
                hasSingleTap = true;
                const point = event?.pointOnPage;
                const position = point
                    ? this.coordinateAt(point.x, point.y)
                    : null;
                if (position) this.emitClick(position);
            });
        } catch {
            // Older MapKit rejects unknown event names; the DOM path covers it.
        }

        const onDomClick = (event: MouseEvent) => {
            if (hasSingleTap && Date.now() - this.lastTapAt < 500) return;
            // A tap that selected an annotation is that annotation's click, not
            // a map click — same rule as Google's Marker/Map click split.
            if (map.selectedAnnotation) return;
            const position = this.coordinateAt(event.pageX, event.pageY);
            if (position) this.emitClick(position);
        };
        this.container.addEventListener('click', onDomClick);
        this.domListeners.push(() => this.container.removeEventListener('click', onDomClick));

        map.addEventListener('region-change-end', () => {
            for (const emit of this.emitters.idle) emit(undefined);
        });

        map.addEventListener('map-type-change', () => {
            const type = baseMapTypeOf(this.mapkit, map.mapType);
            for (const emit of this.emitters.basemaptypechange) emit({ type });
        });
    }

    private get widthPx(): number {
        return this.container.clientWidth || 1;
    }

    private get heightPx(): number {
        return this.container.clientHeight || 1;
    }

    getCenter(): LatLng {
        const c = this.map.center;
        return { lat: c.latitude, lng: c.longitude };
    }

    setCenter(center: LatLng): void {
        this.map.center = new this.mapkit.Coordinate(center.lat, center.lng);
    }

    panTo(center: LatLng): void {
        this.map.setCenterAnimated(new this.mapkit.Coordinate(center.lat, center.lng), true);
    }

    getZoom(): number {
        return zoomFromSpan(this.map.region?.span?.longitudeDelta ?? 360, this.widthPx);
    }

    setZoom(zoom: number): void {
        const { mapkit } = this;
        const centre = this.map.center;
        const longitudeDelta = spanForZoom(zoom, this.widthPx);
        const latitudeDelta = longitudeDelta
            * (this.heightPx / this.widthPx)
            * Math.cos((centre.latitude * Math.PI) / 180);
        this.map.region = new mapkit.CoordinateRegion(
            centre,
            new mapkit.CoordinateSpan(Math.abs(latitudeDelta), Math.abs(longitudeDelta)),
        );
    }

    getBounds(): LatLngBounds | null {
        const region = this.map.region;
        if (!region) return null;
        const bounding = region.toBoundingRegion();
        return {
            south: bounding.southLatitude,
            west: bounding.westLongitude,
            north: bounding.northLatitude,
            east: bounding.eastLongitude,
        };
    }

    fitBounds(bounds: LatLngBounds, options?: FitBoundsOptions): void {
        const { mapkit } = this;
        let region = new mapkit.BoundingRegion(
            bounds.north, bounds.east, bounds.south, bounds.west,
        ).toCoordinateRegion();

        // MapKit's region setter takes no padding, so padding becomes a span
        // expansion — the same trick the Esri adapter uses for goTo.
        const padding = options?.padding ?? 0;
        if (padding > 0 && this.widthPx > 2 * padding && this.heightPx > 2 * padding) {
            const factor = Math.max(
                this.widthPx / (this.widthPx - 2 * padding),
                this.heightPx / (this.heightPx - 2 * padding),
            );
            region = new mapkit.CoordinateRegion(
                region.center,
                new mapkit.CoordinateSpan(
                    region.span.latitudeDelta * factor,
                    region.span.longitudeDelta * factor,
                ),
            );
        }

        // A single-point bounds collapses the span to zero and MapKit zooms to
        // the maximum; clamp before applying rather than after.
        const maxZoom = options?.maxZoom;
        if (maxZoom !== undefined) {
            const minSpan = spanForZoom(maxZoom, this.widthPx);
            if (region.span.longitudeDelta < minSpan) {
                const ratio = minSpan / Math.max(region.span.longitudeDelta, 1e-9);
                region = new mapkit.CoordinateRegion(
                    region.center,
                    new mapkit.CoordinateSpan(
                        Math.max(region.span.latitudeDelta * ratio, minSpan * (this.heightPx / this.widthPx)),
                        minSpan,
                    ),
                );
            }
        }

        this.map.setRegionAnimated(region, true);
    }

    getBaseMapType(): BaseMapType {
        return baseMapTypeOf(this.mapkit, this.map.mapType);
    }

    setBaseMapType(type: BaseMapType): void {
        // 'terrain' is not a MapKit map type. Falling back to Standard rather
        // than throwing keeps a shared UI usable, and capabilities.baseMapTypes
        // already tells the caller not to offer it.
        this.map.mapType = mapTypeFor(this.mapkit, type);
        for (const emit of this.emitters.basemaptypechange) emit({ type: this.getBaseMapType() });
    }

    createMarkerLayer(options?: MarkerLayerOptions): MarkerLayer {
        const layer = new AppleMarkerLayer(this.ctx, options?.cluster, l => {
            const index = this.markerLayers.indexOf(l);
            if (index >= 0) this.markerLayers.splice(index, 1);
        });
        this.markerLayers.push(layer);
        return layer;
    }

    addMarker(options: MarkerOptions): MarkerHandle {
        if (!this.defaultMarkerLayer) {
            this.defaultMarkerLayer = this.createMarkerLayer() as AppleMarkerLayer;
        }
        return this.defaultMarkerLayer.addMarker(options);
    }

    addGeoJsonLayer(options: GeoJsonLayerOptions): GeoJsonLayerHandle {
        const layer = new AppleGeoJsonLayer(this.ctx, options, l => {
            const index = this.geoJsonLayers.indexOf(l);
            if (index >= 0) this.geoJsonLayers.splice(index, 1);
        });
        this.geoJsonLayers.push(layer);
        return layer;
    }

    addPolygon(options: PolygonOptions): PolygonHandle {
        const polygon = new ApplePolygon(this.ctx, options, p => {
            const index = this.polygons.indexOf(p);
            if (index >= 0) this.polygons.splice(index, 1);
        });
        this.polygons.push(polygon);
        return polygon;
    }

    createPopup(options?: PopupOptions): PopupHandle {
        const popup = new ApplePopup(this.ctx, options, p => {
            const index = this.popups.indexOf(p);
            if (index >= 0) this.popups.splice(index, 1);
        });
        this.popups.push(popup);
        return popup;
    }

    /** Always null. See the comment on APPLE_CAPABILITIES.canvasOverlay. */
    addCanvasOverlay(_options: CanvasOverlayOptions): CanvasOverlayHandle | null {
        return null;
    }

    on<K extends keyof MapEventMap>(event: K, handler: (payload: MapEventMap[K]) => void): Unsubscribe {
        const list = this.emitters[event] as ((payload: any) => void)[];
        list.push(handler as (payload: any) => void);
        return () => {
            const index = list.indexOf(handler as (payload: any) => void);
            if (index >= 0) list.splice(index, 1);
        };
    }

    destroy(): void {
        for (const popup of [...this.popups]) popup.remove();
        for (const polygon of [...this.polygons]) polygon.remove();
        for (const layer of [...this.geoJsonLayers]) layer.remove();
        for (const layer of [...this.markerLayers]) layer.remove();
        this.defaultMarkerLayer = null;

        for (const off of this.domListeners) off();
        this.domListeners.length = 0;
        this.clusterStyles.clear();
        this.emitters.click.length = 0;
        this.emitters.idle.length = 0;
        this.emitters.basemaptypechange.length = 0;

        this.map.annotationForCluster = null;
        this.map.destroy();
    }
}
