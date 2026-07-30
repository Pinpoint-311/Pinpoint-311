/**
 * Google Maps JS SDK adapter for the MapRenderer interface.
 *
 * This is the only file in the app allowed to touch `google.maps` for
 * rendering. Everything it exports is described in terms of src/maps/types.ts;
 * the vendor objects stay private to the module.
 */

import { MarkerClusterer, Renderer as ClusterRenderer } from '@googlemaps/markerclusterer';
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
    MapPointerEvent,
    MapProviderId,
    MapRenderer,
    MarkerHandle,
    MarkerIcon,
    MarkerLayer,
    MarkerLayerOptions,
    MarkerOptions,
    OverlayViewport,
    PolygonHandle,
    PolygonOptions,
    PopupHandle,
    PopupOptions,
    Unsubscribe,
    VectorStyle,
} from '../../types';

/* eslint-disable @typescript-eslint/no-explicit-any */

export const GOOGLE_CAPABILITIES: MapCapabilities = {
    canvasOverlay: true,
    clustering: true,
    tilt: true,
    rotation: true,
    baseMapTypes: ['roadmap', 'satellite', 'hybrid', 'terrain'],
};

const CONTROL_POSITIONS: Record<string, keyof typeof google.maps.ControlPosition> = {
    'top-left': 'TOP_LEFT',
    'top-center': 'TOP_CENTER',
    'top-right': 'TOP_RIGHT',
    'left-top': 'LEFT_TOP',
    'left-center': 'LEFT_CENTER',
    'left-bottom': 'LEFT_BOTTOM',
    'right-top': 'RIGHT_TOP',
    'right-center': 'RIGHT_CENTER',
    'right-bottom': 'RIGHT_BOTTOM',
    'bottom-left': 'BOTTOM_LEFT',
    'bottom-center': 'BOTTOM_CENTER',
    'bottom-right': 'BOTTOM_RIGHT',
};

function controlPosition(name?: string): number | undefined {
    if (!name) return undefined;
    const key = CONTROL_POSITIONS[name];
    return key ? window.google.maps.ControlPosition[key] : undefined;
}

function toLatLng(value: google.maps.LatLng | null | undefined): LatLng {
    return value ? { lat: value.lat(), lng: value.lng() } : { lat: 0, lng: 0 };
}

function toBounds(value: google.maps.LatLngBounds | null | undefined): LatLngBounds | null {
    if (!value || value.isEmpty()) return null;
    const ne = value.getNorthEast();
    const sw = value.getSouthWest();
    return { south: sw.lat(), west: sw.lng(), north: ne.lat(), east: ne.lng() };
}

function fromBounds(bounds: LatLngBounds): google.maps.LatLngBounds {
    return new window.google.maps.LatLngBounds(
        { lat: bounds.south, lng: bounds.west },
        { lat: bounds.north, lng: bounds.east },
    );
}

function toGoogleIcon(icon: MarkerIcon | undefined): google.maps.Symbol | google.maps.Icon | undefined {
    if (!icon) return undefined;
    if (icon.type === 'circle') {
        return {
            path: window.google.maps.SymbolPath.CIRCLE,
            scale: icon.radius,
            fillColor: icon.fillColor,
            fillOpacity: icon.fillOpacity ?? 1,
            strokeColor: icon.strokeColor,
            strokeWeight: icon.strokeWidth ?? 0,
        };
    }
    return {
        url: icon.url,
        scaledSize: new window.google.maps.Size(icon.width, icon.height),
        anchor: icon.anchor
            ? new window.google.maps.Point(icon.anchor.x, icon.anchor.y)
            : undefined,
    };
}

function toGoogleStyle(style: VectorStyle | undefined): google.maps.Data.StyleOptions {
    return {
        fillColor: style?.fillColor,
        fillOpacity: style?.fillOpacity,
        strokeColor: style?.strokeColor,
        strokeOpacity: style?.strokeOpacity,
        strokeWeight: style?.strokeWidth,
        visible: style?.visible,
        clickable: style?.clickable,
        zIndex: style?.zIndex,
    };
}

function featureOf(feature: google.maps.Data.Feature): GeoFeature {
    const geometry = feature.getGeometry();
    const geometryType = (geometry?.getType() || 'Point') as GeometryType;
    const properties: Record<string, unknown> = {};
    feature.forEachProperty((value, key) => { properties[key] = value; });

    let position: LatLng | null = null;
    if (geometryType === 'Point' && geometry) {
        position = toLatLng((geometry as google.maps.Data.Point).get());
    }
    return { geometryType, properties, position };
}

class GoogleMarker implements MarkerHandle {
    constructor(readonly native: google.maps.Marker, private readonly onRemove: (m: GoogleMarker) => void) { }

    getPosition(): LatLng {
        return toLatLng(this.native.getPosition());
    }

    setPosition(position: LatLng): void {
        this.native.setPosition(position);
    }

    setIcon(icon: MarkerIcon): void {
        this.native.setIcon(toGoogleIcon(icon));
    }

    setVisible(visible: boolean): void {
        this.native.setVisible(visible);
    }

    remove(): void {
        window.google.maps.event.clearInstanceListeners(this.native);
        this.native.setMap(null);
        this.onRemove(this);
    }
}

class GoogleMarkerLayer implements MarkerLayer {
    private markers: GoogleMarker[] = [];
    private clusterer: MarkerClusterer | null = null;
    private visible = true;
    private removed = false;

    constructor(
        private readonly map: google.maps.Map,
        private readonly cluster: ClusterOptions | undefined,
        private readonly onRemove: (layer: GoogleMarkerLayer) => void,
    ) { }

    private build(options: MarkerOptions): GoogleMarker {
        const native = new window.google.maps.Marker({
            position: options.position,
            // Clustered markers must NOT be attached to the map directly —
            // MarkerClusterer owns their visibility once it takes them.
            map: this.cluster ? null : (this.visible ? this.map : null),
            icon: toGoogleIcon(options.icon),
            label: options.label,
            title: options.title,
            zIndex: options.zIndex,
            draggable: options.draggable,
            animation: options.dropAnimation ? window.google.maps.Animation.DROP : undefined,
        });

        const handle = new GoogleMarker(native, m => {
            this.markers = this.markers.filter(existing => existing !== m);
        });

        if (options.onClick) {
            native.addListener('click', () => {
                options.onClick!({ position: handle.getPosition() }, handle);
            });
        }
        if (options.onDrag) {
            native.addListener('drag', () => {
                options.onDrag!(handle.getPosition());
            });
        }
        if (options.onDragEnd) {
            native.addListener('dragend', () => {
                options.onDragEnd!(handle.getPosition());
            });
        }
        return handle;
    }

    private syncClusterer(): void {
        if (!this.cluster) return;

        const natives = this.markers.map(m => m.native);
        if (!this.clusterer) {
            this.clusterer = new MarkerClusterer({
                map: this.visible ? this.map : null,
                markers: natives,
                renderer: this.clusterRenderer(),
            });
            return;
        }
        this.clusterer.clearMarkers();
        if (natives.length) this.clusterer.addMarkers(natives);
    }

    private clusterRenderer(): ClusterRenderer {
        const style = this.cluster!.style;
        return {
            render: ({ count, position }) => {
                const spec = style(count);
                return new window.google.maps.Marker({
                    position,
                    icon: toGoogleIcon(spec.icon),
                    label: spec.label,
                    zIndex: spec.zIndex,
                });
            },
        };
    }

    setMarkers(markers: MarkerOptions[]): MarkerHandle[] {
        this.clear();
        if (this.removed) return [];
        this.markers = markers.map(m => this.build(m));
        this.syncClusterer();
        return [...this.markers];
    }

    addMarker(marker: MarkerOptions): MarkerHandle {
        const handle = this.build(marker);
        this.markers.push(handle);
        this.syncClusterer();
        return handle;
    }

    clear(): void {
        this.clusterer?.clearMarkers();
        for (const marker of [...this.markers]) marker.remove();
        this.markers = [];
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        if (this.cluster) {
            this.clusterer?.setMap(visible ? this.map : null);
            return;
        }
        for (const marker of this.markers) marker.setVisible(visible);
    }

    remove(): void {
        this.clear();
        this.clusterer?.setMap(null);
        this.clusterer = null;
        this.removed = true;
        this.onRemove(this);
    }
}

class GoogleGeoJsonLayer implements GeoJsonLayerHandle {
    private data: google.maps.Data;

    constructor(
        private readonly map: google.maps.Map,
        options: GeoJsonLayerOptions,
        private readonly onRemove: (layer: GoogleGeoJsonLayer) => void,
    ) {
        this.data = new window.google.maps.Data();

        const gj = options.data as any;
        // Data.addGeoJson only accepts Feature/FeatureCollection, so wrap bare
        // geometries — several stored map layers are raw geometry objects.
        if (gj?.type === 'FeatureCollection') {
            this.data.addGeoJson(gj);
        } else if (gj?.type === 'Feature') {
            this.data.addGeoJson({ type: 'FeatureCollection', features: [gj] });
        } else if (gj?.type) {
            this.data.addGeoJson({
                type: 'FeatureCollection',
                features: [{ type: 'Feature', geometry: gj, properties: {} }],
            });
        }

        this.setStyle(options.style ?? {}, options.pointRendering);

        if (options.onFeatureClick) {
            this.data.addListener('click', (event: google.maps.Data.MouseEvent) => {
                options.onFeatureClick!(featureOf(event.feature), { position: toLatLng(event.latLng) });
            });
        }

        this.data.setMap(map);
    }

    setStyle(
        style: VectorStyle | ((feature: GeoFeature) => VectorStyle),
        pointRendering: GeoJsonLayerOptions['pointRendering'] = 'default',
    ): void {
        this.data.setStyle(feature => {
            const info = featureOf(feature);
            if (pointRendering === 'hidden' && info.geometryType === 'Point') {
                return { visible: false };
            }
            return toGoogleStyle(typeof style === 'function' ? style(info) : style);
        });
    }

    setVisible(visible: boolean): void {
        this.data.setMap(visible ? this.map : null);
    }

    remove(): void {
        window.google.maps.event.clearInstanceListeners(this.data);
        this.data.setMap(null);
        this.onRemove(this);
    }
}

class GooglePolygon implements PolygonHandle {
    private polygon: google.maps.Polygon;

    constructor(
        private readonly map: google.maps.Map,
        options: PolygonOptions,
        private readonly onRemove: (p: GooglePolygon) => void,
    ) {
        this.polygon = new window.google.maps.Polygon({
            paths: options.paths,
            map,
            ...this.toOptions(options.style),
        });
        if (options.onClick) {
            this.polygon.addListener('click', (event: google.maps.PolyMouseEvent) => {
                options.onClick!({ position: toLatLng(event.latLng) });
            });
        }
    }

    private toOptions(style: VectorStyle | undefined): google.maps.PolygonOptions {
        return {
            fillColor: style?.fillColor,
            fillOpacity: style?.fillOpacity,
            strokeColor: style?.strokeColor,
            strokeOpacity: style?.strokeOpacity,
            strokeWeight: style?.strokeWidth,
            clickable: style?.clickable ?? false,
            zIndex: style?.zIndex,
        };
    }

    setStyle(style: VectorStyle): void {
        this.polygon.setOptions(this.toOptions(style));
    }

    setVisible(visible: boolean): void {
        this.polygon.setMap(visible ? this.map : null);
    }

    remove(): void {
        window.google.maps.event.clearInstanceListeners(this.polygon);
        this.polygon.setMap(null);
        this.onRemove(this);
    }
}

class GooglePopup implements PopupHandle {
    private info: google.maps.InfoWindow;

    constructor(
        private readonly map: google.maps.Map,
        options: PopupOptions | undefined,
        private readonly onRemove: (p: GooglePopup) => void,
    ) {
        this.info = new window.google.maps.InfoWindow(
            options?.content ? { content: options.content } : undefined,
        );
    }

    setContent(content: string | HTMLElement): void {
        this.info.setContent(content);
    }

    openAt(anchor: MarkerHandle | LatLng): void {
        if (anchor instanceof GoogleMarker) {
            this.info.open(this.map, anchor.native);
            return;
        }
        this.info.setPosition(anchor as LatLng);
        this.info.open(this.map);
    }

    close(): void {
        this.info.close();
    }

    remove(): void {
        this.info.close();
        this.onRemove(this);
    }
}

/**
 * Canvas overlay on top of OverlayView.
 *
 * The adapter owns the canvas, the sizing and the projection maths; the caller
 * only gets `(ctx, view)` with `view.project()` already in canvas-local pixels.
 * That is the narrowest contract that still supports the spatial-bias heatmap,
 * and it is implementable on MapLibre (absolutely positioned canvas + map.project)
 * and Esri (a custom layer view). It is NOT implementable on Apple MapKit JS —
 * see capabilities.canvasOverlay.
 */
function createCanvasOverlay(
    map: google.maps.Map,
    options: CanvasOverlayOptions,
    onRemove: (o: CanvasOverlayHandle) => void,
): CanvasOverlayHandle {
    class Overlay extends window.google.maps.OverlayView {
        canvas: HTMLCanvasElement | null = null;

        onAdd(): void {
            const canvas = document.createElement('canvas');
            canvas.style.position = 'absolute';
            canvas.style.pointerEvents = 'none';
            this.canvas = canvas;
            this.getPanes()!.overlayLayer.appendChild(canvas);
        }

        onRemove(): void {
            this.canvas?.parentNode?.removeChild(this.canvas);
            this.canvas = null;
        }

        draw(): void {
            const projection = this.getProjection();
            const canvas = this.canvas;
            if (!projection || !canvas) return;

            const mapBounds = map.getBounds();
            if (!mapBounds) return;

            // Position the canvas over the current viewport in the pane's
            // div-pixel space — the same space fromLatLngToDivPixel returns, so
            // projected points line up exactly.
            const ne = projection.fromLatLngToDivPixel(mapBounds.getNorthEast());
            const sw = projection.fromLatLngToDivPixel(mapBounds.getSouthWest());
            if (!ne || !sw) return;

            const left = Math.min(ne.x, sw.x);
            const top = Math.min(ne.y, sw.y);
            const width = Math.max(1, Math.round(Math.abs(ne.x - sw.x)));
            const height = Math.max(1, Math.round(Math.abs(ne.y - sw.y)));

            canvas.style.left = `${left}px`;
            canvas.style.top = `${top}px`;
            canvas.width = width;
            canvas.height = height;

            const ctx = canvas.getContext('2d');
            if (!ctx) return;
            ctx.clearRect(0, 0, width, height);

            const view: OverlayViewport = {
                width,
                height,
                bounds: toBounds(mapBounds)!,
                zoom: map.getZoom() ?? 0,
                project: position => {
                    const px = projection.fromLatLngToDivPixel(
                        new window.google.maps.LatLng(position.lat, position.lng),
                    );
                    return px ? { x: px.x - left, y: px.y - top } : { x: NaN, y: NaN };
                },
            };

            options.draw(ctx, view);
        }
    }

    const overlay = new Overlay();
    overlay.setMap(map);

    const handle: CanvasOverlayHandle = {
        redraw: () => overlay.draw(),
        remove: () => {
            overlay.setMap(null);
            onRemove(handle);
        },
    };
    return handle;
}

export class GoogleMapRenderer implements MapRenderer {
    readonly providerId: MapProviderId = 'google';
    readonly capabilities = GOOGLE_CAPABILITIES;

    private map: google.maps.Map;
    private listeners: google.maps.MapsEventListener[] = [];
    private markerLayers: GoogleMarkerLayer[] = [];
    private geoJsonLayers: GoogleGeoJsonLayer[] = [];
    private polygons: GooglePolygon[] = [];
    private popups: GooglePopup[] = [];
    private overlays: CanvasOverlayHandle[] = [];
    private defaultMarkerLayer: GoogleMarkerLayer | null = null;

    constructor(container: HTMLElement, options: MapInitOptions) {
        const controls = options.controls ?? {};

        const mapOptions: google.maps.MapOptions = {
            center: options.center,
            zoom: options.zoom,
            mapTypeId: options.baseMapType ?? 'roadmap',
            mapTypeControl: controls.baseMapSwitcher?.enabled ?? false,
            streetViewControl: controls.streetView?.enabled ?? false,
            fullscreenControl: controls.fullscreen?.enabled ?? false,
            zoomControl: controls.zoom?.enabled ?? false,
            ...(options.vendorOptions as google.maps.MapOptions | undefined),
        };

        if (controls.baseMapSwitcher?.enabled) {
            mapOptions.mapTypeControlOptions = {
                style: window.google.maps.MapTypeControlStyle.HORIZONTAL_BAR,
                position: controlPosition(controls.baseMapSwitcher.position),
                mapTypeIds: controls.baseMapSwitcher.types,
            };
        }
        if (controls.zoom?.enabled && controls.zoom.position) {
            mapOptions.zoomControlOptions = { position: controlPosition(controls.zoom.position) };
        }
        if (controls.fullscreen?.enabled && controls.fullscreen.position) {
            mapOptions.fullscreenControlOptions = { position: controlPosition(controls.fullscreen.position) };
        }
        if (controls.rotate?.enabled) {
            (mapOptions as any).rotateControl = true;
        }
        // A Map ID switches Google to vector rendering, which is what makes
        // tilt/heading do anything at all — only send them together.
        if (options.styleId) {
            (mapOptions as any).mapId = options.styleId;
            if (options.tilt !== undefined) mapOptions.tilt = options.tilt;
            if (options.heading !== undefined) mapOptions.heading = options.heading;
        }

        this.map = new window.google.maps.Map(container, mapOptions);
    }

    getCenter(): LatLng {
        return toLatLng(this.map.getCenter());
    }

    setCenter(center: LatLng): void {
        this.map.setCenter(center);
    }

    panTo(center: LatLng): void {
        this.map.panTo(center);
    }

    getZoom(): number {
        return this.map.getZoom() ?? 0;
    }

    setZoom(zoom: number): void {
        this.map.setZoom(zoom);
    }

    getBounds(): LatLngBounds | null {
        return toBounds(this.map.getBounds());
    }

    fitBounds(bounds: LatLngBounds, options?: FitBoundsOptions): void {
        this.map.fitBounds(fromBounds(bounds), options?.padding);

        // Google has no maxZoom argument on fitBounds; clamp once the camera
        // settles, otherwise a single-point bounds zooms to street level.
        const maxZoom = options?.maxZoom;
        if (maxZoom === undefined) return;
        const once = this.map.addListener('idle', () => {
            if ((this.map.getZoom() ?? 0) > maxZoom) this.map.setZoom(maxZoom);
            window.google.maps.event.removeListener(once);
        });
    }

    getBaseMapType(): BaseMapType {
        return (this.map.getMapTypeId() as BaseMapType) || 'roadmap';
    }

    setBaseMapType(type: BaseMapType): void {
        this.map.setMapTypeId(type);
    }

    createMarkerLayer(options?: MarkerLayerOptions): MarkerLayer {
        const layer = new GoogleMarkerLayer(this.map, options?.cluster, l => {
            this.markerLayers = this.markerLayers.filter(existing => existing !== l);
        });
        this.markerLayers.push(layer);
        return layer;
    }

    addMarker(options: MarkerOptions): MarkerHandle {
        if (!this.defaultMarkerLayer) {
            this.defaultMarkerLayer = this.createMarkerLayer() as GoogleMarkerLayer;
        }
        return this.defaultMarkerLayer.addMarker(options);
    }

    addGeoJsonLayer(options: GeoJsonLayerOptions): GeoJsonLayerHandle {
        const layer = new GoogleGeoJsonLayer(this.map, options, l => {
            this.geoJsonLayers = this.geoJsonLayers.filter(existing => existing !== l);
        });
        this.geoJsonLayers.push(layer);
        return layer;
    }

    addPolygon(options: PolygonOptions): PolygonHandle {
        const polygon = new GooglePolygon(this.map, options, p => {
            this.polygons = this.polygons.filter(existing => existing !== p);
        });
        this.polygons.push(polygon);
        return polygon;
    }

    createPopup(options?: PopupOptions): PopupHandle {
        const popup = new GooglePopup(this.map, options, p => {
            this.popups = this.popups.filter(existing => existing !== p);
        });
        this.popups.push(popup);
        return popup;
    }

    addCanvasOverlay(options: CanvasOverlayOptions): CanvasOverlayHandle | null {
        const overlay = createCanvasOverlay(this.map, options, o => {
            this.overlays = this.overlays.filter(existing => existing !== o);
        });
        this.overlays.push(overlay);
        return overlay;
    }

    on<K extends keyof MapEventMap>(event: K, handler: (payload: MapEventMap[K]) => void): Unsubscribe {
        const emit = handler as (payload: any) => void;
        let listener: google.maps.MapsEventListener;

        if (event === 'click') {
            listener = this.map.addListener('click', (e: google.maps.MapMouseEvent) => {
                if (!e.latLng) return;
                emit({ position: toLatLng(e.latLng) } as MapPointerEvent);
            });
        } else if (event === 'idle') {
            listener = this.map.addListener('idle', () => emit(undefined));
        } else {
            listener = this.map.addListener('maptypeid_changed', () => {
                emit({ type: this.getBaseMapType() });
            });
        }

        this.listeners.push(listener);
        return () => {
            window.google.maps.event.removeListener(listener);
            this.listeners = this.listeners.filter(existing => existing !== listener);
        };
    }

    destroy(): void {
        for (const listener of this.listeners) window.google.maps.event.removeListener(listener);
        this.listeners = [];
        for (const layer of [...this.markerLayers]) layer.remove();
        for (const layer of [...this.geoJsonLayers]) layer.remove();
        for (const polygon of [...this.polygons]) polygon.remove();
        for (const popup of [...this.popups]) popup.remove();
        for (const overlay of [...this.overlays]) overlay.remove();
        this.defaultMarkerLayer = null;
        window.google.maps.event.clearInstanceListeners(this.map);
    }
}
