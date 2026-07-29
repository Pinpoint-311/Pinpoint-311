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
