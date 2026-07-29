/**
 * Azure Maps Web SDK adapter for the MapRenderer interface.
 *
 * Azure Maps is a MapLibre fork, so the *shape* of this adapter is the MapLibre
 * one: clustering lives in the data source, marker icons become sprite images
 * named by a `step`/`get` expression, GeoJSON styling is baked into feature
 * properties because no paint expression can call a caller-supplied function.
 * Icon rasterisation lives in ./icons -- Azure Maps is a MapLibre fork, so a
 * declarative MarkerIcon has to become a bitmap the same way.
 *
 * Where it diverges, and why the code is not just a re-parameterisation:
 *  - The map is not usable until it fires 'ready'. Everything source-backed has
 *    to be deferred behind `ready`, which the MapLibre adapter did not need.
 *  - Sources and layers are objects (`atlas.source.DataSource`,
 *    `atlas.layer.SymbolLayer`) managed by `map.sources` / `map.layers`, not
 *    style-document entries addressed by string id.
 *  - `setStyle()` preserves user sources and layers, so there is no
 *    reattach-after-style-swap dance.
 *  - Azure ships a real base map switcher (`atlas.control.StyleControl`) and
 *    all four BaseMapTypes exist natively.
 */

import type * as atlas from 'azure-maps-control';

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
import { ResolvedIcon, iconKey, iconOffset, markerElement, parseFontSize, resolveIcon } from './icons';
import { atlasSdk } from './sdk';

/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Unlike MapLibre, all four base map types exist natively, so nothing here is
 * config-dependent and the factory's static capabilities are the whole truth.
 */
export const AZURE_CAPABILITIES: MapCapabilities = {
    canvasOverlay: true,
    clustering: true,
    tilt: true,
    rotation: true,
    baseMapTypes: ['roadmap', 'satellite', 'hybrid', 'terrain'],
};

const AZURE_STYLES: Record<BaseMapType, string> = {
    roadmap: 'road',
    satellite: 'satellite',
    // Azure's imagery-with-labels style — the one thing MapLibre cannot do for free.
    hybrid: 'satellite_road_labels',
    terrain: 'road_shaded_relief',
};

const BASE_MAP_BY_STYLE: Record<string, BaseMapType> = Object.fromEntries(
    Object.entries(AZURE_STYLES).map(([type, style]) => [style, type as BaseMapType]),
) as Record<string, BaseMapType>;

type Corner = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';

/** Azure also offers only four corners; same collapse as MapLibre. */
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

const CLUSTER_BREAKS = [1, 10, 25, 50, 100, 250, 500, 1000];

let uid = 0;
const nextId = (prefix: string) => `pp-az-${prefix}-${++uid}`;

function geoFeatureOf(feature: any): GeoFeature {
    const geometryType = (feature?.geometry?.type || 'Point') as GeometryType;
    let position: LatLng | null = null;
    if (geometryType === 'Point' && Array.isArray(feature?.geometry?.coordinates)) {
        position = { lat: feature.geometry.coordinates[1], lng: feature.geometry.coordinates[0] };
    }
    return { geometryType, properties: (feature?.properties || {}) as Record<string, unknown>, position };
}

/** Azure hands back either a Shape wrapper or a raw Feature; normalise both. */
function propertiesOf(shape: any): Record<string, any> {
    if (!shape) return {};
    return typeof shape.getProperties === 'function' ? shape.getProperties() : (shape.properties ?? {});
}

function toFeatureCollection(data: object): any {
    const gj = data as any;
    if (gj?.type === 'FeatureCollection') return { ...gj, features: [...(gj.features || [])] };
    if (gj?.type === 'Feature') return { type: 'FeatureCollection', features: [gj] };
    if (gj?.type) return { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: gj, properties: {} }] };
    return { type: 'FeatureCollection', features: [] };
}

type ImageRegistrar = (icon: MarkerIcon) => Promise<string>;

// ---------------------------------------------------------------------------
// Markers
// ---------------------------------------------------------------------------

/**
 * HtmlMarker-backed marker, used by *unclustered* layers only — for the same
 * reason as MapLibre: MarkerOptions carries `draggable`/`onDragEnd`, and a
 * symbol layer over a clustered DataSource cannot drag one feature.
 */
class AzureHtmlMarker implements MarkerHandle {
    readonly native: atlas.HtmlMarker;
    private position: LatLng;

    constructor(
        private readonly map: atlas.Map,
        private readonly options: MarkerOptions,
        private readonly onRemove: (marker: AzureHtmlMarker) => void,
    ) {
        const sdk = atlasSdk();
        this.position = options.position;
        const content = markerElement(options.icon, options.label, options.title);
        if (options.zIndex !== undefined) content.element.style.zIndex = String(options.zIndex);
        if (options.dropAnimation) {
            content.element.animate(
                [{ transform: 'translateY(-24px)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1 }],
                { duration: 300, easing: 'cubic-bezier(0.2, 0.8, 0.3, 1)' },
            );
        }

        this.native = new sdk.HtmlMarker({
            htmlContent: content.element,
            position: [options.position.lng, options.position.lat],
            pixelOffset: new sdk.Pixel(content.offset[0], content.offset[1]),
            anchor: 'center',
            draggable: options.draggable ?? false,
        });
        map.markers.add(this.native);

        if (options.onClick) {
            map.events.add('click', this.native, () => {
                options.onClick!({ position: this.getPosition() }, this);
            });
        }
        if (options.onDragEnd) {
            map.events.add('dragend', this.native, () => {
                options.onDragEnd!(this.getPosition());
            });
        }
    }

    getPosition(): LatLng {
        const position = this.native.getOptions().position;
        if (!position) return this.position;
        return { lat: position[1], lng: position[0] };
    }

    setPosition(position: LatLng): void {
        this.position = position;
        this.native.setOptions({ position: [position.lng, position.lat] });
    }

    setIcon(icon: MarkerIcon): void {
        const content = markerElement(icon, this.options.label, this.options.title);
        const sdk = atlasSdk();
        this.native.setOptions({
            htmlContent: content.element,
            pixelOffset: new sdk.Pixel(content.offset[0], content.offset[1]),
        });
    }

    setVisible(visible: boolean): void {
        this.native.setOptions({ visible });
    }

    remove(): void {
        this.map.markers.remove(this.native);
        this.onRemove(this);
    }
}

class HtmlMarkerLayer implements MarkerLayer {
    private markers: AzureHtmlMarker[] = [];
    private visible = true;
    private removed = false;

    constructor(
        private readonly map: atlas.Map,
        private readonly ready: Promise<void>,
        private readonly onRemove: (layer: HtmlMarkerLayer) => void,
    ) { }

    private build(options: MarkerOptions): AzureHtmlMarker {
        const marker = new AzureHtmlMarker(this.map, options, m => {
            this.markers = this.markers.filter(existing => existing !== m);
        });
        if (!this.visible) marker.setVisible(false);
        return marker;
    }

    setMarkers(markers: MarkerOptions[]): MarkerHandle[] {
        this.clear();
        if (this.removed) return [];
        // HtmlMarkers can only be added once the map is ready, but the interface
        // hands handles back synchronously — so the handles are real objects and
        // only the map attachment is deferred.
        const handles = markers.map(options => this.build(options));
        this.markers = handles;
        return [...handles];
    }

    addMarker(marker: MarkerOptions): MarkerHandle {
        const handle = this.build(marker);
        this.markers.push(handle);
        return handle;
    }

    clear(): void {
        for (const marker of [...this.markers]) marker.remove();
        this.markers = [];
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        void this.ready.then(() => {
            for (const marker of this.markers) marker.setVisible(visible);
        });
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
    iconKey: string | null;
    label?: MarkerOptions['label'];
    title?: string;
    zIndex?: number;
    hidden: boolean;
    onClick?: MarkerOptions['onClick'];
    handle: DataSourceMarker;
}

class DataSourceMarker implements MarkerHandle {
    constructor(private readonly layer: DataSourceMarkerLayer, private readonly entryId: number) { }

    getPosition(): LatLng {
        return this.layer.entry(this.entryId)?.position ?? { lat: 0, lng: 0 };
    }

    setPosition(position: LatLng): void {
        const entry = this.layer.entry(this.entryId);
        if (!entry) return;
        entry.position = position;
        this.layer.sync();
    }

    setIcon(icon: MarkerIcon): void {
        this.layer.setEntryIcon(this.entryId, icon);
    }

    setVisible(visible: boolean): void {
        const entry = this.layer.entry(this.entryId);
        if (!entry) return;
        entry.hidden = !visible;
        this.layer.sync();
    }

    remove(): void {
        this.layer.removeEntry(this.entryId);
    }
}

/** Clustered marker layer: one DataSource with `cluster: true` plus symbol layers. */
class DataSourceMarkerLayer implements MarkerLayer {
    private source: atlas.source.DataSource | null = null;
    private clusterLayer: atlas.layer.SymbolLayer | null = null;
    private pointLayer: atlas.layer.SymbolLayer | null = null;
    private entries = new Map<number, ClusterEntry>();
    private order: number[] = [];
    private offsets = new Map<string, [number, number]>();
    private nextEntryId = 1;
    private visible = true;
    private removed = false;
    private attached: Promise<void>;

    constructor(
        private readonly map: atlas.Map,
        ready: Promise<void>,
        private readonly cluster: ClusterOptions,
        private readonly ensureImage: ImageRegistrar,
        private readonly onRemove: (layer: DataSourceMarkerLayer) => void,
    ) {
        this.attached = ready.then(() => this.attach());
    }

    entry(id: number): ClusterEntry | undefined {
        return this.entries.get(id);
    }

    setOffset(key: string, offset: [number, number]): void {
        this.offsets.set(key, offset);
    }

    private async attach(): Promise<void> {
        const sdk = atlasSdk();

        const specs = CLUSTER_BREAKS.map(count => this.cluster.style(count));
        const keys = await Promise.all(specs.map(spec => this.ensureImage(spec.icon)));
        if (this.removed) return;

        const iconStep: any[] = ['step', ['get', 'point_count'], keys[0]];
        for (let i = 1; i < CLUSTER_BREAKS.length; i++) iconStep.push(CLUSTER_BREAKS[i], keys[i]);

        // Same trick as the MapLibre adapter: if the caller's labels are just
        // the count stringified, read the live count so a cluster of 37 is not
        // labelled "25" from the sampled breakpoint.
        const labelsAreCounts = specs.every((spec, i) => spec.label?.text === String(CLUSTER_BREAKS[i]));
        let textField: any = ['to-string', ['get', 'point_count']];
        if (!labelsAreCounts) {
            const step: any[] = ['step', ['get', 'point_count'], specs[0].label?.text ?? ''];
            for (let i = 1; i < CLUSTER_BREAKS.length; i++) step.push(CLUSTER_BREAKS[i], specs[i].label?.text ?? '');
            textField = step;
        }
        const labelStyle = specs[specs.length - 1].label;

        this.source = new sdk.source.DataSource(nextId('src'), {
            cluster: true,
            clusterRadius: 50,
            clusterMaxZoom: 16,
        });
        this.map.sources.add(this.source);

        this.clusterLayer = new sdk.layer.SymbolLayer(this.source, nextId('cls'), {
            filter: ['has', 'point_count'] as any,
            visible: this.visible,
            iconOptions: { image: iconStep as any, allowOverlap: true, ignorePlacement: true },
            textOptions: {
                textField: textField as any,
                color: labelStyle?.color ?? '#ffffff',
                size: parseFontSize(labelStyle?.fontSize, 12),
                allowOverlap: true,
                ignorePlacement: true,
            },
        });

        this.pointLayer = new sdk.layer.SymbolLayer(this.source, nextId('pts'), {
            filter: ['all', ['!', ['has', 'point_count']], ['!=', ['get', '__hidden'], true]] as any,
            visible: this.visible,
            iconOptions: {
                image: ['coalesce', ['get', '__icon'], ''] as any,
                offset: ['array', 'number', 2, ['coalesce', ['get', '__offset'], ['literal', [0, 0]]]] as any,
                allowOverlap: true,
                ignorePlacement: true,
            },
            textOptions: {
                textField: ['coalesce', ['get', '__label'], ''] as any,
                color: ['coalesce', ['get', '__labelColor'], '#ffffff'] as any,
                size: ['to-number', ['coalesce', ['get', '__labelSize'], 12]] as any,
                allowOverlap: true,
                ignorePlacement: true,
            },
            // Symbols with a lower sort key draw on top, so invert zIndex.
            sortKey: ['*', -1, ['to-number', ['coalesce', ['get', '__z'], 0]]] as any,
        });

        this.map.layers.add([this.clusterLayer, this.pointLayer]);

        this.map.events.add('click', this.pointLayer, (event: atlas.MapMouseEvent) => {
            const properties = propertiesOf(event.shapes?.[0]);
            const entry = properties.__id !== undefined ? this.entries.get(Number(properties.__id)) : undefined;
            if (!entry?.onClick) return;
            entry.onClick({ position: entry.position }, entry.handle);
        });

        this.map.events.add('click', this.clusterLayer, (event: atlas.MapMouseEvent) => {
            const properties = propertiesOf(event.shapes?.[0]);
            if (properties.cluster_id === undefined || !this.source) return;
            void this.source.getClusterExpansionZoom(properties.cluster_id).then(zoom => {
                this.map.setCamera({ center: event.position, zoom, type: 'ease', duration: 200 });
            });
        });

        this.applyData();
    }

    private collection(): any {
        return {
            type: 'FeatureCollection',
            features: this.order
                .map(id => this.entries.get(id))
                .filter((entry): entry is ClusterEntry => !!entry)
                .map(entry => ({
                    type: 'Feature',
                    geometry: { type: 'Point', coordinates: [entry.position.lng, entry.position.lat] },
                    properties: {
                        __id: entry.id,
                        __icon: entry.iconKey,
                        __offset: entry.iconKey ? this.offsets.get(entry.iconKey) ?? [0, 0] : [0, 0],
                        __z: entry.zIndex ?? 0,
                        __hidden: entry.hidden,
                        __label: entry.label?.text ?? '',
                        __labelColor: entry.label?.color ?? '#ffffff',
                        __labelSize: parseFontSize(entry.label?.fontSize, 12),
                        __title: entry.title ?? '',
                    },
                })),
        };
    }

    private applyData(): void {
        this.source?.setShapes(this.collection());
    }

    sync(): void {
        void this.attached.then(() => {
            if (!this.removed) this.applyData();
        });
    }

    private async resolveEntryIcon(entry: ClusterEntry, icon: MarkerIcon): Promise<void> {
        const key = await this.ensureImage(icon);
        if (this.removed || !this.entries.has(entry.id)) return;
        entry.iconKey = key;
        this.applyData();
    }

    setEntryIcon(id: number, icon: MarkerIcon): void {
        const entry = this.entries.get(id);
        if (!entry) return;
        void this.attached.then(() => this.resolveEntryIcon(entry, icon));
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
            iconKey: null,
            label: options.label,
            title: options.title,
            zIndex: options.zIndex,
            hidden: false,
            onClick: options.onClick,
            handle: undefined as unknown as DataSourceMarker,
        };
        entry.handle = new DataSourceMarker(this, id);
        this.entries.set(id, entry);
        this.order.push(id);

        if (options.draggable || options.onDragEnd) {
            console.warn('Azure Maps: draggable markers are not supported inside a clustered marker layer');
        }
        if (options.icon) void this.attached.then(() => this.resolveEntryIcon(entry, options.icon!));
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
        void this.attached.then(() => {
            this.clusterLayer?.setOptions({ visible });
            this.pointLayer?.setOptions({ visible });
        });
    }

    remove(): void {
        this.removed = true;
        void this.attached.then(() => {
            const layers = [this.clusterLayer, this.pointLayer].filter(Boolean) as atlas.layer.Layer[];
            if (layers.length) this.map.layers.remove(layers);
            if (this.source) this.map.sources.remove(this.source);
            this.clusterLayer = null;
            this.pointLayer = null;
            this.source = null;
        });
        this.entries.clear();
        this.order = [];
        this.onRemove(this);
    }
}

// ---------------------------------------------------------------------------
// GeoJSON / polygons
// ---------------------------------------------------------------------------

const DEFAULT_VECTOR_STYLE = {
    fillColor: '#3388ff',
    fillOpacity: 0.2,
    strokeColor: '#3388ff',
    strokeOpacity: 1,
    strokeWidth: 2,
};

/**
 * Per-feature style functions are baked into feature properties, exactly as in
 * the MapLibre adapter — Azure inherits the same expression engine and the same
 * inability to call back into JS from a paint property.
 */
class AzureGeoJsonLayer implements GeoJsonLayerHandle {
    private source: atlas.source.DataSource | null = null;
    private layers: atlas.layer.Layer[] = [];
    private collection: any;
    private style: VectorStyle | ((feature: GeoFeature) => VectorStyle);
    private visible = true;
    private removed = false;
    private attached: Promise<void>;

    constructor(
        private readonly map: atlas.Map,
        ready: Promise<void>,
        private readonly options: GeoJsonLayerOptions,
        private readonly onRemove: (layer: AzureGeoJsonLayer) => void,
    ) {
        this.collection = toFeatureCollection(options.data);
        this.style = options.style ?? {};
        this.bake();
        this.attached = ready.then(() => this.attach());
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

    private attach(): void {
        if (this.removed) return;
        const sdk = atlasSdk();

        this.source = new sdk.source.DataSource(nextId('gjs'));
        this.map.sources.add(this.source);
        this.source.setShapes(this.collection);

        const visibleFilter: any[] = ['!=', ['get', '__visible'], false];

        const polygonLayer = new sdk.layer.PolygonLayer(this.source, nextId('gjf'), {
            filter: ['all', visibleFilter, ['==', ['geometry-type'], 'Polygon']] as any,
            visible: this.visible,
            fillColor: ['to-color', ['get', '__fill']] as any,
            fillOpacity: ['to-number', ['get', '__fillOpacity']] as any,
        });

        const lineLayer = new sdk.layer.LineLayer(this.source, nextId('gjl'), {
            filter: ['all', visibleFilter, ['match', ['geometry-type'], ['LineString', 'Polygon'], true, false]] as any,
            visible: this.visible,
            strokeColor: ['to-color', ['get', '__stroke']] as any,
            strokeOpacity: ['to-number', ['get', '__strokeOpacity']] as any,
            strokeWidth: ['to-number', ['get', '__strokeWidth']] as any,
        });

        this.layers = [polygonLayer, lineLayer];

        if (this.options.pointRendering !== 'hidden') {
            this.layers.push(new sdk.layer.BubbleLayer(this.source, nextId('gjc'), {
                filter: ['all', visibleFilter, ['==', ['geometry-type'], 'Point']] as any,
                visible: this.visible,
                color: ['to-color', ['get', '__fill']] as any,
                opacity: ['to-number', ['get', '__fillOpacity']] as any,
                radius: 6,
                strokeColor: ['to-color', ['get', '__stroke']] as any,
                strokeWidth: ['to-number', ['get', '__strokeWidth']] as any,
            }));
        }

        this.map.layers.add(this.layers);

        if (this.options.onFeatureClick) {
            this.map.events.add('click', this.layers, (event: atlas.MapMouseEvent) => {
                const shape = event.shapes?.[0];
                const properties = propertiesOf(shape);
                if (properties.__clickable === false) return;
                const feature = typeof (shape as any)?.toJson === 'function' ? (shape as any).toJson() : shape;
                this.options.onFeatureClick!(geoFeatureOf(feature), {
                    position: { lat: event.position?.[1] ?? 0, lng: event.position?.[0] ?? 0 },
                });
            });
        }
    }

    setStyle(style: VectorStyle | ((feature: GeoFeature) => VectorStyle)): void {
        this.style = style;
        this.bake();
        void this.attached.then(() => this.source?.setShapes(this.collection));
    }

    setVisible(visible: boolean): void {
        this.visible = visible;
        void this.attached.then(() => {
            for (const layer of this.layers) (layer as any).setOptions({ visible });
        });
    }

    remove(): void {
        this.removed = true;
        void this.attached.then(() => {
            if (this.layers.length) this.map.layers.remove(this.layers);
            if (this.source) this.map.sources.remove(this.source);
            this.layers = [];
            this.source = null;
        });
        this.onRemove(this);
    }
}

class AzurePolygon implements PolygonHandle {
    private layer: AzureGeoJsonLayer;

    constructor(
        map: atlas.Map,
        ready: Promise<void>,
        options: PolygonOptions,
        private readonly onRemove: (polygon: AzurePolygon) => void,
    ) {
        const coordinates = options.paths.map(ring => ring.map(point => [point.lng, point.lat]));
        this.layer = new AzureGeoJsonLayer(map, ready, {
            data: { type: 'Polygon', coordinates },
            style: options.style ?? {},
            onFeatureClick: options.onClick ? (_feature, event) => options.onClick!(event) : undefined,
        }, () => { });
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

class AzurePopup implements PopupHandle {
    private popup: atlas.Popup;
    private open = false;

    constructor(
        private readonly map: atlas.Map,
        options: PopupOptions | undefined,
        private readonly onRemove: (popup: AzurePopup) => void,
    ) {
        this.popup = new (atlasSdk().Popup)({
            content: options?.content ?? '',
            closeButton: true,
        });
        map.events.add('close', this.popup, () => { this.open = false; });
    }

    setContent(content: string | HTMLElement): void {
        this.popup.setOptions({ content });
    }

    openAt(anchor: MarkerHandle | LatLng): void {
        const position = 'getPosition' in anchor ? anchor.getPosition() : anchor;
        this.popup.setOptions({ position: [position.lng, position.lat] });
        if (!this.open) {
            this.popup.open(this.map);
            this.open = true;
        }
    }

    close(): void {
        this.popup.close();
        this.open = false;
    }

    remove(): void {
        this.close();
        this.onRemove(this);
    }
}

/**
 * Canvas overlay on `positionsToPixels`, which is Azure's equivalent of
 * `map.project` and returns container-relative pixels.
 */
function createCanvasOverlay(
    map: atlas.Map,
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
        if (removed || map.isDisposed) return;
        const container = map.getMapContainer();
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

        const camera = map.getCamera();
        const box = camera.bounds;
        if (!box) return;

        const view: OverlayViewport = {
            width,
            height,
            // Azure BoundingBox is [west, south, east, north].
            bounds: { west: box[0], south: box[1], east: box[2], north: box[3] },
            zoom: camera.zoom ?? 0,
            project: position => {
                const pixel = map.positionsToPixels([[position.lng, position.lat]])[0];
                return pixel ? { x: pixel[0], y: pixel[1] } : { x: NaN, y: NaN };
            },
        };
        options.draw(ctx, view);
    };

    map.events.add('move', render);
    map.events.add('resize', render);
    map.events.add('ready', render);

    const handle: CanvasOverlayHandle = {
        redraw: render,
        remove: () => {
            removed = true;
            map.events.remove('move', render);
            map.events.remove('resize', render);
            map.events.remove('ready', render);
            canvas.remove();
            onRemove(handle);
        },
    };
    return handle;
}

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

export interface AzureProviderOptions {
    /** Azure Maps localisation view (ISO 3166-1 alpha-2, or 'Auto'). */
    view?: string;
    language?: string;
}

export class AzureMapRenderer implements MapRenderer {
    readonly providerId: MapProviderId = 'azure';
    readonly capabilities = AZURE_CAPABILITIES;

    private map: atlas.Map;
    private ready: Promise<void>;
    private baseMapType: BaseMapType;
    private pixelRatio = Math.min(2, Math.round(window.devicePixelRatio || 1));

    private imagePromises = new Map<string, Promise<string>>();
    private markerLayers: MarkerLayer[] = [];
    private geoJsonLayers: AzureGeoJsonLayer[] = [];
    private polygons: AzurePolygon[] = [];
    private popups: AzurePopup[] = [];
    private overlays: CanvasOverlayHandle[] = [];
    private mapListeners: { type: string; handler: (payload: any) => void }[] = [];
    private baseMapListeners: ((type: BaseMapType) => void)[] = [];
    private styleControl: atlas.control.StyleControl | null = null;
    private defaultMarkerLayer: HtmlMarkerLayer | null = null;
    private destroyed = false;

    constructor(
        container: HTMLElement,
        subscriptionKey: string,
        providerOptions: AzureProviderOptions,
        options: MapInitOptions,
    ) {
        const sdk = atlasSdk();
        this.baseMapType = options.baseMapType ?? 'roadmap';

        this.map = new sdk.Map(container, {
            center: [options.center?.lng ?? 0, options.center?.lat ?? 0],
            zoom: options.zoom ?? 1,
            bearing: options.heading ?? 0,
            pitch: options.tilt ?? 0,
            // styleId, when set, is an Azure style name and wins over baseMapType.
            style: options.styleId || AZURE_STYLES[this.baseMapType],
            language: providerOptions.language,
            // Azure requires a localisation view for disputed borders; 'Auto'
            // resolves it from the caller's IP, which is the documented default
            // for deployments that cannot determine the user's region.
            view: providerOptions.view ?? 'Auto',
            authOptions: {
                authType: sdk.AuthenticationType.subscriptionKey,
                subscriptionKey,
            },
            ...(options.vendorOptions as any),
        });

        if (options.styleId && BASE_MAP_BY_STYLE[options.styleId]) {
            this.baseMapType = BASE_MAP_BY_STYLE[options.styleId];
        }

        this.ready = new Promise<void>(resolve => {
            this.map.events.add('ready', () => resolve());
        });

        this.addControls(options);
    }

    private addControls(options: MapInitOptions): void {
        const sdk = atlasSdk();
        const controls = options.controls ?? {};

        if (controls.zoom?.enabled) {
            this.map.controls.add(new sdk.control.ZoomControl(), {
                position: corner(controls.zoom.position, 'top-right') as atlas.ControlPosition,
            });
        }
        if (controls.rotate?.enabled) {
            this.map.controls.add([new sdk.control.CompassControl(), new sdk.control.PitchControl()], {
                position: corner(controls.rotate.position, 'top-right') as atlas.ControlPosition,
            });
        }
        if (controls.baseMapSwitcher?.enabled) {
            const types = controls.baseMapSwitcher.types ?? AZURE_CAPABILITIES.baseMapTypes;
            this.styleControl = new sdk.control.StyleControl({
                mapStyles: types.map(type => AZURE_STYLES[type]),
                layout: 'list',
            });
            this.map.controls.add(this.styleControl, {
                position: corner(controls.baseMapSwitcher.position, 'top-left') as atlas.ControlPosition,
            });
            // The control changes the style behind our back, so mirror it into
            // baseMapType and fire basemaptypechange from here.
            this.map.events.add('styleselected', this.styleControl, (style: string) => {
                const type = BASE_MAP_BY_STYLE[style];
                if (!type || type === this.baseMapType) return;
                this.baseMapType = type;
                for (const listener of this.baseMapListeners) listener(type);
            });
        }
        if (controls.fullscreen?.enabled) {
            // azure-maps-control ships no fullscreen control (it lives in the
            // separate azure-maps-fullscreen-control package). Adding that
            // dependency for one button is not worth it; the request is ignored
            // rather than faked.
            console.warn('Azure Maps: fullscreen control is not part of the Web SDK; ignoring controls.fullscreen');
        }
        // controls.streetView is Google-only; Azure has no street-level mode.
    }

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
        const resolved: ResolvedIcon = await resolveIcon(icon, this.pixelRatio);
        for (const layer of this.markerLayers) {
            if (layer instanceof DataSourceMarkerLayer) layer.setOffset(key, iconOffset(resolved));
        }
        await this.ready;
        if (this.destroyed) return key;
        try {
            // imageSprite.add takes a data URI directly — no HTMLImageElement
            // round trip, unlike MapLibre's addImage.
            await this.map.imageSprite.add(key, resolved.url, { pixelRatio: resolved.pixelRatio });
        } catch (error) {
            console.warn('Azure Maps: failed to register marker image', error);
        }
        return key;
    }

    getCenter(): LatLng {
        const center = this.map.getCamera().center;
        return center ? { lat: center[1], lng: center[0] } : { lat: 0, lng: 0 };
    }

    setCenter(center: LatLng): void {
        this.map.setCamera({ center: [center.lng, center.lat] });
    }

    panTo(center: LatLng): void {
        this.map.setCamera({ center: [center.lng, center.lat], type: 'ease', duration: 300 });
    }

    getZoom(): number {
        return this.map.getCamera().zoom ?? 0;
    }

    setZoom(zoom: number): void {
        this.map.setCamera({ zoom });
    }

    getBounds(): LatLngBounds | null {
        const box = this.map.getCamera().bounds;
        if (!box) return null;
        return { west: box[0], south: box[1], east: box[2], north: box[3] };
    }

    fitBounds(bounds: LatLngBounds, options?: FitBoundsOptions): void {
        this.map.setCamera({
            bounds: [bounds.west, bounds.south, bounds.east, bounds.north],
            padding: options?.padding ?? 0,
            maxZoom: options?.maxZoom,
        });
    }

    getBaseMapType(): BaseMapType {
        return this.baseMapType;
    }

    setBaseMapType(type: BaseMapType): void {
        if (type === this.baseMapType) return;
        this.baseMapType = type;
        // Azure preserves user-added sources, layers, markers and sprite images
        // across a style change, so unlike MapLibre nothing has to be rebuilt.
        this.map.setStyle({ style: AZURE_STYLES[type] });
        this.styleControl?.setSelectedStyle(AZURE_STYLES[type]);
        for (const listener of this.baseMapListeners) listener(type);
    }

    createMarkerLayer(options?: MarkerLayerOptions): MarkerLayer {
        const layer: MarkerLayer = options?.cluster
            ? new DataSourceMarkerLayer(this.map, this.ready, options.cluster, this.ensureImage, l => this.forget(l))
            : new HtmlMarkerLayer(this.map, this.ready, l => this.forget(l));
        this.markerLayers.push(layer);
        return layer;
    }

    private forget(layer: MarkerLayer): void {
        this.markerLayers = this.markerLayers.filter(existing => existing !== layer);
    }

    addMarker(options: MarkerOptions): MarkerHandle {
        if (!this.defaultMarkerLayer) {
            this.defaultMarkerLayer = this.createMarkerLayer() as HtmlMarkerLayer;
        }
        return this.defaultMarkerLayer.addMarker(options);
    }

    addGeoJsonLayer(options: GeoJsonLayerOptions): GeoJsonLayerHandle {
        const layer = new AzureGeoJsonLayer(this.map, this.ready, options, l => {
            this.geoJsonLayers = this.geoJsonLayers.filter(existing => existing !== l);
        });
        this.geoJsonLayers.push(layer);
        return layer;
    }

    addPolygon(options: PolygonOptions): PolygonHandle {
        const polygon = new AzurePolygon(this.map, this.ready, options, p => {
            this.polygons = this.polygons.filter(existing => existing !== p);
        });
        this.polygons.push(polygon);
        return polygon;
    }

    createPopup(options?: PopupOptions): PopupHandle {
        const popup = new AzurePopup(this.map, options, p => {
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
            const listener = (type: BaseMapType) => emit({ type });
            this.baseMapListeners.push(listener);
            return () => {
                this.baseMapListeners = this.baseMapListeners.filter(existing => existing !== listener);
            };
        }

        const type = event === 'click' ? 'click' : 'idle';
        const wrapped = event === 'click'
            ? (e: atlas.MapMouseEvent) => {
                if (!e.position) return;
                emit({ position: { lat: e.position[1], lng: e.position[0] } });
            }
            : () => emit(undefined);

        (this.map.events.add as any)(type, wrapped);
        const record = { type, handler: wrapped as (payload: any) => void };
        this.mapListeners.push(record);

        return () => {
            (this.map.events.remove as any)(type, wrapped);
            this.mapListeners = this.mapListeners.filter(existing => existing !== record);
        };
    }

    destroy(): void {
        this.destroyed = true;
        for (const listener of this.mapListeners) {
            (this.map.events.remove as any)(listener.type, listener.handler);
        }
        this.mapListeners = [];
        this.baseMapListeners = [];
        for (const overlay of [...this.overlays]) overlay.remove();
        for (const popup of [...this.popups]) popup.remove();
        for (const layer of [...this.markerLayers]) layer.remove();
        for (const polygon of [...this.polygons]) polygon.remove();
        for (const layer of [...this.geoJsonLayers]) layer.remove();
        this.defaultMarkerLayer = null;
        this.map.dispose();
    }
}
