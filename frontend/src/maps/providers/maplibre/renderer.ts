/**
 * MapLibre GL adapter for the MapRenderer interface.
 *
 * Only this module (and its siblings in this directory) may touch maplibre-gl,
 * and only through `sdk.ml()` so the SDK stays in its own async chunk.
 *
 * Two structural differences from Google shape most of what follows:
 *
 *  1. MapLibre draws from *sources and layers described by a style document*,
 *     not from objects attached to a map. Clustering therefore lives in the
 *     source (`cluster: true`) and cluster bubbles are a symbol layer driven by
 *     a `step` expression — which is exactly what MarkerIcon-as-data buys us.
 *  2. `setStyle()` replaces the whole style, destroying every source, layer and
 *     runtime image. So switching base map type is not the cheap flag flip that
 *     `setBaseMapType()` looks like: everything source-backed has to be
 *     reattached afterwards. That is what the `attachments` list is for.
 */

import type {
    GeoJSONSource,
    IControl,
    Map as MlMap,
    MapMouseEvent,
    Marker as MlMarker,
    Popup as MlPopup,
    StyleSpecification,
} from 'maplibre-gl';

import {
    BaseMapType,
    CanvasOverlayHandle,
    CanvasOverlayOptions,
    ClusterOptions,
    ControlPosition,
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
import { ResolvedIcon, iconKey, iconOffset, loadImageElement, markerElement, parseFontSize, resolveIcon } from './icons';
import { ml } from './sdk';
import { BaseMapStyle, MapLibreProviderOptions, availableBaseMapTypes, resolveStyles } from './styles';

/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Static, config-independent capabilities for the factory. The *instance*
 * capabilities can be narrower: which base map types exist depends entirely on
 * which style URLs a town configured, so MapLibreRenderer recomputes
 * `baseMapTypes` per map. 'hybrid' is absent here because there is no free
 * imagery-plus-labels style to default to (see styles.ts).
 */
export const MAPLIBRE_CAPABILITIES: MapCapabilities = {
    canvasOverlay: true,
    clustering: true,
    tilt: true,
    rotation: true,
    baseMapTypes: ['roadmap', 'satellite', 'terrain'],
};

type Corner = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

/**
 * MapLibre only has four control slots, so the interface's twelve positions
 * collapse to the nearest corner. Callers asking for 'top-center' get top-left
 * rather than nothing.
 */
const CORNERS: Record<ControlPosition, Corner> = {
    'top-left': 'top-left',
    'top-center': 'top-left',
    'top-right': 'top-right',
    'left-top': 'top-left',
    'left-center': 'top-left',
    'left-bottom': 'bottom-left',
    'right-top': 'top-right',
    'right-center': 'top-right',
    'right-bottom': 'bottom-right',
    'bottom-left': 'bottom-left',
    'bottom-center': 'bottom-left',
    'bottom-right': 'bottom-right',
};

function corner(position: ControlPosition | undefined, fallback: Corner): Corner {
    return position ? CORNERS[position] : fallback;
}

/** Cluster sizes the caller's `style(count)` function is sampled at. */
const CLUSTER_BREAKS = [1, 10, 25, 50, 100, 250, 500, 1000];

interface Attachment {
    /** Rebuild sources/layers after a style swap. */
    reattach(): void;
}

let uid = 0;
const nextId = (prefix: string) => `pp-${prefix}-${++uid}`;

function toBounds(map: MlMap): LatLngBounds | null {
    const bounds = map.getBounds();
    if (!bounds) return null;
    return {
        south: bounds.getSouth(),
        west: bounds.getWest(),
        north: bounds.getNorth(),
        east: bounds.getEast(),
    };
}

function geoFeatureOf(feature: any): GeoFeature {
    const geometryType = (feature?.geometry?.type || 'Point') as GeometryType;
    let position: LatLng | null = null;
    if (geometryType === 'Point' && Array.isArray(feature?.geometry?.coordinates)) {
        position = { lat: feature.geometry.coordinates[1], lng: feature.geometry.coordinates[0] };
    }
    return { geometryType, properties: (feature?.properties || {}) as Record<string, unknown>, position };
}

function toFeatureCollection(data: object): any {
    const gj = data as any;
    if (gj?.type === 'FeatureCollection') return { ...gj, features: [...(gj.features || [])] };
    if (gj?.type === 'Feature') return { type: 'FeatureCollection', features: [gj] };
    if (gj?.type) return { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: gj, properties: {} }] };
    return { type: 'FeatureCollection', features: [] };
}

// ---------------------------------------------------------------------------
// Markers
// ---------------------------------------------------------------------------

/**
 * DOM-backed marker, used by *unclustered* layers only.
 *
 * To be explicit, because the interface asked the question: MarkerIcon as data
 * is entirely sufficient for the clustered path below — no DOM needed there.
 * DOM markers survive here because MarkerOptions also carries `draggable`,
 * `onDragEnd` and `dropAnimation`, and a symbol layer over a GeoJSON source has
 * no notion of dragging a single feature. Reimplementing drag by hand on top of
 * queryRenderedFeatures would be worse code for the one call site that needs it
 * (the location picker's single pin).
 */
class DomMarker implements MarkerHandle {
    readonly native: MlMarker;
    private position: LatLng;

    constructor(
        map: MlMap,
        private readonly options: MarkerOptions,
        private readonly onRemove: (m: DomMarker) => void,
    ) {
        this.position = options.position;
        const content = markerElement(options.icon, options.label, options.title);
        if (options.zIndex !== undefined) content.element.style.zIndex = String(options.zIndex);
        if (options.dropAnimation) {
            // Cosmetic only; MapLibre has no drop animation of its own.
            content.element.animate(
                [{ transform: 'translateY(-24px)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1 }],
                { duration: 300, easing: 'cubic-bezier(0.2, 0.8, 0.3, 1)' },
            );
        }

        this.native = new (ml().Marker)({
            element: content.element,
            offset: content.offset,
            draggable: options.draggable ?? false,
        })
            .setLngLat([options.position.lng, options.position.lat])
            .addTo(map);

        if (options.onClick) {
            content.element.addEventListener('click', event => {
                event.stopPropagation();
                options.onClick!({ position: this.getPosition() }, this);
            });
        }
        if (options.onDragEnd) {
            this.native.on('dragend', () => {
                const lngLat = this.native.getLngLat();
                this.position = { lat: lngLat.lat, lng: lngLat.lng };
                options.onDragEnd!(this.position);
            });
        }
    }

    getPosition(): LatLng {
        const lngLat = this.native.getLngLat();
        return { lat: lngLat.lat, lng: lngLat.lng };
    }

    setPosition(position: LatLng): void {
        this.position = position;
        this.native.setLngLat([position.lng, position.lat]);
    }

    setIcon(icon: MarkerIcon): void {
        // Marker.setElement does not exist, so rebuild the node in place.
        const content = markerElement(icon, this.options.label, this.options.title);
        const element = this.native.getElement();
        element.replaceChildren(...Array.from(content.element.childNodes));
        this.native.setOffset(content.offset);
    }

    setVisible(visible: boolean): void {
        this.native.getElement().style.display = visible ? '' : 'none';
    }

    remove(): void {
        this.native.remove();
        this.onRemove(this);
    }
}

class DomMarkerLayer implements MarkerLayer {
    private markers: DomMarker[] = [];
    private visible = true;
    private removed = false;

    constructor(
        private readonly map: MlMap,
        private readonly onRemove: (layer: DomMarkerLayer) => void,
    ) { }

    setMarkers(markers: MarkerOptions[]): MarkerHandle[] {
        this.clear();
        if (this.removed) return [];
        this.markers = markers.map(options => this.build(options));
        return [...this.markers];
    }

    addMarker(marker: MarkerOptions): MarkerHandle {
        const handle = this.build(marker);
        this.markers.push(handle);
        return handle;
    }

    private build(options: MarkerOptions): DomMarker {
        const marker = new DomMarker(this.map, options, m => {
            this.markers = this.markers.filter(existing => existing !== m);
        });
        if (!this.visible) marker.setVisible(false);
        return marker;
    }

    clear(): void {
        for (const marker of [...this.markers]) marker.remove();
        this.markers = [];
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        for (const marker of this.markers) marker.setVisible(visible);
    }

    remove(): void {
        this.clear();
        this.removed = true;
        this.onRemove(this);
    }
}

interface ClusterEntry {
    id: number;
    position: LatLng;
    icon?: MarkerIcon;
    iconKey: string | null;
    label?: MarkerOptions['label'];
    title?: string;
    zIndex?: number;
    hidden: boolean;
    onClick?: MarkerOptions['onClick'];
    handle: SourceMarker;
}

class SourceMarker implements MarkerHandle {
    constructor(private readonly layer: SourceMarkerLayer, private readonly entryId: number) { }

    private entry(): ClusterEntry | undefined {
        return this.layer.entry(this.entryId);
    }

    getPosition(): LatLng {
        return this.entry()?.position ?? { lat: 0, lng: 0 };
    }

    setPosition(position: LatLng): void {
        const entry = this.entry();
        if (!entry) return;
        entry.position = position;
        this.layer.sync();
    }

    setIcon(icon: MarkerIcon): void {
        this.layer.setEntryIcon(this.entryId, icon);
    }

    setVisible(visible: boolean): void {
        const entry = this.entry();
        if (!entry) return;
        // A source-backed marker has no element to hide, so it is filtered out
        // of the layer instead — same observable effect, no feature churn.
        entry.hidden = !visible;
        this.layer.sync();
    }

    remove(): void {
        this.layer.removeEntry(this.entryId);
    }
}

/**
 * Clustered marker layer: one GeoJSON source with `cluster: true`, one symbol
 * layer for cluster bubbles and one for individual pins. No DOM markers, no
 * external clustering package, and the caller's `ClusterOptions.style` function
 * is honoured by sampling it at CLUSTER_BREAKS and folding the results into a
 * `step` expression.
 */
class SourceMarkerLayer implements MarkerLayer {
    private readonly sourceId = nextId('src');
    private readonly pointLayerId = nextId('pts');
    private readonly clusterLayerId = nextId('cls');
    private readonly clusterTextLayerId = nextId('clt');

    private entries = new Map<number, ClusterEntry>();
    private order: number[] = [];
    private nextEntryId = 1;
    private visible = true;
    private removed = false;
    private ready: Promise<void>;
    private subscriptions: { unsubscribe: () => void }[] = [];

    constructor(
        private readonly map: MlMap,
        private readonly cluster: ClusterOptions,
        private readonly ensureImage: (icon: MarkerIcon) => Promise<string>,
        private readonly onRemove: (layer: SourceMarkerLayer) => void,
    ) {
        this.ready = this.attach();
    }

    entry(id: number): ClusterEntry | undefined {
        return this.entries.get(id);
    }

    /** Called by the renderer after a style swap wipes every source and layer. */
    reattach(): void {
        this.ready = this.attach();
    }

    private async attach(): Promise<void> {
        for (const subscription of this.subscriptions) subscription.unsubscribe();
        this.subscriptions = [];

        // Cluster bubbles are ordinary sprite images: sample the caller's style
        // function once per breakpoint and register the results up front so the
        // step expression below can name them.
        const specs = CLUSTER_BREAKS.map(count => this.cluster.style(count));
        const keys = await Promise.all(specs.map(spec => this.ensureImage(spec.icon)));
        if (this.removed || !this.map.getContainer()) return;

        const iconStep: any[] = ['step', ['get', 'point_count'], keys[0]];
        for (let i = 1; i < CLUSTER_BREAKS.length; i++) iconStep.push(CLUSTER_BREAKS[i], keys[i]);

        // If every sampled label is just the count rendered as text (which is
        // what every caller actually does), read the live count instead of the
        // sampled string — otherwise a cluster of 37 would be labelled "25".
        const labelsAreCounts = specs.every((spec, i) => spec.label?.text === String(CLUSTER_BREAKS[i]));
        let textField: any = ['to-string', ['get', 'point_count']];
        if (!labelsAreCounts) {
            const step: any[] = ['step', ['get', 'point_count'], specs[0].label?.text ?? ''];
            for (let i = 1; i < CLUSTER_BREAKS.length; i++) step.push(CLUSTER_BREAKS[i], specs[i].label?.text ?? '');
            textField = step;
        }
        const labelStyle = specs[specs.length - 1].label;

        if (!this.map.getSource(this.sourceId)) {
            this.map.addSource(this.sourceId, {
                type: 'geojson',
                data: this.collection(),
                cluster: true,
                clusterRadius: 50,
                clusterMaxZoom: 16,
            } as any);
        }

        this.map.addLayer({
            id: this.clusterLayerId,
            type: 'symbol',
            source: this.sourceId,
            filter: ['has', 'point_count'],
            layout: {
                'icon-image': iconStep,
                'icon-allow-overlap': true,
                'icon-ignore-placement': true,
                visibility: this.visible ? 'visible' : 'none',
            },
        } as any);

        this.map.addLayer({
            id: this.clusterTextLayerId,
            type: 'symbol',
            source: this.sourceId,
            filter: ['has', 'point_count'],
            layout: {
                'text-field': textField,
                'text-size': parseFontSize(labelStyle?.fontSize, 12),
                'text-allow-overlap': true,
                'text-ignore-placement': true,
                visibility: this.visible ? 'visible' : 'none',
            },
            paint: { 'text-color': labelStyle?.color ?? '#ffffff' },
        } as any);

        this.map.addLayer({
            id: this.pointLayerId,
            type: 'symbol',
            source: this.sourceId,
            filter: ['all', ['!', ['has', 'point_count']], ['!=', ['get', '__hidden'], true]],
            layout: {
                'icon-image': ['coalesce', ['get', '__icon'], ''],
                'icon-offset': ['array', 'number', 2, ['coalesce', ['get', '__offset'], ['literal', [0, 0]]]],
                'icon-allow-overlap': true,
                'icon-ignore-placement': true,
                // Symbols with a *lower* sort key draw on top, so invert zIndex.
                'symbol-sort-key': ['*', -1, ['to-number', ['coalesce', ['get', '__z'], 0]]],
                'text-field': ['coalesce', ['get', '__label'], ''],
                'text-size': ['to-number', ['coalesce', ['get', '__labelSize'], 12]],
                'text-allow-overlap': true,
                'text-ignore-placement': true,
                visibility: this.visible ? 'visible' : 'none',
            },
            paint: { 'text-color': ['coalesce', ['get', '__labelColor'], '#ffffff'] },
        } as any);

        this.subscriptions.push(
            this.map.on('click', this.pointLayerId, (event: any) => {
                const id = event.features?.[0]?.properties?.__id;
                const entry = id !== undefined ? this.entries.get(Number(id)) : undefined;
                if (!entry?.onClick) return;
                event.originalEvent?.stopPropagation?.();
                entry.onClick(({ position: entry.position }), entry.handle);
            }),
            this.map.on('click', this.clusterLayerId, (event: any) => {
                // Zooming a cluster open is the universally expected behaviour
                // and the interface has no hook to delegate it to the caller.
                const clusterId = event.features?.[0]?.properties?.cluster_id;
                if (clusterId === undefined) return;
                const source = this.map.getSource(this.sourceId) as GeoJSONSource | undefined;
                void source?.getClusterExpansionZoom(clusterId).then(zoom => {
                    this.map.easeTo({ center: event.lngLat, zoom });
                });
            }),
        );

        this.applyData();
    }

    private collection(): any {
        return {
            type: 'FeatureCollection',
            features: this.order.map(id => this.entries.get(id)).filter(Boolean).map(entry => ({
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [entry!.position.lng, entry!.position.lat] },
                properties: {
                    __id: entry!.id,
                    __icon: entry!.iconKey,
                    __offset: entry!.iconKey ? this.offsets.get(entry!.iconKey) ?? [0, 0] : [0, 0],
                    __z: entry!.zIndex ?? 0,
                    __hidden: entry!.hidden,
                    __label: entry!.label?.text ?? '',
                    __labelColor: entry!.label?.color ?? '#ffffff',
                    __labelSize: parseFontSize(entry!.label?.fontSize, 12),
                    __title: entry!.title ?? '',
                },
            })),
        };
    }

    /** Icon key -> pixel offset, filled in as icons resolve. */
    private offsets = new Map<string, [number, number]>();

    setOffset(key: string, offset: [number, number]): void {
        this.offsets.set(key, offset);
    }

    private applyData(): void {
        const source = this.map.getSource(this.sourceId) as GeoJSONSource | undefined;
        source?.setData(this.collection());
    }

    sync(): void {
        void this.ready.then(() => {
            if (!this.removed) this.applyData();
        });
    }

    private async resolveEntryIcon(entry: ClusterEntry, icon: MarkerIcon): Promise<void> {
        const key = await this.ensureImage(icon);
        if (this.removed || !this.entries.has(entry.id)) return;
        entry.icon = icon;
        entry.iconKey = key;
        this.applyData();
    }

    setEntryIcon(id: number, icon: MarkerIcon): void {
        const entry = this.entries.get(id);
        if (!entry) return;
        void this.ready.then(() => this.resolveEntryIcon(entry, icon));
    }

    removeEntry(id: number): void {
        if (!this.entries.delete(id)) return;
        this.order = this.order.filter(existing => existing !== id);
        this.sync();
    }

    private build(options: MarkerOptions): ClusterEntry {
        const id = this.nextEntryId++;
        const entry: ClusterEntry = {
            id,
            position: options.position,
            icon: options.icon,
            iconKey: null,
            label: options.label,
            title: options.title,
            zIndex: options.zIndex,
            hidden: false,
            onClick: options.onClick,
            handle: undefined as unknown as SourceMarker,
        };
        entry.handle = new SourceMarker(this, id);
        this.entries.set(id, entry);
        this.order.push(id);

        if (options.draggable || options.onDragEnd) {
            // Honest failure rather than a silently inert pin: dragging one
            // feature out of a clustered source is not something MapLibre can
            // express. Callers that need it must use an unclustered layer.
            console.warn('MapLibre: draggable markers are not supported inside a clustered marker layer');
        }
        if (options.icon) void this.ready.then(() => this.resolveEntryIcon(entry, options.icon!));
        return entry;
    }

    setMarkers(markers: MarkerOptions[]): MarkerHandle[] {
        this.entries.clear();
        this.order = [];
        const handles = markers.map(options => this.build(options).handle);
        this.sync();
        return handles;
    }

    addMarker(marker: MarkerOptions): MarkerHandle {
        const entry = this.build(marker);
        this.sync();
        return entry.handle;
    }

    clear(): void {
        this.entries.clear();
        this.order = [];
        this.sync();
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        void this.ready.then(() => {
            if (this.removed) return;
            for (const layerId of [this.clusterLayerId, this.clusterTextLayerId, this.pointLayerId]) {
                if (this.map.getLayer(layerId)) {
                    this.map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
                }
            }
        });
    }

    remove(): void {
        this.removed = true;
        for (const subscription of this.subscriptions) subscription.unsubscribe();
        this.subscriptions = [];
        for (const layerId of [this.clusterLayerId, this.clusterTextLayerId, this.pointLayerId]) {
            if (this.map.getLayer(layerId)) this.map.removeLayer(layerId);
        }
        if (this.map.getSource(this.sourceId)) this.map.removeSource(this.sourceId);
        this.entries.clear();
        this.order = [];
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// GeoJSON / polygons
// ---------------------------------------------------------------------------

const DEFAULT_VECTOR_STYLE: Required<Pick<VectorStyle, 'fillColor' | 'fillOpacity' | 'strokeColor' | 'strokeOpacity' | 'strokeWidth'>> = {
    fillColor: '#3388ff',
    fillOpacity: 0.2,
    strokeColor: '#3388ff',
    strokeOpacity: 1,
    strokeWidth: 2,
};

/**
 * A GeoJSON layer is a source plus a fill/line/circle layer triple.
 *
 * `style` may be a per-feature function, which no MapLibre paint expression can
 * call. The resolution is to evaluate it here and bake the result into each
 * feature's properties, then have every paint property read those properties.
 * One code path covers both the static and the functional case.
 */
class MapLibreGeoJsonLayer implements GeoJsonLayerHandle, Attachment {
    private readonly sourceId = nextId('gjs');
    private readonly fillId = nextId('gjf');
    private readonly lineId = nextId('gjl');
    private readonly circleId = nextId('gjc');

    private collection: any;
    private style: VectorStyle | ((feature: GeoFeature) => VectorStyle);
    private visible = true;
    private subscriptions: { unsubscribe: () => void }[] = [];

    constructor(
        private readonly map: MlMap,
        private readonly options: GeoJsonLayerOptions,
        private readonly onRemove: (layer: MapLibreGeoJsonLayer) => void,
    ) {
        this.collection = toFeatureCollection(options.data);
        this.style = options.style ?? {};
        this.bake();
        this.attach();
    }

    private bake(): void {
        this.collection = {
            ...this.collection,
            features: (this.collection.features || []).map((feature: any) => {
                const info = geoFeatureOf(feature);
                const style = typeof this.style === 'function' ? this.style(info) : this.style;
                return {
                    ...feature,
                    properties: {
                        ...(feature.properties || {}),
                        __fill: style.fillColor ?? DEFAULT_VECTOR_STYLE.fillColor,
                        __fillOpacity: style.fillOpacity ?? DEFAULT_VECTOR_STYLE.fillOpacity,
                        __stroke: style.strokeColor ?? DEFAULT_VECTOR_STYLE.strokeColor,
                        __strokeOpacity: style.strokeOpacity ?? DEFAULT_VECTOR_STYLE.strokeOpacity,
                        __strokeWidth: style.strokeWidth ?? DEFAULT_VECTOR_STYLE.strokeWidth,
                        __visible: style.visible !== false,
                        __clickable: style.clickable !== false,
                    },
                };
            }),
        };
    }

    reattach(): void {
        this.attach();
    }

    private attach(): void {
        for (const subscription of this.subscriptions) subscription.unsubscribe();
        this.subscriptions = [];

        if (!this.map.getSource(this.sourceId)) {
            this.map.addSource(this.sourceId, { type: 'geojson', data: this.collection } as any);
        }

        const visibility = this.visible ? 'visible' : 'none';
        const visibleFilter: any = ['!=', ['get', '__visible'], false];

        this.map.addLayer({
            id: this.fillId,
            type: 'fill',
            source: this.sourceId,
            filter: ['all', visibleFilter, ['match', ['geometry-type'], ['Polygon'], true, false]],
            layout: { visibility },
            paint: {
                'fill-color': ['to-color', ['get', '__fill']],
                'fill-opacity': ['to-number', ['get', '__fillOpacity']],
            },
        } as any);

        this.map.addLayer({
            id: this.lineId,
            type: 'line',
            source: this.sourceId,
            filter: ['all', visibleFilter, ['match', ['geometry-type'], ['LineString', 'Polygon'], true, false]],
            layout: { visibility, 'line-join': 'round', 'line-cap': 'round' },
            paint: {
                'line-color': ['to-color', ['get', '__stroke']],
                'line-opacity': ['to-number', ['get', '__strokeOpacity']],
                'line-width': ['to-number', ['get', '__strokeWidth']],
            },
        } as any);

        // 'hidden' means the caller draws its own markers for point features.
        if (this.options.pointRendering !== 'hidden') {
            this.map.addLayer({
                id: this.circleId,
                type: 'circle',
                source: this.sourceId,
                filter: ['all', visibleFilter, ['match', ['geometry-type'], ['Point'], true, false]],
                layout: { visibility },
                paint: {
                    'circle-color': ['to-color', ['get', '__fill']],
                    'circle-opacity': ['to-number', ['get', '__fillOpacity']],
                    'circle-radius': 6,
                    'circle-stroke-color': ['to-color', ['get', '__stroke']],
                    'circle-stroke-width': ['to-number', ['get', '__strokeWidth']],
                },
            } as any);
        }

        if (this.options.onFeatureClick) {
            const layers = this.layerIds();
            this.subscriptions.push(this.map.on('click', layers, (event: any) => {
                const feature = event.features?.[0];
                if (!feature || feature.properties?.__clickable === false) return;
                this.options.onFeatureClick!(geoFeatureOf(feature), {
                    position: { lat: event.lngLat.lat, lng: event.lngLat.lng },
                });
            }));
        }
    }

    private layerIds(): string[] {
        return [this.fillId, this.lineId, this.circleId].filter(id => this.map.getLayer(id));
    }

    setStyle(style: VectorStyle | ((feature: GeoFeature) => VectorStyle)): void {
        this.style = style;
        this.bake();
        const source = this.map.getSource(this.sourceId) as GeoJSONSource | undefined;
        source?.setData(this.collection);
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        for (const id of this.layerIds()) {
            this.map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
        }
    }

    remove(): void {
        for (const subscription of this.subscriptions) subscription.unsubscribe();
        this.subscriptions = [];
        for (const id of this.layerIds()) this.map.removeLayer(id);
        if (this.map.getSource(this.sourceId)) this.map.removeSource(this.sourceId);
        this.onRemove(this);
    }
}

/** A polygon is just a one-feature GeoJSON layer; no separate vendor object exists. */
class MapLibrePolygon implements PolygonHandle {
    private layer: MapLibreGeoJsonLayer;

    constructor(
        map: MlMap,
        options: PolygonOptions,
        register: (layer: MapLibreGeoJsonLayer) => void,
        private readonly onRemove: (polygon: MapLibrePolygon) => void,
    ) {
        const coordinates = options.paths.map(ring => ring.map(point => [point.lng, point.lat]));
        this.layer = new MapLibreGeoJsonLayer(map, {
            data: { type: 'Polygon', coordinates },
            style: options.style ?? {},
            onFeatureClick: options.onClick ? (_feature, event) => options.onClick!(event) : undefined,
        }, () => { });
        register(this.layer);
    }

    setStyle(style: VectorStyle): void {
        this.layer.setStyle(style);
    }

    setVisible(visible: boolean): void {
        this.layer.setVisible(visible);
    }

    remove(): void {
        this.layer.remove();
        this.onRemove(this);
    }
}

class MapLibrePopup implements PopupHandle {
    private popup: MlPopup;
    private open = false;

    constructor(
        private readonly map: MlMap,
        options: PopupOptions | undefined,
        private readonly onRemove: (popup: MapLibrePopup) => void,
    ) {
        this.popup = new (ml().Popup)({ closeButton: true, closeOnClick: false, maxWidth: '320px' });
        if (options?.content) this.setContent(options.content);
        this.popup.on('close', () => { this.open = false; });
    }

    setContent(content: string | HTMLElement): void {
        if (typeof content === 'string') this.popup.setHTML(content);
        else this.popup.setDOMContent(content);
    }

    openAt(anchor: MarkerHandle | LatLng): void {
        const position = 'getPosition' in anchor ? anchor.getPosition() : anchor;
        this.popup.setLngLat([position.lng, position.lat]);
        if (!this.open) {
            this.popup.addTo(this.map);
            this.open = true;
        }
    }

    close(): void {
        this.popup.remove();
        this.open = false;
    }

    remove(): void {
        this.close();
        this.onRemove(this);
    }
}

/**
 * Canvas overlay: an absolutely positioned canvas inside the map's canvas
 * container (the same element markers live in, so z-order comes out right) and
 * `map.project` for the projection. Redrawn on every camera frame.
 */
function createCanvasOverlay(
    map: MlMap,
    options: CanvasOverlayOptions,
    onRemove: (overlay: CanvasOverlayHandle) => void,
): CanvasOverlayHandle {
    const canvas = document.createElement('canvas');
    canvas.style.position = 'absolute';
    canvas.style.left = '0';
    canvas.style.top = '0';
    canvas.style.pointerEvents = 'none';
    map.getCanvasContainer().appendChild(canvas);

    let removed = false;

    const render = (): void => {
        if (removed) return;
        const container = map.getContainer();
        const width = container.clientWidth;
        const height = container.clientHeight;
        if (width <= 0 || height <= 0) return;

        const ratio = window.devicePixelRatio || 1;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
            canvas.width = Math.round(width * ratio);
            canvas.height = Math.round(height * ratio);
        }

        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, width, height);

        const bounds = toBounds(map);
        if (!bounds) return;

        const view: OverlayViewport = {
            width,
            height,
            bounds,
            zoom: map.getZoom(),
            project: position => {
                const point = map.project([position.lng, position.lat]);
                return { x: point.x, y: point.y };
            },
        };
        options.draw(ctx, view);
    };

    const subscriptions = [
        map.on('move', render),
        map.on('resize', render),
        map.on('load', render),
    ];
    render();

    const handle: CanvasOverlayHandle = {
        redraw: render,
        remove: () => {
            removed = true;
            for (const subscription of subscriptions) subscription.unsubscribe();
            canvas.remove();
            onRemove(handle);
        },
    };
    return handle;
}

/**
 * MapLibre ships no base map switcher, so this is a small custom IControl. It
 * exists because the interface offers `controls.baseMapSwitcher` and silently
 * dropping it would be worse than 30 lines of buttons.
 */
class BaseMapSwitcherControl implements IControl {
    private container: HTMLElement | null = null;
    private buttons = new Map<BaseMapType, HTMLButtonElement>();

    constructor(
        private readonly types: BaseMapType[],
        private readonly current: () => BaseMapType,
        private readonly select: (type: BaseMapType) => void,
    ) { }

    onAdd(): HTMLElement {
        const container = document.createElement('div');
        container.className = 'maplibregl-ctrl maplibregl-ctrl-group';
        container.style.display = 'flex';
        for (const type of this.types) {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = type === 'roadmap' ? 'Map' : type[0].toUpperCase() + type.slice(1);
            button.style.padding = '0 8px';
            button.style.width = 'auto';
            button.addEventListener('click', () => {
                this.select(type);
                this.refresh();
            });
            this.buttons.set(type, button);
            container.appendChild(button);
        }
        this.container = container;
        this.refresh();
        return container;
    }

    refresh(): void {
        const active = this.current();
        for (const [type, button] of this.buttons) {
            button.style.fontWeight = type === active ? '700' : '400';
        }
    }

    onRemove(): void {
        this.container?.remove();
        this.container = null;
        this.buttons.clear();
    }
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

export class MapLibreRenderer implements MapRenderer {
    readonly providerId: MapProviderId = 'maplibre';
    readonly capabilities: MapCapabilities;

    private map: MlMap;
    private styles: Partial<Record<BaseMapType, BaseMapStyle>>;
    private baseMapType: BaseMapType;
    private pixelRatio = Math.min(2, Math.round(window.devicePixelRatio || 1));

    private images = new Map<string, ResolvedIcon>();
    private imagePromises = new Map<string, Promise<string>>();

    private markerLayers: MarkerLayer[] = [];
    private geoJsonLayers: MapLibreGeoJsonLayer[] = [];
    private polygons: MapLibrePolygon[] = [];
    private popups: MapLibrePopup[] = [];
    private overlays: CanvasOverlayHandle[] = [];
    private attachments: Attachment[] = [];
    private subscriptions: { unsubscribe: () => void }[] = [];
    private baseMapListeners: ((type: BaseMapType) => void)[] = [];
    private switcher: BaseMapSwitcherControl | null = null;
    private defaultMarkerLayer: DomMarkerLayer | null = null;
    private destroyed = false;

    constructor(container: HTMLElement, providerOptions: MapLibreProviderOptions, options: MapInitOptions) {
        this.styles = resolveStyles(providerOptions, options.styleId);
        const available = availableBaseMapTypes(this.styles);
        this.capabilities = { ...MAPLIBRE_CAPABILITIES, baseMapTypes: available };

        const requested = options.baseMapType ?? 'roadmap';
        this.baseMapType = available.includes(requested) ? requested : (available[0] ?? 'roadmap');

        const maplibre = ml();
        this.map = new maplibre.Map({
            container,
            style: (this.styles[this.baseMapType] ?? this.styles.roadmap ?? { version: 8, sources: {}, layers: [] }) as StyleSpecification | string,
            center: [options.center?.lng ?? 0, options.center?.lat ?? 0],
            zoom: options.zoom ?? 1,
            bearing: options.heading ?? 0,
            pitch: options.tilt ?? 0,
            ...(options.vendorOptions as any),
        });

        const controls = options.controls ?? {};
        if (controls.zoom?.enabled || controls.rotate?.enabled) {
            this.map.addControl(
                new maplibre.NavigationControl({
                    showZoom: controls.zoom?.enabled ?? false,
                    showCompass: controls.rotate?.enabled ?? false,
                    visualizePitch: controls.rotate?.enabled ?? false,
                }),
                corner(controls.zoom?.position ?? controls.rotate?.position, 'top-right'),
            );
        }
        if (controls.fullscreen?.enabled) {
            this.map.addControl(new maplibre.FullscreenControl({}), corner(controls.fullscreen.position, 'top-right'));
        }
        if (controls.baseMapSwitcher?.enabled) {
            const types = (controls.baseMapSwitcher.types ?? available).filter(type => available.includes(type));
            if (types.length > 1) {
                this.switcher = new BaseMapSwitcherControl(
                    types,
                    () => this.baseMapType,
                    type => this.setBaseMapType(type),
                );
                this.map.addControl(this.switcher, corner(controls.baseMapSwitcher.position, 'top-left'));
            }
        }
        // controls.streetView is Google-only and has no MapLibre equivalent; the
        // interface says providers without a street-level mode ignore it.
    }

    /** Resolve a MarkerIcon to a registered sprite id, once per distinct icon. */
    private ensureImage = (icon: MarkerIcon): Promise<string> => {
        const key = iconKey(icon, this.pixelRatio);
        let pending = this.imagePromises.get(key);
        if (!pending) {
            pending = this.registerImage(icon, key);
            this.imagePromises.set(key, pending);
        }
        return pending;
    };

    private async registerImage(icon: MarkerIcon, key: string): Promise<string> {
        const resolved = await resolveIcon(icon, this.pixelRatio);
        this.images.set(key, resolved);
        for (const layer of this.markerLayers) {
            if (layer instanceof SourceMarkerLayer) layer.setOffset(key, iconOffset(resolved));
        }
        await this.addImage(resolved);
        return key;
    }

    private async addImage(resolved: ResolvedIcon): Promise<void> {
        if (this.destroyed || this.map.hasImage(resolved.key)) return;
        try {
            const element = await loadImageElement(resolved.url);
            if (this.destroyed || this.map.hasImage(resolved.key)) return;
            this.map.addImage(resolved.key, element, { pixelRatio: resolved.pixelRatio });
        } catch (error) {
            console.warn('MapLibre: failed to register marker image', error);
        }
    }

    getCenter(): LatLng {
        const center = this.map.getCenter();
        return { lat: center.lat, lng: center.lng };
    }

    setCenter(center: LatLng): void {
        this.map.setCenter([center.lng, center.lat]);
    }

    panTo(center: LatLng): void {
        this.map.panTo([center.lng, center.lat]);
    }

    getZoom(): number {
        return this.map.getZoom();
    }

    setZoom(zoom: number): void {
        this.map.setZoom(zoom);
    }

    getBounds(): LatLngBounds | null {
        return toBounds(this.map);
    }

    fitBounds(bounds: LatLngBounds, options?: FitBoundsOptions): void {
        this.map.fitBounds(
            [[bounds.west, bounds.south], [bounds.east, bounds.north]],
            { padding: options?.padding ?? 0, maxZoom: options?.maxZoom },
        );
    }

    getBaseMapType(): BaseMapType {
        return this.baseMapType;
    }

    setBaseMapType(type: BaseMapType): void {
        if (type === this.baseMapType) return;
        const style = this.styles[type];
        if (!style) {
            // Not configured (normally 'hybrid'). Reported through
            // capabilities.baseMapTypes; substituting another style silently
            // would be worse than doing nothing.
            console.warn(`MapLibre: no style configured for base map type "${type}"`);
            return;
        }

        this.baseMapType = type;
        this.map.setStyle(style as StyleSpecification | string);

        // setStyle wipes sources, layers and runtime images. Everything
        // source-backed has to be rebuilt once the new style is in place.
        this.map.once('styledata', () => {
            if (this.destroyed) return;
            for (const resolved of this.images.values()) void this.addImage(resolved);
            for (const attachment of this.attachments) attachment.reattach();
            this.switcher?.refresh();
            for (const listener of this.baseMapListeners) listener(type);
        });
    }

    createMarkerLayer(options?: MarkerLayerOptions): MarkerLayer {
        const layer: MarkerLayer = options?.cluster
            ? new SourceMarkerLayer(this.map, options.cluster, this.ensureImage, l => this.forget(l))
            : new DomMarkerLayer(this.map, l => this.forget(l));

        this.markerLayers.push(layer);
        if (layer instanceof SourceMarkerLayer) this.attachments.push(layer);
        return layer;
    }

    private forget(layer: MarkerLayer): void {
        this.markerLayers = this.markerLayers.filter(existing => existing !== layer);
        this.attachments = this.attachments.filter(existing => existing !== (layer as unknown as Attachment));
    }

    addMarker(options: MarkerOptions): MarkerHandle {
        if (!this.defaultMarkerLayer) {
            this.defaultMarkerLayer = this.createMarkerLayer() as DomMarkerLayer;
        }
        return this.defaultMarkerLayer.addMarker(options);
    }

    addGeoJsonLayer(options: GeoJsonLayerOptions): GeoJsonLayerHandle {
        const layer = new MapLibreGeoJsonLayer(this.map, options, l => {
            this.geoJsonLayers = this.geoJsonLayers.filter(existing => existing !== l);
            this.attachments = this.attachments.filter(existing => existing !== l);
        });
        this.geoJsonLayers.push(layer);
        this.attachments.push(layer);
        return layer;
    }

    addPolygon(options: PolygonOptions): PolygonHandle {
        const polygon = new MapLibrePolygon(
            this.map,
            options,
            layer => this.attachments.push(layer),
            p => { this.polygons = this.polygons.filter(existing => existing !== p); },
        );
        this.polygons.push(polygon);
        return polygon;
    }

    createPopup(options?: PopupOptions): PopupHandle {
        const popup = new MapLibrePopup(this.map, options, p => {
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

        if (event === 'basemaptypechange') {
            // Not a MapLibre event: the base map is our own concept here, so the
            // renderer emits it from setBaseMapType.
            const listener = (type: BaseMapType) => emit({ type });
            this.baseMapListeners.push(listener);
            return () => {
                this.baseMapListeners = this.baseMapListeners.filter(existing => existing !== listener);
            };
        }

        const subscription = event === 'click'
            ? this.map.on('click', (e: MapMouseEvent) => emit({ position: { lat: e.lngLat.lat, lng: e.lngLat.lng } }))
            : this.map.on('idle', () => emit(undefined));

        this.subscriptions.push(subscription);
        return () => {
            subscription.unsubscribe();
            this.subscriptions = this.subscriptions.filter(existing => existing !== subscription);
        };
    }

    destroy(): void {
        this.destroyed = true;
        for (const subscription of this.subscriptions) subscription.unsubscribe();
        this.subscriptions = [];
        this.baseMapListeners = [];
        for (const overlay of [...this.overlays]) overlay.remove();
        for (const popup of [...this.popups]) popup.remove();
        for (const layer of [...this.markerLayers]) layer.remove();
        for (const polygon of [...this.polygons]) polygon.remove();
        for (const layer of [...this.geoJsonLayers]) layer.remove();
        this.attachments = [];
        this.defaultMarkerLayer = null;
        this.map.remove();
    }
}
