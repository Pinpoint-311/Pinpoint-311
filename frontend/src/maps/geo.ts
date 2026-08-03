/**
 * Pure WGS84 / GeoJSON helpers.
 *
 * These live outside the provider adapters on purpose: bounds arithmetic,
 * point-in-polygon and feature extraction are the same maths for every vendor,
 * and every SDK offers a slightly different (and slightly wrong) version of
 * them. Doing it here means an adapter never has to.
 */

import { GeoFeature, GeometryType, LatLng, LatLngBounds } from './types';

/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Where a map points when nothing better is known.
 *
 * Five components each carried `{ lat: 40.3573, lng: -74.6672 }` commented
 * "central NJ", and one carried Newark. On a town in Oregon that is not a
 * default, it is a wrong answer rendered confidently: the map opens three
 * thousand miles away and a resident's first pin drop starts there.
 *
 * The real centre comes from the town's boundary — `default_center` on the maps
 * config is derived from it server-side, and `boundsOfGeoJson` fits to it once
 * the boundary loads. This is only for the gap before either exists, so it is
 * the middle of the contiguous states at a zoom that shows all of them:
 * obviously provisional rather than plausibly wrong.
 */
export const CONTINENTAL_US_CENTER: LatLng = { lat: 39.8283, lng: -98.5795 };
export const CONTINENTAL_US_ZOOM = 4;

export class BoundsBuilder {
    private south = Infinity;
    private west = Infinity;
    private north = -Infinity;
    private east = -Infinity;

    extend(position: LatLng): this {
        if (!Number.isFinite(position.lat) || !Number.isFinite(position.lng)) return this;
        if (position.lat < this.south) this.south = position.lat;
        if (position.lat > this.north) this.north = position.lat;
        if (position.lng < this.west) this.west = position.lng;
        if (position.lng > this.east) this.east = position.lng;
        return this;
    }

    isEmpty(): boolean {
        return !Number.isFinite(this.south);
    }

    build(): LatLngBounds | null {
        if (this.isEmpty()) return null;
        return { south: this.south, west: this.west, north: this.north, east: this.east };
    }
}

/** Walk every coordinate of a GeoJSON geometry, in [lng, lat] source order. */
function forEachCoordinate(geometry: any, visit: (position: LatLng) => void): void {
    if (!geometry) return;

    if (geometry.type === 'GeometryCollection') {
        for (const g of geometry.geometries || []) forEachCoordinate(g, visit);
        return;
    }

    const walk = (node: any): void => {
        if (!Array.isArray(node)) return;
        if (typeof node[0] === 'number' && typeof node[1] === 'number') {
            visit({ lat: node[1], lng: node[0] });
            return;
        }
        for (const child of node) walk(child);
    };

    walk(geometry.coordinates);
}

/** Every Feature in any GeoJSON shape (FeatureCollection, Feature, geometry). */
export function extractFeatures(geojson: unknown): GeoFeature[] {
    const gj = geojson as any;
    if (!gj || typeof gj !== 'object') return [];

    const raw: any[] =
        gj.type === 'FeatureCollection' ? (gj.features || [])
            : gj.type === 'Feature' ? [gj]
                : gj.type ? [{ type: 'Feature', geometry: gj, properties: {} }]
                    : [];

    return raw
        .filter(f => f?.geometry?.type)
        .map(f => {
            const geometryType = f.geometry.type as GeometryType;
            let position: LatLng | null = null;
            if (geometryType === 'Point' && Array.isArray(f.geometry.coordinates)) {
                position = { lat: f.geometry.coordinates[1], lng: f.geometry.coordinates[0] };
            }
            return {
                geometryType,
                properties: (f.properties || {}) as Record<string, unknown>,
                position,
            };
        });
}

export function boundsOfGeoJson(geojson: unknown): LatLngBounds | null {
    const gj = geojson as any;
    if (!gj || typeof gj !== 'object') return null;

    const builder = new BoundsBuilder();
    if (gj.type === 'FeatureCollection') {
        for (const feature of gj.features || []) forEachCoordinate(feature?.geometry, p => builder.extend(p));
    } else if (gj.type === 'Feature') {
        forEachCoordinate(gj.geometry, p => builder.extend(p));
    } else {
        forEachCoordinate(gj, p => builder.extend(p));
    }
    return builder.build();
}

export function boundsOfPoints(points: LatLng[]): LatLngBounds | null {
    const builder = new BoundsBuilder();
    for (const p of points) builder.extend(p);
    return builder.build();
}

/**
 * Rings of the first polygon in a GeoJSON, as {lat,lng} paths. Ring 0 is the
 * outer boundary and the rest are holes — the shape a polygon overlay wants.
 */
export function firstPolygonRings(geojson: unknown): LatLng[][] {
    const gj = geojson as any;
    if (!gj || typeof gj !== 'object') return [];

    let rings: number[][][] = [];
    const fromGeometry = (geom: any) => {
        if (!geom) return;
        if (geom.type === 'Polygon') rings = geom.coordinates || [];
        else if (geom.type === 'MultiPolygon') rings = (geom.coordinates || [])[0] || [];
    };

    if (gj.type === 'FeatureCollection') fromGeometry(gj.features?.[0]?.geometry);
    else if (gj.type === 'Feature') fromGeometry(gj.geometry);
    else fromGeometry(gj);

    return rings.map(ring => ring.map(([lng, lat]) => ({ lat, lng })));
}

// Ray casting; GeoJSON rings are [lng, lat].
function isPointInRing(lat: number, lng: number, ring: number[][]): boolean {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const lngi = ring[i][0];
        const lati = ring[i][1];
        const lngj = ring[j][0];
        const latj = ring[j][1];

        const intersect = ((lati > lat) !== (latj > lat)) &&
            (lng < (lngj - lngi) * (lat - lati) / (latj - lati) + lngi);
        if (intersect) inside = !inside;
    }
    return inside;
}

// rings[0] is the outer ring, rings[1..] are holes.
function isPointInRings(lat: number, lng: number, rings: number[][][]): boolean {
    if (!rings || rings.length === 0) return false;
    if (!isPointInRing(lat, lng, rings[0])) return false;
    for (let i = 1; i < rings.length; i++) {
        if (isPointInRing(lat, lng, rings[i])) return false;
    }
    return true;
}

/**
 * Is a point inside any polygon of a GeoJSON, respecting holes?
 * An absent or non-polygonal GeoJSON means "no constraint", so it returns true —
 * callers use this to gate out-of-jurisdiction warnings and must not start
 * rejecting pins just because a town has no boundary configured.
 */
export function isPointInGeoJson(lat: number, lng: number, geojson: unknown): boolean {
    const gj = geojson as any;
    if (!gj || typeof gj !== 'object' || Object.keys(gj).length === 0) return true;

    try {
        const polygons: number[][][][] = [];
        const collect = (geom: any) => {
            if (!geom) return;
            if (geom.type === 'Polygon') polygons.push(geom.coordinates);
            else if (geom.type === 'MultiPolygon') for (const poly of geom.coordinates || []) polygons.push(poly);
        };

        if (gj.type === 'FeatureCollection') {
            for (const feature of gj.features || []) collect(feature?.geometry);
        } else if (gj.type === 'Feature') {
            collect(gj.geometry);
        } else {
            collect(gj);
        }

        if (polygons.length === 0) return true;
        return polygons.some(rings => isPointInRings(lat, lng, rings));
    } catch (e) {
        console.warn('Failed to check boundary:', e);
        return true; // On error, allow the point.
    }
}

/**
 * Position along a polyline, as a fraction of its total length.
 *
 * Fractions rather than coordinates: a rule trimmed to "the first 40% of this
 * segment" survives the publisher re-drawing the line on a monthly refresh,
 * where a stored point would end up floating off the geometry. This mirrors
 * PostGIS ST_LineLocatePoint / ST_LineInterpolatePoint, which is what evaluates
 * the same trim server-side.
 *
 * Distances are computed with an equirectangular approximation scaled by
 * latitude. Over a single road segment the error is far below the metre or two
 * that matters here, and it avoids a haversine per vertex on every drag frame.
 */

function segmentLengths(path: LatLng[]): { lengths: number[]; total: number } {
    const lengths: number[] = [];
    let total = 0;
    for (let i = 1; i < path.length; i++) {
        const a = path[i - 1];
        const b = path[i];
        const midLat = ((a.lat + b.lat) / 2) * (Math.PI / 180);
        const dx = (b.lng - a.lng) * Math.cos(midLat);
        const dy = b.lat - a.lat;
        const d = Math.sqrt(dx * dx + dy * dy);
        lengths.push(d);
        total += d;
    }
    return { lengths, total };
}

/** The point a given fraction (0..1) along a polyline. */
export function pointAtFraction(path: LatLng[], fraction: number): LatLng | null {
    if (path.length === 0) return null;
    if (path.length === 1) return path[0];

    const { lengths, total } = segmentLengths(path);
    if (total === 0) return path[0];

    const target = Math.min(Math.max(fraction, 0), 1) * total;
    let walked = 0;
    for (let i = 0; i < lengths.length; i++) {
        if (walked + lengths[i] >= target) {
            const t = lengths[i] === 0 ? 0 : (target - walked) / lengths[i];
            const a = path[i];
            const b = path[i + 1];
            return { lat: a.lat + (b.lat - a.lat) * t, lng: a.lng + (b.lng - a.lng) * t };
        }
        walked += lengths[i];
    }
    return path[path.length - 1];
}

/**
 * How far along a polyline the nearest point to `position` lies, as a fraction.
 *
 * Used while dragging a trim handle: the handle follows the cursor but the
 * value stored is where it projects onto the road, so a handle dropped slightly
 * off the line still means a sensible position along it.
 */
export function fractionAlongLine(path: LatLng[], position: LatLng): number {
    if (path.length < 2) return 0;

    const { lengths, total } = segmentLengths(path);
    if (total === 0) return 0;

    let best = { distance: Infinity, walked: 0 };
    let walked = 0;

    for (let i = 1; i < path.length; i++) {
        const a = path[i - 1];
        const b = path[i];
        const midLat = ((a.lat + b.lat) / 2) * (Math.PI / 180);
        const scale = Math.cos(midLat);

        const ax = a.lng * scale, ay = a.lat;
        const bx = b.lng * scale, by = b.lat;
        const px = position.lng * scale, py = position.lat;

        const vx = bx - ax, vy = by - ay;
        const lengthSq = vx * vx + vy * vy;
        // Project onto the segment, clamped so a point beyond either end maps
        // to that end rather than off the line.
        const t = lengthSq === 0 ? 0 : Math.min(Math.max(((px - ax) * vx + (py - ay) * vy) / lengthSq, 0), 1);
        const dx = px - (ax + vx * t), dy = py - (ay + vy * t);
        const distance = dx * dx + dy * dy;

        if (distance < best.distance) {
            best = { distance, walked: walked + lengths[i - 1] * t };
        }
        walked += lengths[i - 1];
    }

    return Math.min(Math.max(best.walked / total, 0), 1);
}

/**
 * Extract a sub-polyline between start (0..1) and end (0..1) fractions.
 * Used for live map rendering of trimmed road segments.
 */
export function subPathByFractions(path: LatLng[], start: number, end: number): LatLng[] {
    if (path.length < 2) return path;
    const startPoint = pointAtFraction(path, start);
    const endPoint = pointAtFraction(path, end);
    if (!startPoint || !endPoint) return path;

    const s = Math.min(start, end);
    const e = Math.max(start, end);
    if (s <= 0.001 && e >= 0.999) return path;

    const { lengths, total } = segmentLengths(path);
    if (total === 0) return path;

    const targetStart = s * total;
    const targetEnd = e * total;

    const sub: LatLng[] = [startPoint];
    let walked = 0;

    for (let i = 0; i < lengths.length; i++) {
        const segStart = walked;
        if (segStart > targetStart && segStart < targetEnd) {
            sub.push(path[i]);
        }
        walked += lengths[i];
    }
    sub.push(endPoint);
    return sub;
}
