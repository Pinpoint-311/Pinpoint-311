import { describe, expect, it, vi } from 'vitest';

import { boundsOfMarkers, clusterMarkers, withSharedClustering } from './clustering';
import { clusterStyle } from './markerIcons';
import { LatLngBounds, MapRenderer, MarkerLayer, MarkerOptions } from './types';

/**
 * Clustering is the app's, not the vendor's.
 *
 * The bug that moved it here: Esri styles clusters with a renderer over a
 * synthetic `cluster_count` field and cannot call a JS callback per cluster, so
 * its adapter sampled `ClusterOptions.style` at ten fixed breakpoints and baked
 * the result into an image. Live, from the deployed build, the class breaks read
 *
 *     [2, 4] -> "2"   [25, 49] -> "25"   [100, 249] -> "100"
 *
 * so a cluster of 49 reports drew a bubble saying **25**. Google, driving
 * MarkerClusterer, drew 49. Same data, same town, different number depending on
 * which provider was configured.
 *
 * `the bubble says how many are actually in it` is that regression, and it
 * fails against any implementation that samples rather than counts.
 */

function markerAt(lat: number, lng: number, extra: Partial<MarkerOptions> = {}): MarkerOptions {
    return { position: { lat, lng }, ...extra };
}

/** Records whatever the provider layer is asked to draw. */
function fakeLayer(): MarkerLayer & { drawn: MarkerOptions[] } {
    const layer = {
        drawn: [] as MarkerOptions[],
        setMarkers(markers: MarkerOptions[]) { layer.drawn = markers; return []; },
        addMarker: () => ({}) as never,
        clear() { layer.drawn = []; },
        setVisible() { },
        remove() { },
    };
    return layer as MarkerLayer & { drawn: MarkerOptions[] };
}

function fakeRenderer(zoom: number) {
    const native = fakeLayer();
    const idle: Array<() => void> = [];
    const renderer = {
        zoom,
        fitBounds: vi.fn<(b: LatLngBounds) => void>(),
        setZoom: vi.fn<(z: number) => void>(),
        getZoom: () => renderer.zoom,
        on: (event: string, handler: () => void) => {
            if (event === 'idle') idle.push(handler);
            return () => { };
        },
        createMarkerLayer: () => native,
        native,
        idle,
    };
    return renderer as unknown as MapRenderer & typeof renderer;
}

/** The count drawn inside a cluster bubble's SVG. */
function drawnCount(marker: MarkerOptions): string | undefined {
    const icon = marker.icon;
    if (!icon || icon.type !== 'image') return undefined;
    const markup = decodeURIComponent(icon.url.slice(icon.url.indexOf(',') + 1));
    return (markup.match(/>([^<]*)<\/text>/) || [])[1];
}

describe('clusterMarkers', () => {
    it('separates markers that are far apart', () => {
        const clusters = clusterMarkers(
            [markerAt(40.73, -74.27), markerAt(40.80, -74.10)],
            13,
        );
        expect(clusters).toHaveLength(2);
        expect(clusters.every(c => c.members.length === 1)).toBe(true);
    });

    it('groups markers that share a cell, and loosens its grip as you zoom in', () => {
        const nearby = [
            markerAt(40.7300, -74.2700),
            markerAt(40.7302, -74.2702),
            markerAt(40.7304, -74.2698),
        ];
        expect(clusterMarkers(nearby, 11)).toHaveLength(1);

        const zoomedIn = clusterMarkers(nearby, 19);
        expect(zoomedIn.length).toBeGreaterThan(1);
    });

    it('does not depend on the order the markers arrive in', () => {
        // Two maps show the same reports from different queries; they must group
        // them the same way.
        const markers = Array.from({ length: 40 }, (_, i) =>
            markerAt(40.73 + (i % 7) * 0.001, -74.27 + Math.floor(i / 7) * 0.001));
        const shape = (ms: MarkerOptions[]) =>
            clusterMarkers(ms, 15).map(c => c.members.length).sort((a, b) => a - b);

        expect(shape([...markers].reverse())).toEqual(shape(markers));
    });

    it('puts the bubble at the mean of its members, not at a grid corner', () => {
        const [cluster] = clusterMarkers(
            [markerAt(40.0, -74.0), markerAt(40.0002, -74.0002)], 12);
        expect(cluster.members).toHaveLength(2);
        expect(cluster.position.lat).toBeCloseTo(40.0001, 6);
        expect(cluster.position.lng).toBeCloseTo(-74.0001, 6);
    });

    it('survives a zoom that has not settled yet', () => {
        const clusters = clusterMarkers([markerAt(1, 1), markerAt(2, 2)], NaN);
        expect(clusters).toHaveLength(2);
    });
});

describe('boundsOfMarkers', () => {
    it('is the tightest box round every marker', () => {
        expect(boundsOfMarkers([markerAt(1, 2), markerAt(3, -4)]))
            .toEqual({ north: 3, south: 1, east: 2, west: -4 });
    });

    it('is null for nothing', () => {
        expect(boundsOfMarkers([])).toBeNull();
    });
});

describe('a clustering marker layer', () => {
    it('the bubble says how many are actually in it', () => {
        // 49 markers in one cell -- the exact case Esri drew as "25".
        const renderer = fakeRenderer(11);
        const layer = withSharedClustering(renderer)
            .createMarkerLayer({ cluster: { style: clusterStyle } });

        layer.setMarkers(Array.from({ length: 49 }, (_, i) =>
            markerAt(40.73 + i * 0.000002, -74.27 + i * 0.000002)));

        expect(renderer.native.drawn).toHaveLength(1);
        expect(drawnCount(renderer.native.drawn[0])).toBe('49');
    });

    it('hands a lone marker to the provider exactly as the caller wrote it', () => {
        const renderer = fakeRenderer(13);
        const onClick = vi.fn();
        const mine = markerAt(40.73, -74.27, { title: 'Pothole on Valley St', onClick });
        const layer = withSharedClustering(renderer)
            .createMarkerLayer({ cluster: { style: clusterStyle } });

        layer.setMarkers([mine, markerAt(41.5, -73.0)]);

        // Same object: its icon, title, z-index and click handler all intact.
        expect(renderer.native.drawn).toContain(mine);
    });

    it('regroups when the camera settles at a new zoom', () => {
        const renderer = fakeRenderer(19);
        const layer = withSharedClustering(renderer)
            .createMarkerLayer({ cluster: { style: clusterStyle } });

        const nearby = [
            markerAt(40.7300, -74.2700),
            markerAt(40.7302, -74.2702),
            markerAt(40.7304, -74.2698),
        ];
        layer.setMarkers(nearby);
        expect(renderer.native.drawn.length).toBeGreaterThan(1);   // zoomed in: separate

        renderer.zoom = 11;
        renderer.idle.forEach(fire => fire());
        expect(renderer.native.drawn).toHaveLength(1);             // zoomed out: one bubble
        expect(drawnCount(renderer.native.drawn[0])).toBe('3');
    });

    it('zooms to what is inside the bubble when it is clicked', () => {
        const renderer = fakeRenderer(11);
        const layer = withSharedClustering(renderer)
            .createMarkerLayer({ cluster: { style: clusterStyle } });

        layer.setMarkers([markerAt(40.7300, -74.2700), markerAt(40.7305, -74.2695)]);
        const bubble = renderer.native.drawn[0];
        bubble.onClick!({ position: bubble.position }, {} as never);

        expect(renderer.fitBounds).toHaveBeenCalledWith(
            { north: 40.7305, south: 40.73, east: -74.2695, west: -74.27 },
            { padding: 60 },
        );
    });

    it('steps the zoom when every member shares one coordinate', () => {
        // Two reports at the same address: fitting a zero-area box either does
        // nothing or slams to max zoom, depending on the vendor.
        const renderer = fakeRenderer(14);
        const layer = withSharedClustering(renderer)
            .createMarkerLayer({ cluster: { style: clusterStyle } });

        layer.setMarkers([markerAt(40.73, -74.27), markerAt(40.73, -74.27)]);
        renderer.native.drawn[0].onClick!({ position: { lat: 40.73, lng: -74.27 } }, {} as never);

        expect(renderer.fitBounds).not.toHaveBeenCalled();
        expect(renderer.setZoom).toHaveBeenCalledWith(16);
    });

    it('leaves an unclustered layer alone', () => {
        const renderer = fakeRenderer(13);
        const layer = withSharedClustering(renderer).createMarkerLayer();
        expect(layer).toBe(renderer.native);
    });
});
