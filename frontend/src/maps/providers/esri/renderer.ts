/**
 * ArcGIS Maps SDK for JavaScript adapter for the MapRenderer interface.
 *
 * Strategic target: NJGIN, NJDOT and essentially every New Jersey county GIS
 * department is an Esri shop. This adapter lets a town render its own
 * authoritative basemap (a portal item, a cached MapServer, a vector tile
 * service) and overlay its own road centrelines, instead of trusting whatever
 * a commercial vendor thinks the town looks like.
 *
 * The SDK is loaded from Esri's CDN (see loader.ts) so no Esri code lands in
 * Pinpoint's bundle. This is the only rendering file allowed to touch it.
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
    OverlayViewport,
    PolygonHandle,
    PolygonOptions,
    PopupHandle,
    PopupOptions,
    Unsubscribe,
    VectorStyle,
} from '../../types';
import { EsriModules, esriModules } from './loader';
import {
    fillSymbol,
    fromEsriExtent,
    fromEsriPoint,
    invisiblePointSymbol,
    lineSymbol,
    markerSymbol,
    pointSymbolFromStyle,
    textSymbol,
    toEsriExtent,
    toEsriPoint,
} from './symbols';

export const ESRI_CAPABILITIES: MapCapabilities = {
    canvasOverlay: true,
    clustering: true,
    // A 2D MapView has no pitch at all — tilt exists only on SceneView, which is
    // a different view class with a different (WebGL globe) rendering pipeline
    // and different layer support. Swapping view classes at runtime would change
    // what every other method on this adapter means, so 2D-only, tilt false.
    tilt: false,
    rotation: true,
    baseMapTypes: ['roadmap', 'satellite', 'hybrid', 'terrain'],
};

/**
 * Esri's well-known basemap ids for our four generic types. A town that wants
 * its own basemap sets MapInitOptions.styleId, which overrides 'roadmap'.
 */
const BASEMAP_IDS: Record<BaseMapType, string> = {
    roadmap: 'streets-navigation-vector',
    satellite: 'satellite',
    hybrid: 'hybrid',
    terrain: 'topo-vector',
};

/**
 * ControlPosition has twelve values; view.ui has four corners plus 'manual'.
 * Collapse to the nearest corner rather than pretending to honour the rest.
 */
function uiPosition(position: string | undefined, fallback: string): string {
    if (!position) return fallback;
    if (position.includes('top') && position.includes('left')) return 'top-left';
    if (position.includes('top') && position.includes('right')) return 'top-right';
    if (position.includes('bottom') && position.includes('left')) return 'bottom-left';
    if (position.includes('bottom') && position.includes('right')) return 'bottom-right';
    if (position.startsWith('top')) return 'top-right';
    if (position.startsWith('bottom')) return 'bottom-right';
    if (position.startsWith('left')) return 'top-left';
    if (position.startsWith('right')) return 'top-right';
    return fallback;
}

/** Everything a child handle needs from the renderer, without the renderer itself. */
interface EsriContext {
    mods: EsriModules;
    view: any;
    whenReady(fn: () => void): void;
    /** Route a hitTest on this graphic to a click handler. */
    setGraphicClick(graphic: any, handler: ((position: LatLng) => void) | null): void;
    /** Route a hitTest anywhere in this layer to a handler (GeoJSON layers). */
    setLayerClick(layer: any, handler: ((graphic: any, position: LatLng) => void) | null): void;
    /** Enable pointer dragging for a graphic; null disables. */
    setGraphicDrag(graphic: any, handler: ((position: LatLng) => void) | null): void;
}

// ---------------------------------------------------------------------------
// Markers — unclustered (GraphicsLayer)
// ---------------------------------------------------------------------------

class EsriGraphicsMarker implements MarkerHandle {
    readonly graphic: any;
    private labelGraphic: any = null;
    private position: LatLng;
    private visible = true;

    constructor(
        private readonly ctx: EsriContext,
        private readonly layer: any,
        private readonly options: MarkerOptions,
        private readonly onRemove: (m: EsriGraphicsMarker) => void,
    ) {
        const { mods } = ctx;
        this.position = options.position;

        this.graphic = new mods.Graphic({
            geometry: toEsriPoint(mods, options.position),
            symbol: markerSymbol(mods, options.icon),
            attributes: { title: options.title ?? '' },
        });

        // GraphicsLayer has no per-graphic label slot, so a label is a second
        // graphic pinned to the same point and kept in step with it.
        if (options.label) {
            this.labelGraphic = new mods.Graphic({
                geometry: toEsriPoint(mods, options.position),
                symbol: textSymbol(mods, options.label),
            });
        }

        if (options.onClick) {
            ctx.setGraphicClick(this.graphic, position => options.onClick!({ position }, this));
        }
        if (options.draggable && options.onDragEnd) {
            ctx.setGraphicDrag(this.graphic, position => {
                this.position = position;
                this.syncLabel();
                options.onDragEnd!(position);
            });
        } else if (options.draggable) {
            ctx.setGraphicDrag(this.graphic, position => {
                this.position = position;
                this.syncLabel();
            });
        }
    }

    /** zIndex is emulated by ordering within the layer's graphics collection. */
    get zIndex(): number {
        return this.options.zIndex ?? 0;
    }

    get graphics(): any[] {
        return this.labelGraphic ? [this.graphic, this.labelGraphic] : [this.graphic];
    }

    private syncLabel(): void {
        if (!this.labelGraphic) return;
        this.labelGraphic.geometry = toEsriPoint(this.ctx.mods, this.position);
    }

    getPosition(): LatLng {
        return this.position;
    }

    setPosition(position: LatLng): void {
        this.position = position;
        this.graphic.geometry = toEsriPoint(this.ctx.mods, position);
        this.syncLabel();
    }

    setIcon(icon: MarkerIcon): void {
        this.graphic.symbol = markerSymbol(this.ctx.mods, icon);
    }

    setVisible(visible: boolean): void {
        if (visible === this.visible) return;
        this.visible = visible;
        if (visible) this.layer.addMany(this.graphics);
        else this.layer.removeMany(this.graphics);
    }

    remove(): void {
        this.ctx.setGraphicClick(this.graphic, null);
        this.ctx.setGraphicDrag(this.graphic, null);
        this.layer.removeMany(this.graphics);
        this.onRemove(this);
    }
}

class EsriGraphicsMarkerLayer implements MarkerLayer {
    private readonly layer: any;
    private markers: EsriGraphicsMarker[] = [];
    private visible = true;

    constructor(
        private readonly ctx: EsriContext,
        private readonly onRemove: (layer: MarkerLayer) => void,
    ) {
        this.layer = new ctx.mods.GraphicsLayer({ listMode: 'hide' });
        ctx.view.map.add(this.layer);
    }

    /**
     * Draw order in a GraphicsLayer is array order, so honouring MarkerOptions
     * .zIndex means re-sorting the collection. Cheap because callers replace
     * their whole marker set at once.
     */
    private restack(): void {
        const ordered = [...this.markers].sort((a, b) => a.zIndex - b.zIndex);
        this.layer.removeAll();
        if (!this.visible) return;
        for (const marker of ordered) this.layer.addMany(marker.graphics);
    }

    setMarkers(markers: MarkerOptions[]): MarkerHandle[] {
        this.clear();
        this.markers = markers.map(options => new EsriGraphicsMarker(
            this.ctx, this.layer, options,
            m => { this.markers = this.markers.filter(existing => existing !== m); },
        ));
        this.restack();
        return [...this.markers];
    }

    addMarker(marker: MarkerOptions): MarkerHandle {
        const handle = new EsriGraphicsMarker(
            this.ctx, this.layer, marker,
            m => { this.markers = this.markers.filter(existing => existing !== m); },
        );
        this.markers.push(handle);
        this.restack();
        return handle;
    }

    clear(): void {
        for (const marker of [...this.markers]) marker.remove();
        this.markers = [];
        this.layer.removeAll();
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        this.layer.visible = visible;
    }

    remove(): void {
        this.clear();
        this.ctx.view.map.remove(this.layer);
        this.layer.destroy?.();
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// Markers — clustered (client-side FeatureLayer + FeatureReduction)
// ---------------------------------------------------------------------------

/**
 * FeatureReduction lives on FeatureLayer/GeoJSONLayer, never on GraphicsLayer,
 * so a clustered marker layer has to be a client-side FeatureLayer. That layer
 * type has no per-graphic symbol either — styling goes through a renderer — so
 * each distinct MarkerIcon becomes a unique value keyed on a synthetic field.
 *
 * Consequence: the handles here are plain data holders and the layer is rebuilt
 * from them on a microtask. A burst of setPosition/setIcon calls collapses into
 * one rebuild instead of N applyEdits round-trips.
 */
class EsriClusterMarker implements MarkerHandle {
    position: LatLng;
    icon: MarkerIcon | undefined;
    visible = true;

    constructor(
        readonly options: MarkerOptions,
        private readonly layer: EsriClusterMarkerLayer,
    ) {
        this.position = options.position;
        this.icon = options.icon;
    }

    getPosition(): LatLng {
        return this.position;
    }

    setPosition(position: LatLng): void {
        this.position = position;
        this.layer.invalidate();
    }

    setIcon(icon: MarkerIcon): void {
        this.icon = icon;
        this.layer.invalidate();
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        this.layer.invalidate();
    }

    remove(): void {
        this.layer.forget(this);
    }
}

/** Cluster sizes sampled from ClusterOptions.style to build class breaks. */
const CLUSTER_BREAKS = [2, 5, 10, 25, 50, 100, 250, 500, 1000, 5000];

class EsriClusterMarkerLayer implements MarkerLayer {
    private layer: any = null;
    private markers: EsriClusterMarker[] = [];
    private visible = true;
    private dirty = false;
    private removed = false;

    constructor(
        private readonly ctx: EsriContext,
        private readonly cluster: ClusterOptions,
        private readonly onRemove: (layer: MarkerLayer) => void,
    ) { }

    invalidate(): void {
        if (this.dirty || this.removed) return;
        this.dirty = true;
        queueMicrotask(() => {
            this.dirty = false;
            if (!this.removed) this.rebuild();
        });
    }

    forget(marker: EsriClusterMarker): void {
        this.markers = this.markers.filter(existing => existing !== marker);
        this.invalidate();
    }

    private iconKey(icon: MarkerIcon | undefined): string {
        return icon ? JSON.stringify(icon) : 'default';
    }

    private buildRenderer(icons: Map<string, MarkerIcon | undefined>): any {
        const { mods } = this.ctx;
        return new mods.UniqueValueRenderer({
            field: 'styleKey',
            defaultSymbol: markerSymbol(mods, undefined),
            uniqueValueInfos: [...icons.entries()].map(([value, icon]) => ({
                value,
                symbol: markerSymbol(mods, icon),
            })),
        });
    }

    /**
     * Esri clusters are styled by a renderer over the synthetic `cluster_count`
     * field, not by a callback. ClusterOptions.style is therefore *sampled* at
     * fixed breakpoints — types.ts anticipates exactly this ("providers whose
     * clustering is expression-based must sample it at breakpoints").
     */
    private buildClusterConfig(): any {
        const { mods } = this.ctx;
        const style = this.cluster.style;

        const infos: any[] = [];
        let lower = 1;
        for (const upper of CLUSTER_BREAKS) {
            const spec = style(lower);
            infos.push({
                minValue: lower,
                maxValue: upper - 1,
                symbol: markerSymbol(mods, spec.icon),
            });
            lower = upper;
        }
        const last = style(lower);
        infos.push({ minValue: lower, maxValue: Number.MAX_SAFE_INTEGER, symbol: markerSymbol(mods, last.icon) });

        const sample = style(10);
        return {
            type: 'cluster',
            clusterRadius: '60px',
            popupEnabled: false,
            renderer: new mods.ClassBreaksRenderer({
                field: 'cluster_count',
                classBreakInfos: infos,
                defaultSymbol: markerSymbol(mods, style(1).icon),
            }),
            labelingInfo: sample.label ? [{
                deconflictionStrategy: 'none',
                labelExpressionInfo: { expression: 'Text($feature.cluster_count, "#,###")' },
                labelPlacement: 'center-center',
                symbol: {
                    type: 'text',
                    color: sample.label.color ?? '#ffffff',
                    font: {
                        size: sample.label.fontSize ?? '11px',
                        weight: sample.label.fontWeight ?? 'bold',
                        family: 'sans-serif',
                    },
                },
            }] : undefined,
        };
    }

    private rebuild(): void {
        const { mods, view } = this.ctx;
        const shown = this.markers.filter(m => m.visible);

        const icons = new Map<string, MarkerIcon | undefined>();
        const source = shown.map((marker, index) => {
            const key = this.iconKey(marker.icon);
            if (!icons.has(key)) icons.set(key, marker.icon);
            return new mods.Graphic({
                geometry: toEsriPoint(mods, marker.position),
                attributes: {
                    OBJECTID: index + 1,
                    styleKey: key,
                    labelText: marker.options.label?.text ?? '',
                    title: marker.options.title ?? '',
                },
            });
        });

        const previous = this.layer;
        this.layer = new mods.FeatureLayer({
            source,
            objectIdField: 'OBJECTID',
            geometryType: 'point',
            spatialReference: mods.SpatialReference.WGS84,
            fields: [
                { name: 'OBJECTID', type: 'oid' },
                { name: 'styleKey', type: 'string' },
                { name: 'labelText', type: 'string' },
                { name: 'title', type: 'string' },
            ],
            renderer: this.buildRenderer(icons),
            featureReduction: this.buildClusterConfig(),
            popupEnabled: false,
            visible: this.visible,
            listMode: 'hide',
        });

        // Route clicks on either a cluster bubble or a leaf feature back to the
        // originating marker's onClick, matched by position (client-side
        // FeatureLayer graphics are copies, not our Graphic instances).
        this.ctx.setLayerClick(this.layer, (graphic, position) => {
            const oid = graphic?.attributes?.OBJECTID;
            const marker = typeof oid === 'number' ? shown[oid - 1] : undefined;
            marker?.options.onClick?.({ position }, marker);
        });

        view.map.add(this.layer);
        if (previous) {
            this.ctx.setLayerClick(previous, null);
            view.map.remove(previous);
            previous.destroy?.();
        }
    }

    setMarkers(markers: MarkerOptions[]): MarkerHandle[] {
        this.markers = markers.map(options => new EsriClusterMarker(options, this));
        this.invalidate();
        return [...this.markers];
    }

    addMarker(marker: MarkerOptions): MarkerHandle {
        const handle = new EsriClusterMarker(marker, this);
        this.markers.push(handle);
        this.invalidate();
        return handle;
    }

    clear(): void {
        this.markers = [];
        this.invalidate();
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        if (this.layer) this.layer.visible = visible;
    }

    remove(): void {
        this.removed = true;
        this.markers = [];
        if (this.layer) {
            this.ctx.setLayerClick(this.layer, null);
            this.ctx.view.map.remove(this.layer);
            this.layer.destroy?.();
            this.layer = null;
        }
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// GeoJSON
// ---------------------------------------------------------------------------

type GeoKind = 'point' | 'polyline' | 'polygon';

const GEOMETRY_KIND: Record<string, GeoKind> = {
    Point: 'point',
    MultiPoint: 'point',
    LineString: 'polyline',
    MultiLineString: 'polyline',
    Polygon: 'polygon',
    MultiPolygon: 'polygon',
};

interface SplitFeature {
    kind: GeoKind;
    raw: any;
    info: GeoFeature;
}

/** GeoJSON of any shape (FeatureCollection / Feature / bare geometry) -> features. */
function normaliseFeatures(data: any): SplitFeature[] {
    const raw: any[] =
        data?.type === 'FeatureCollection' ? (data.features || [])
            : data?.type === 'Feature' ? [data]
                : data?.type ? [{ type: 'Feature', geometry: data, properties: {} }]
                    : [];

    const out: SplitFeature[] = [];
    for (const feature of raw) {
        const type = feature?.geometry?.type;
        // GeometryCollection has no ArcGIS equivalent and no GeoJSONLayer
        // support at all; skipping is better than a layer that fails to load.
        const kind = type ? GEOMETRY_KIND[type] : undefined;
        if (!kind) continue;

        const coords = feature.geometry.coordinates;
        out.push({
            kind,
            raw: feature,
            info: {
                geometryType: type as GeometryType,
                properties: (feature.properties || {}) as Record<string, unknown>,
                position: type === 'Point' && Array.isArray(coords)
                    ? { lat: coords[1], lng: coords[0] }
                    : null,
            },
        });
    }
    return out;
}

/**
 * GeoJSONLayer takes a *URL*, not inline data, and supports exactly one geometry
 * type per layer. Both facts are load-bearing here: the data is served to the
 * SDK from an object URL, and a mixed FeatureCollection becomes up to three
 * layers presented behind one handle.
 */
class EsriGeoJsonLayer implements GeoJsonLayerHandle {
    private layers: any[] = [];
    private urls: string[] = [];
    private visible = true;
    private style: VectorStyle | ((feature: GeoFeature) => VectorStyle);
    private readonly features: SplitFeature[];

    constructor(
        private readonly ctx: EsriContext,
        private readonly options: GeoJsonLayerOptions,
        private readonly onRemove: (layer: EsriGeoJsonLayer) => void,
    ) {
        this.features = normaliseFeatures(options.data);
        this.style = options.style ?? {};
        this.build();
    }

    private renderersFor(kind: GeoKind, members: SplitFeature[]): any {
        const { mods } = this.ctx;

        if (kind === 'point' && this.options.pointRendering === 'hidden') {
            return new mods.SimpleRenderer({ symbol: invisiblePointSymbol(mods) });
        }

        const symbolFor = (style: VectorStyle | undefined) =>
            kind === 'polygon' ? fillSymbol(mods, style)
                : kind === 'polyline' ? lineSymbol(mods, style)
                    : pointSymbolFromStyle(mods, style);

        if (typeof this.style !== 'function') {
            return new mods.SimpleRenderer({ symbol: symbolFor(this.style) });
        }

        // Per-feature styling is evaluated here and collapsed to unique values on
        // a synthetic field, because ArcGIS renderers cannot call back into JS
        // per feature. One entry per distinct *style*, not per feature, so a
        // 50k-segment centreline file with three colours makes three entries.
        const fn = this.style;
        const infos: any[] = [];
        const seen = new Map<string, number>();
        members.forEach(member => {
            const resolved = fn(member.info);
            const key = JSON.stringify(resolved);
            if (!seen.has(key)) {
                seen.set(key, seen.size);
                infos.push({ value: String(seen.size - 1), symbol: symbolFor(resolved) });
            }
            member.raw.properties = {
                ...(member.raw.properties || {}),
                __ppStyle: String(seen.get(key)),
            };
        });

        return new mods.UniqueValueRenderer({
            field: '__ppStyle',
            defaultSymbol: symbolFor(undefined),
            uniqueValueInfos: infos,
        });
    }

    private build(): void {
        const { mods, view } = this.ctx;

        const groups = new Map<GeoKind, SplitFeature[]>();
        for (const feature of this.features) {
            const bucket = groups.get(feature.kind) ?? [];
            bucket.push(feature);
            groups.set(feature.kind, bucket);
        }

        for (const [kind, members] of groups) {
            // renderersFor may inject __ppStyle into properties, so it has to run
            // before the collection is serialised into the object URL.
            const renderer = this.renderersFor(kind, members);
            const collection = {
                type: 'FeatureCollection',
                features: members.map(m => m.raw),
            };
            const url = URL.createObjectURL(
                new Blob([JSON.stringify(collection)], { type: 'application/geo+json' }),
            );
            this.urls.push(url);

            const layer = new mods.GeoJSONLayer({
                url,
                renderer,
                visible: this.visible,
                popupEnabled: false,
                listMode: 'hide',
                // GeoJSON is WGS84 by specification; say so rather than letting
                // the SDK guess from the first coordinate pair.
                spatialReference: mods.SpatialReference.WGS84,
            });

            if (this.options.onFeatureClick) {
                const byStyleKey = members;
                this.ctx.setLayerClick(layer, (graphic, position) => {
                    const info = this.matchFeature(byStyleKey, graphic);
                    if (info) this.options.onFeatureClick!(info, { position });
                });
            }

            this.layers.push(layer);
            view.map.add(layer);
        }
    }

    /**
     * GeoJSONLayer assigns its own OBJECTIDs and hands back copies, so a clicked
     * graphic is matched to the source feature by its properties rather than by
     * identity. Exact-property equality is the only key guaranteed to survive.
     */
    private matchFeature(members: SplitFeature[], graphic: any): GeoFeature | null {
        const attrs = graphic?.attributes;
        if (!attrs) return null;
        const match = members.find(member => {
            const props = member.info.properties;
            return Object.keys(props).every(key => (props as any)[key] === attrs[key]);
        });
        return match ? match.info : null;
    }

    private teardown(): void {
        for (const layer of this.layers) {
            this.ctx.setLayerClick(layer, null);
            this.ctx.view.map.remove(layer);
            layer.destroy?.();
        }
        this.layers = [];
        for (const url of this.urls) URL.revokeObjectURL(url);
        this.urls = [];
    }

    setStyle(style: VectorStyle | ((feature: GeoFeature) => VectorStyle)): void {
        this.style = style;

        // A flat style is just a renderer swap. A style *function* changes the
        // synthetic field baked into the served GeoJSON, so the layers have to
        // be rebuilt — rare enough (highlight toggles) to be worth the honesty.
        if (typeof style === 'function') {
            this.teardown();
            this.build();
            return;
        }

        const groups = new Map<GeoKind, SplitFeature[]>();
        for (const feature of this.features) {
            const bucket = groups.get(feature.kind) ?? [];
            bucket.push(feature);
            groups.set(feature.kind, bucket);
        }
        [...groups.keys()].forEach((kind, index) => {
            const layer = this.layers[index];
            if (layer) layer.renderer = this.renderersFor(kind, groups.get(kind)!);
        });

        if (style.visible !== undefined) this.setVisible(style.visible);
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        for (const layer of this.layers) layer.visible = visible;
    }

    remove(): void {
        this.teardown();
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// Polygons and popups
// ---------------------------------------------------------------------------

class EsriPolygon implements PolygonHandle {
    private readonly layer: any;
    private readonly graphic: any;

    constructor(
        private readonly ctx: EsriContext,
        options: PolygonOptions,
        private readonly onRemove: (p: EsriPolygon) => void,
    ) {
        const { mods } = ctx;
        this.layer = new mods.GraphicsLayer({ listMode: 'hide' });

        this.graphic = new mods.Graphic({
            geometry: new mods.Polygon({
                // Ring 0 outer, the rest holes — the same convention as GeoJSON
                // and as PolygonOptions.paths, so no re-winding is needed.
                rings: options.paths.map(ring => ring.map(p => [p.lng, p.lat])),
                spatialReference: mods.SpatialReference.WGS84,
            }),
            symbol: fillSymbol(mods, options.style),
        });

        this.layer.add(this.graphic);
        ctx.view.map.add(this.layer);

        if (options.onClick && (options.style?.clickable ?? true)) {
            ctx.setGraphicClick(this.graphic, position => options.onClick!({ position }));
        }
        if (options.style?.zIndex !== undefined) this.layer.zIndex = options.style.zIndex;
    }

    setStyle(style: VectorStyle): void {
        this.graphic.symbol = fillSymbol(this.ctx.mods, style);
        if (style.zIndex !== undefined) this.layer.zIndex = style.zIndex;
        if (style.visible !== undefined) this.setVisible(style.visible);
    }

    setVisible(visible: boolean): void {
        this.layer.visible = visible;
    }

    remove(): void {
        this.ctx.setGraphicClick(this.graphic, null);
        this.ctx.view.map.remove(this.layer);
        this.layer.destroy?.();
        this.onRemove(this);
    }
}

/**
 * A MapView owns exactly one Popup widget, so several PopupHandles share it.
 * Each handle tracks whether it is the one currently showing, which matches how
 * every call site actually behaves (one long-lived popup, re-targeted).
 */
class EsriPopup implements PopupHandle {
    private content: string | HTMLElement | undefined;
    private open = false;

    constructor(
        private readonly ctx: EsriContext,
        options: PopupOptions | undefined,
        private readonly onRemove: (p: EsriPopup) => void,
    ) {
        this.content = options?.content;
    }

    setContent(content: string | HTMLElement): void {
        this.content = content;
        if (this.open) this.ctx.view.popup.content = content;
    }

    openAt(anchor: MarkerHandle | LatLng): void {
        const position = 'getPosition' in anchor ? anchor.getPosition() : anchor;
        const { view, mods } = this.ctx;
        this.open = true;
        view.popup.dockEnabled = false;
        const payload = {
            location: toEsriPoint(mods, position),
            content: this.content ?? '',
        };
        // view.openPopup arrived in 4.27; fall back for pinned older SDKs.
        if (typeof view.openPopup === 'function') view.openPopup(payload);
        else view.popup.open(payload);
    }

    close(): void {
        if (!this.open) return;
        this.open = false;
        const { view } = this.ctx;
        if (typeof view.closePopup === 'function') view.closePopup();
        else view.popup.close();
    }

    remove(): void {
        this.close();
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// Canvas overlay
// ---------------------------------------------------------------------------

/**
 * Absolutely-positioned canvas over the view surface, projected with
 * view.toScreen(). Deliberately not a custom LayerView (BaseLayerViewGL2D):
 * that gives a WebGL context, not a 2D one, and CanvasOverlayOptions.draw is
 * defined in terms of CanvasRenderingContext2D.
 *
 * view.toScreen() returns coordinates relative to the view container, and the
 * canvas covers the container exactly, so no offset arithmetic is needed.
 */
function createCanvasOverlay(
    ctx: EsriContext,
    options: CanvasOverlayOptions,
    onRemove: (o: CanvasOverlayHandle) => void,
): CanvasOverlayHandle {
    const { mods, view } = ctx;

    const canvas = document.createElement('canvas');
    canvas.style.position = 'absolute';
    canvas.style.inset = '0';
    canvas.style.pointerEvents = 'none';

    // Insert directly after the SDK's own drawing surface so the canvas sits
    // above the map but below view.ui widgets.
    const surface = view.surface as HTMLElement | undefined;
    if (surface?.parentNode) surface.parentNode.insertBefore(canvas, surface.nextSibling);
    else view.container?.appendChild(canvas);

    let removed = false;

    const draw = (): void => {
        if (removed) return;
        const width = Math.max(1, Math.round(view.width || 0));
        const height = Math.max(1, Math.round(view.height || 0));
        const bounds = fromEsriExtent(mods, view.extent);
        if (!bounds) return;

        if (canvas.width !== width) canvas.width = width;
        if (canvas.height !== height) canvas.height = height;

        const context = canvas.getContext('2d');
        if (!context) return;
        context.clearRect(0, 0, width, height);

        const viewport: OverlayViewport = {
            width,
            height,
            bounds,
            zoom: view.zoom ?? 0,
            project: position => {
                const screen = view.toScreen(toEsriPoint(mods, position));
                return screen ? { x: screen.x, y: screen.y } : { x: NaN, y: NaN };
            },
        };
        options.draw(context, viewport);
    };

    // extent is reactive and ticks throughout pan/zoom animation, so watching it
    // gives per-frame redraws without an explicit animation loop.
    const watcher = mods.reactiveUtils.watch(
        () => [view.extent, view.rotation, view.width, view.height],
        () => draw(),
    );
    ctx.whenReady(draw);

    const handle: CanvasOverlayHandle = {
        redraw: draw,
        remove: () => {
            removed = true;
            watcher?.remove?.();
            canvas.parentNode?.removeChild(canvas);
            onRemove(handle);
        },
    };
    return handle;
}

// ---------------------------------------------------------------------------
// Basemap switcher
// ---------------------------------------------------------------------------

/**
 * BasemapToggle only flips between two basemaps and BasemapGallery shows Esri's
 * whole catalogue; neither matches "switch between these BaseMapTypes and tell
 * me about it". A handful of buttons is smaller than bending either widget, and
 * it keeps basemaptypechange truthful.
 */
function createBasemapSwitcher(
    types: BaseMapType[],
    current: () => BaseMapType,
    onSelect: (type: BaseMapType) => void,
): HTMLElement {
    const root = document.createElement('div');
    root.className = 'esri-widget';
    root.style.display = 'flex';
    root.style.overflow = 'hidden';
    root.style.borderRadius = '4px';

    const buttons = new Map<BaseMapType, HTMLButtonElement>();
    const paint = () => {
        for (const [type, button] of buttons) {
            const active = type === current();
            button.style.background = active ? '#0079c1' : '#ffffff';
            button.style.color = active ? '#ffffff' : '#323232';
            button.setAttribute('aria-pressed', String(active));
        }
    };

    for (const type of types) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = type === 'roadmap' ? 'Map' : type[0].toUpperCase() + type.slice(1);
        button.style.border = 'none';
        button.style.padding = '6px 10px';
        button.style.font = '12px sans-serif';
        button.style.cursor = 'pointer';
        button.addEventListener('click', () => { onSelect(type); paint(); });
        buttons.set(type, button);
        root.appendChild(button);
    }
    paint();
    return root;
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

export class EsriMapRenderer implements MapRenderer {
    readonly providerId: MapProviderId = 'esri';
    readonly capabilities = ESRI_CAPABILITIES;

    private readonly mods: EsriModules;
    private readonly view: any;
    private readonly ctx: EsriContext;
    private readonly styleId: string | null;

    private baseMapType: BaseMapType;
    private ready = false;
    private readyQueue: (() => void)[] = [];

    private readonly graphicClicks = new Map<any, (position: LatLng) => void>();
    private readonly layerClicks = new Map<any, (graphic: any, position: LatLng) => void>();
    private readonly graphicDrags = new Map<any, (position: LatLng) => void>();

    private readonly nativeHandles: any[] = [];
    private readonly markerLayers: MarkerLayer[] = [];
    private readonly geoJsonLayers: EsriGeoJsonLayer[] = [];
    private readonly polygons: EsriPolygon[] = [];
    private readonly popups: EsriPopup[] = [];
    private readonly overlays: CanvasOverlayHandle[] = [];
    private defaultMarkerLayer: MarkerLayer | null = null;

    private readonly emitters: { [K in keyof MapEventMap]: ((payload: any) => void)[] } = {
        click: [],
        idle: [],
        basemaptypechange: [],
    };

    private dragging: { graphic: any; handler: (position: LatLng) => void } | null = null;
    private hoveredDraggable: any = null;

    /**
     * Synchronous by contract (MapProviderFactory.createRenderer), but the SDK's
     * classes only exist after an async AMD require. loadEsri() resolves every
     * module this file can need before any renderer is constructed, so the
     * constructor can pull them straight out of the module cache. That is the
     * whole reason loader.ts requires the full module list up front.
     */
    constructor(container: HTMLElement, options: MapInitOptions) {
        const mods = esriModules();
        this.mods = mods;
        this.styleId = options.styleId ?? null;
        this.baseMapType = options.baseMapType ?? 'roadmap';

        const map = new mods.Map({ basemap: this.basemapFor(this.baseMapType) });

        this.view = new mods.MapView({
            container,
            map,
            center: [options.center?.lng ?? 0, options.center?.lat ?? 0],
            zoom: options.zoom ?? 12,
            rotation: options.heading ?? 0,
            constraints: { rotationEnabled: options.controls?.rotate?.enabled ?? true },
            popup: { dockEnabled: false, dockOptions: { buttonEnabled: false } },
            ui: { components: [] },
            ...(options.vendorOptions as Record<string, unknown> | undefined),
        });

        this.ctx = {
            mods,
            view: this.view,
            whenReady: fn => this.whenReady(fn),
            setGraphicClick: (graphic, handler) => {
                if (handler) this.graphicClicks.set(graphic, handler);
                else this.graphicClicks.delete(graphic);
            },
            setLayerClick: (layer, handler) => {
                if (handler) this.layerClicks.set(layer, handler);
                else this.layerClicks.delete(layer);
            },
            setGraphicDrag: (graphic, handler) => {
                if (handler) this.graphicDrags.set(graphic, handler);
                else this.graphicDrags.delete(graphic);
            },
        };

        this.installControls(options);
        this.installInteraction();

        this.view.when(() => {
            this.ready = true;
            const queued = this.readyQueue;
            this.readyQueue = [];
            for (const fn of queued) fn();
        }, () => { /* view failed to initialise; handles stay inert rather than throwing */ });
    }

    private whenReady(fn: () => void): void {
        if (this.ready) fn();
        else this.readyQueue.push(fn);
    }

    /**
     * styleId is whatever the town's GIS department gave them: a portal item id,
     * a cached MapServer URL, a VectorTileServer URL, or an Esri basemap name.
     * It replaces the 'roadmap' basemap only — imagery types stay Esri's, since
     * a local street basemap has no satellite equivalent.
     */
    private basemapFor(type: BaseMapType): any {
        const { mods } = this;
        if (type !== 'roadmap' || !this.styleId) return BASEMAP_IDS[type];

        const id = this.styleId;
        if (/VectorTileServer\/?$/i.test(id)) {
            return new mods.Basemap({ baseLayers: [new mods.VectorTileLayer({ url: id })] });
        }
        if (/MapServer\/?$/i.test(id) || /ImageServer\/?$/i.test(id)) {
            return new mods.Basemap({ baseLayers: [new mods.TileLayer({ url: id })] });
        }
        if (/^[0-9a-f]{32}$/i.test(id)) {
            return new mods.Basemap({ portalItem: { id } });
        }
        return id;
    }

    private installControls(options: MapInitOptions): void {
        const controls = options.controls ?? {};
        const { mods, view } = this;

        if (controls.zoom?.enabled) {
            view.ui.add(new mods.Zoom({ view }), uiPosition(controls.zoom.position, 'top-left'));
        }
        if (controls.fullscreen?.enabled) {
            view.ui.add(new mods.Fullscreen({ view }), uiPosition(controls.fullscreen.position, 'top-right'));
        }
        if (controls.rotate?.enabled) {
            view.ui.add(new mods.Compass({ view }), uiPosition(controls.rotate.position, 'top-left'));
        }
        if (controls.baseMapSwitcher?.enabled) {
            const types = controls.baseMapSwitcher.types?.length
                ? controls.baseMapSwitcher.types
                : ESRI_CAPABILITIES.baseMapTypes;
            view.ui.add(
                createBasemapSwitcher(types, () => this.baseMapType, type => this.setBaseMapType(type)),
                uiPosition(controls.baseMapSwitcher.position, 'top-right'),
            );
        }
        // MapControlsOptions.streetView is Google-only; there is no ArcGIS
        // equivalent (Esri's Oriented Imagery is a different product).
    }

    private installInteraction(): void {
        const { view } = this;

        this.nativeHandles.push(view.on('click', (event: any) => {
            const position = fromEsriPoint(this.mods, event.mapPoint);
            view.hitTest(event).then((response: any) => {
                for (const result of response.results || []) {
                    const graphic = result.graphic;
                    if (!graphic) continue;

                    const direct = this.graphicClicks.get(graphic);
                    if (direct) { direct(position); return; }

                    const layerHandler = this.layerClicks.get(graphic.layer);
                    if (layerHandler) { layerHandler(graphic, position); return; }
                }
                // Nothing was hit, so this is a bare map click — matches Google,
                // where a marker click does not also fire the map's click event.
                for (const emit of this.emitters.click) emit({ position });
            });
        }));

        // Dragging a graphic needs to know *before* the drag starts whether the
        // pointer is over a draggable, because stopPropagation() has to happen on
        // the very first drag event or the map pans away underneath. hitTest is
        // async, so the answer is precomputed on pointer-move.
        this.nativeHandles.push(view.on('pointer-move', (event: any) => {
            if (this.graphicDrags.size === 0 || this.dragging) return;
            view.hitTest(event).then((response: any) => {
                const hit = (response.results || [])
                    .map((r: any) => r.graphic)
                    .find((g: any) => g && this.graphicDrags.has(g));
                this.hoveredDraggable = hit ?? null;
                view.container.style.cursor = hit ? 'grab' : '';
            });
        }));

        this.nativeHandles.push(view.on('drag', (event: any) => {
            if (event.action === 'start') {
                const graphic = this.hoveredDraggable;
                const handler = graphic ? this.graphicDrags.get(graphic) : undefined;
                if (!graphic || !handler) return;
                this.dragging = { graphic, handler };
            }
            if (!this.dragging) return;

            event.stopPropagation();
            const point = view.toMap({ x: event.x, y: event.y });
            if (point) this.dragging.graphic.geometry = point;

            if (event.action === 'end') {
                const position = fromEsriPoint(this.mods, this.dragging.graphic.geometry);
                this.dragging.handler(position);
                this.dragging = null;
            }
        }));

        this.nativeHandles.push(this.mods.reactiveUtils.watch(
            () => view.stationary,
            (stationary: boolean) => {
                if (stationary) for (const emit of this.emitters.idle) emit(undefined);
            },
        ));
    }

    getCenter(): LatLng {
        return fromEsriPoint(this.mods, this.view.center);
    }

    setCenter(center: LatLng): void {
        this.whenReady(() => { this.view.center = toEsriPoint(this.mods, center); });
    }

    panTo(center: LatLng): void {
        this.whenReady(() => { this.view.goTo({ center: toEsriPoint(this.mods, center) }); });
    }

    getZoom(): number {
        return this.view.zoom ?? 0;
    }

    setZoom(zoom: number): void {
        this.whenReady(() => { this.view.zoom = zoom; });
    }

    getBounds(): LatLngBounds | null {
        return fromEsriExtent(this.mods, this.view.extent);
    }

    fitBounds(bounds: LatLngBounds, options?: FitBoundsOptions): void {
        this.whenReady(() => {
            let extent = toEsriExtent(this.mods, bounds);

            // view.goTo takes no padding argument (view.padding is a persistent
            // property that would shift every later camera move), so padding is
            // converted into an extent expansion instead.
            const padding = options?.padding ?? 0;
            if (padding > 0 && this.view.width > 2 * padding && this.view.height > 2 * padding) {
                const factor = Math.max(
                    this.view.width / (this.view.width - 2 * padding),
                    this.view.height / (this.view.height - 2 * padding),
                );
                extent = extent.expand(factor);
            }

            const result = this.view.goTo(extent);
            const maxZoom = options?.maxZoom;
            if (maxZoom === undefined) return;
            // A single-point bounds otherwise slams the camera to street level.
            Promise.resolve(result)
                .then(() => { if ((this.view.zoom ?? 0) > maxZoom) this.view.zoom = maxZoom; })
                .catch(() => { /* goTo rejects when superseded by another move */ });
        });
    }

    getBaseMapType(): BaseMapType {
        return this.baseMapType;
    }

    setBaseMapType(type: BaseMapType): void {
        if (type === this.baseMapType) return;
        this.baseMapType = type;
        this.view.map.basemap = this.basemapFor(type);
        for (const emit of this.emitters.basemaptypechange) emit({ type });
    }

    createMarkerLayer(options?: MarkerLayerOptions): MarkerLayer {
        const drop = (layer: MarkerLayer) => {
            const index = this.markerLayers.indexOf(layer);
            if (index >= 0) this.markerLayers.splice(index, 1);
        };
        const layer = options?.cluster
            ? new EsriClusterMarkerLayer(this.ctx, options.cluster, drop)
            : new EsriGraphicsMarkerLayer(this.ctx, drop);
        this.markerLayers.push(layer);
        return layer;
    }

    addMarker(options: MarkerOptions): MarkerHandle {
        if (!this.defaultMarkerLayer) this.defaultMarkerLayer = this.createMarkerLayer();
        return this.defaultMarkerLayer.addMarker(options);
    }

    addGeoJsonLayer(options: GeoJsonLayerOptions): GeoJsonLayerHandle {
        const layer = new EsriGeoJsonLayer(this.ctx, options, l => {
            const index = this.geoJsonLayers.indexOf(l);
            if (index >= 0) this.geoJsonLayers.splice(index, 1);
        });
        this.geoJsonLayers.push(layer);
        return layer;
    }

    addPolygon(options: PolygonOptions): PolygonHandle {
        const polygon = new EsriPolygon(this.ctx, options, p => {
            const index = this.polygons.indexOf(p);
            if (index >= 0) this.polygons.splice(index, 1);
        });
        this.polygons.push(polygon);
        return polygon;
    }

    createPopup(options?: PopupOptions): PopupHandle {
        const popup = new EsriPopup(this.ctx, options, p => {
            const index = this.popups.indexOf(p);
            if (index >= 0) this.popups.splice(index, 1);
        });
        this.popups.push(popup);
        return popup;
    }

    addCanvasOverlay(options: CanvasOverlayOptions): CanvasOverlayHandle | null {
        const overlay = createCanvasOverlay(this.ctx, options, o => {
            const index = this.overlays.indexOf(o);
            if (index >= 0) this.overlays.splice(index, 1);
        });
        this.overlays.push(overlay);
        return overlay;
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
        for (const overlay of [...this.overlays]) overlay.remove();
        for (const popup of [...this.popups]) popup.remove();
        for (const polygon of [...this.polygons]) polygon.remove();
        for (const layer of [...this.geoJsonLayers]) layer.remove();
        for (const layer of [...this.markerLayers]) layer.remove();
        this.defaultMarkerLayer = null;

        for (const handle of this.nativeHandles) handle?.remove?.();
        this.nativeHandles.length = 0;
        this.graphicClicks.clear();
        this.layerClicks.clear();
        this.graphicDrags.clear();
        this.emitters.click.length = 0;
        this.emitters.idle.length = 0;
        this.emitters.basemaptypechange.length = 0;

        this.view.destroy();
    }
}
