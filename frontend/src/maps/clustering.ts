import { clusterIcon } from './markerIcons';
import {
    ClusterOptions,
    LatLng,
    LatLngBounds,
    MapRenderer,
    MarkerHandle,
    MarkerLayer,
    MarkerOptions,
    Unsubscribe,
} from './types';

/**
 * Clustering, done once, for every provider.
 *
 * ## Why this is not in the adapters any more
 *
 * It used to be, and each vendor brought its own engine: Google drove
 * `@googlemaps/markerclusterer`, Esri set a `featureReduction` on the layer,
 * Azure clustered inside the data source, Apple used `clusteringIdentifier`.
 * Four engines meant four groupings of the same reports, four bubble sizes,
 * four click behaviours -- and one bug that could not be fixed where it
 * appeared.
 *
 * `ClusterOptions.style` is a function of the cluster's size. Google can call
 * it per cluster. Esri cannot: it styles clusters with a *renderer* over a
 * synthetic `cluster_count` field, so the adapter had to sample that function at
 * ten fixed breakpoints and bake the result into an image. The count is drawn
 * inside the SVG, so a cluster of 49 fell in the [25, 49] break and rendered the
 * icon for 25 -- it said **25** on screen. Every break was wrong except at its
 * exact lower bound. That is not an Esri defect to patch; it is what asking an
 * expression-based engine to call a JS callback per feature costs.
 *
 * So the grouping happens here, in one place, and the providers are asked only
 * for what all of them do identically well: draw the markers they are given.
 * A cluster bubble is an ordinary marker carrying an ordinary
 * `markerIcons.clusterIcon`, with the *real* count in it.
 *
 * ## What this needs from a provider
 *
 * `on('idle')`, `getZoom()`, `getBounds()`, `fitBounds()` and a plain marker
 * layer. Every adapter already implements all five, which is why this needed no
 * new capability -- only the removal of four.
 *
 * ## Grid, not centroid-chasing
 *
 * Markers are bucketed by a fixed grid in Web Mercator pixel space. It is what
 * MarkerClusterer's default algorithm does, so the result is familiar; it is
 * O(n); and, unlike a greedy nearest-neighbour pass, it does not depend on the
 * order markers arrive in -- which matters here because two maps showing the
 * same reports build their arrays from different queries.
 */

/** Cluster cell size in CSS pixels. Esri's adapter used 60; so does Google's. */
const CLUSTER_RADIUS_PX = 60;

/** Web Mercator tile size, the unit every provider's zoom level is defined in. */
const TILE_SIZE = 256;

export interface Cluster {
    /** Where the bubble sits: the mean of its members, not the cell centre. */
    position: LatLng;
    members: MarkerOptions[];
}

/** Web Mercator pixel coordinates at a given zoom. */
function project(position: LatLng, worldSize: number): { x: number; y: number } {
    const lat = Math.max(-85.05112878, Math.min(85.05112878, position.lat));
    const sin = Math.sin((lat * Math.PI) / 180);
    return {
        x: ((position.lng + 180) / 360) * worldSize,
        // The standard Mercator y, clamped above so the poles cannot produce
        // an infinite log.
        y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * worldSize,
    };
}

/**
 * Group markers that fall in the same grid cell at this zoom.
 *
 * Exported for its own sake: this is the part worth testing directly, and it is
 * a pure function of markers and zoom, with no map in sight.
 */
export function clusterMarkers(
    markers: MarkerOptions[],
    zoom: number,
    radiusPx: number = CLUSTER_RADIUS_PX,
): Cluster[] {
    if (!markers.length) return [];
    // A non-finite zoom means the camera has not settled. Grouping everything
    // into one bubble would be worse than not grouping at all.
    if (!Number.isFinite(zoom)) {
        return markers.map(marker => ({ position: marker.position, members: [marker] }));
    }

    const worldSize = TILE_SIZE * Math.pow(2, zoom);
    const cells = new Map<string, MarkerOptions[]>();

    for (const marker of markers) {
        const { x, y } = project(marker.position, worldSize);
        const key = `${Math.floor(x / radiusPx)}:${Math.floor(y / radiusPx)}`;
        const bucket = cells.get(key);
        if (bucket) bucket.push(marker);
        else cells.set(key, [marker]);
    }

    const clusters: Cluster[] = [];
    for (const members of cells.values()) {
        if (members.length === 1) {
            clusters.push({ position: members[0].position, members });
            continue;
        }
        let lat = 0;
        let lng = 0;
        for (const member of members) {
            lat += member.position.lat;
            lng += member.position.lng;
        }
        clusters.push({
            position: { lat: lat / members.length, lng: lng / members.length },
            members,
        });
    }
    return clusters;
}

/** The tightest box containing every marker, for zooming into a cluster. */
export function boundsOfMarkers(markers: MarkerOptions[]): LatLngBounds | null {
    if (!markers.length) return null;
    let north = -Infinity;
    let south = Infinity;
    let east = -Infinity;
    let west = Infinity;
    for (const { position } of markers) {
        north = Math.max(north, position.lat);
        south = Math.min(south, position.lat);
        east = Math.max(east, position.lng);
        west = Math.min(west, position.lng);
    }
    return { north, south, east, west };
}

/** A handle for a marker the caller passed but that is currently inside a bubble. */
function detachedHandle(marker: MarkerOptions): MarkerHandle {
    let position = marker.position;
    return {
        getPosition: () => position,
        setPosition: next => { position = next; },
        setIcon: () => { },
        setVisible: () => { },
        remove: () => { },
    };
}

/**
 * Wraps a provider's plain marker layer and feeds it clusters instead of
 * markers. The provider never learns that clustering happened.
 */
class ClusteredMarkerLayer implements MarkerLayer {
    private markers: MarkerOptions[] = [];
    private lastZoom: number | null = null;
    private removed = false;
    private readonly unsubscribe: Unsubscribe;

    constructor(
        private readonly renderer: MapRenderer,
        private readonly native: MarkerLayer,
        private readonly cluster: ClusterOptions,
    ) {
        // `idle` rather than a zoom event: it is the one "camera has settled"
        // signal every adapter implements, and re-bucketing mid-animation would
        // make bubbles jump around while the user is still moving.
        this.unsubscribe = this.renderer.on('idle', () => {
            const zoom = this.renderer.getZoom();
            if (!Number.isFinite(zoom) || zoom === this.lastZoom) return;
            this.render();
        });
    }

    setMarkers(markers: MarkerOptions[]): MarkerHandle[] {
        this.markers = markers;
        this.render();
        // Callers replace their whole marker set rather than holding handles
        // (see MarkerLayer's own note), so these stand in for markers that a
        // bubble is currently standing in front of.
        return markers.map(detachedHandle);
    }

    addMarker(marker: MarkerOptions): MarkerHandle {
        this.markers = [...this.markers, marker];
        this.render();
        return detachedHandle(marker);
    }

    clear(): void {
        this.markers = [];
        this.native.clear();
    }

    setVisible(visible: boolean): void {
        this.native.setVisible(visible);
    }

    remove(): void {
        if (this.removed) return;
        this.removed = true;
        this.unsubscribe?.();
        this.native.remove();
    }

    private render(): void {
        if (this.removed) return;
        const zoom = this.renderer.getZoom();
        this.lastZoom = Number.isFinite(zoom) ? zoom : null;

        const groups = clusterMarkers(this.markers, zoom);
        const drawn: MarkerOptions[] = groups.map(group => {
            // A lone marker is passed through exactly as the caller wrote it --
            // same icon, title, z-index and click handler. Nothing about being
            // in a clustering layer should change how a single pin behaves.
            if (group.members.length === 1) return group.members[0];

            const count = group.members.length;
            const spec = this.cluster.style(count);
            return {
                position: group.position,
                icon: spec.icon ?? clusterIcon(count),
                label: spec.label,
                zIndex: spec.zIndex,
                title: `${count} reports in this area. Activate to zoom in.`,
                onClick: () => this.zoomTo(group),
            };
        });

        this.native.setMarkers(drawn);
    }

    /**
     * Clicking a bubble zooms to what is inside it -- the same thing on every
     * provider, which it previously was not. Members can share a coordinate
     * exactly (two reports at one address), and fitting a zero-area box either
     * does nothing or zooms to maximum depending on the vendor, so that case
     * steps the zoom in instead.
     */
    private zoomTo(group: Cluster): void {
        const bounds = boundsOfMarkers(group.members);
        if (!bounds) return;

        const degenerate = bounds.north === bounds.south && bounds.east === bounds.west;
        if (degenerate) {
            const zoom = this.renderer.getZoom();
            this.renderer.setZoom((Number.isFinite(zoom) ? zoom : 14) + 2);
            return;
        }
        this.renderer.fitBounds(bounds, { padding: 60 });
    }
}

/**
 * Give a renderer shared clustering.
 *
 * Applied once, by `createMap`, so no call site and no adapter has to remember.
 * `createMarkerLayer` is replaced rather than the whole renderer being proxied:
 * a proxy would have to forward two dozen methods and would silently drop any
 * added later, which is the kind of quiet divergence this change exists to end.
 */
export function withSharedClustering(renderer: MapRenderer): MapRenderer {
    const native = renderer.createMarkerLayer.bind(renderer);

    renderer.createMarkerLayer = (options) => {
        if (!options?.cluster) return native(options);
        // The provider is handed a plain layer: `cluster` stops here.
        return new ClusteredMarkerLayer(renderer, native(), options.cluster);
    };

    return renderer;
}
