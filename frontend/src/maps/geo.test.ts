import { describe, expect, it } from 'vitest';

import {
    boundsOfGeoJson,
    boundsOfPoints,
    fractionAlongLine,
    isPointInGeoJson,
    pointAtFraction,
} from './geo';

/**
 * This module holds the geometry that two different components previously
 * implemented slightly differently by hand, plus the line maths that decides
 * where a trim handle sits. None of it had tests.
 *
 * The line-fraction pair is the load-bearing part: pointAtFraction places the
 * handle, fractionAlongLine reads it back after a drag, and PostGIS evaluates
 * the same fraction server-side. If those three disagree, a clerk drags a
 * handle and the rule applies somewhere else.
 */

// A straight east-west line at a fixed latitude, so distances along it are
// proportional to longitude and the expected values are obvious.
const STRAIGHT = [
    { lat: 40.0, lng: -74.0 },
    { lat: 40.0, lng: -73.0 },
];

const BENT = [
    { lat: 40.0, lng: -74.0 },
    { lat: 40.0, lng: -73.5 },
    { lat: 40.5, lng: -73.5 },
];

describe('pointAtFraction', () => {
    it('returns the ends at 0 and 1', () => {
        expect(pointAtFraction(STRAIGHT, 0)).toEqual(STRAIGHT[0]);
        expect(pointAtFraction(STRAIGHT, 1)).toEqual(STRAIGHT[1]);
    });

    it('interpolates the midpoint', () => {
        const mid = pointAtFraction(STRAIGHT, 0.5)!;
        expect(mid.lng).toBeCloseTo(-73.5, 6);
        expect(mid.lat).toBeCloseTo(40.0, 6);
    });

    it('clamps a fraction outside 0..1 instead of extrapolating off the road', () => {
        expect(pointAtFraction(STRAIGHT, -5)).toEqual(STRAIGHT[0]);
        expect(pointAtFraction(STRAIGHT, 99)).toEqual(STRAIGHT[1]);
    });

    it('walks past a vertex on a bent line', () => {
        // Both legs are similar in length, so 0.75 lands on the second leg.
        const p = pointAtFraction(BENT, 0.75)!;
        expect(p.lng).toBeCloseTo(-73.5, 3);
        expect(p.lat).toBeGreaterThan(40.0);
    });

    it('handles degenerate paths without throwing', () => {
        expect(pointAtFraction([], 0.5)).toBeNull();
        expect(pointAtFraction([{ lat: 1, lng: 2 }], 0.5)).toEqual({ lat: 1, lng: 2 });
        // A zero-length line has no "along"; the start is the only sane answer.
        const same = [{ lat: 1, lng: 2 }, { lat: 1, lng: 2 }];
        expect(pointAtFraction(same, 0.5)).toEqual(same[0]);
    });
});

describe('fractionAlongLine', () => {
    it('reads back what pointAtFraction placed', () => {
        // The property that matters: place a handle, drag nothing, read it back.
        for (const f of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]) {
            const point = pointAtFraction(STRAIGHT, f)!;
            expect(fractionAlongLine(STRAIGHT, point)).toBeCloseTo(f, 4);
        }
    });

    it('round-trips on a bent line too', () => {
        for (const f of [0.2, 0.5, 0.8]) {
            const point = pointAtFraction(BENT, f)!;
            expect(fractionAlongLine(BENT, point)).toBeCloseTo(f, 3);
        }
    });

    it('projects a point dropped beside the line onto it', () => {
        // A handle released slightly off the road should still mean a sensible
        // position along it, not snap to an end.
        const beside = { lat: 40.01, lng: -73.5 };
        expect(fractionAlongLine(STRAIGHT, beside)).toBeCloseTo(0.5, 2);
    });

    it('clamps a point dragged beyond an end', () => {
        expect(fractionAlongLine(STRAIGHT, { lat: 40, lng: -80 })).toBe(0);
        expect(fractionAlongLine(STRAIGHT, { lat: 40, lng: -60 })).toBe(1);
    });

    it('never returns a value outside 0..1', () => {
        for (const p of [{ lat: 90, lng: 180 }, { lat: -90, lng: -180 }, { lat: 0, lng: 0 }]) {
            const f = fractionAlongLine(BENT, p);
            expect(f).toBeGreaterThanOrEqual(0);
            expect(f).toBeLessThanOrEqual(1);
        }
    });

    it('handles degenerate paths without throwing', () => {
        expect(fractionAlongLine([], { lat: 1, lng: 1 })).toBe(0);
        expect(fractionAlongLine([{ lat: 1, lng: 1 }], { lat: 1, lng: 1 })).toBe(0);
    });
});

describe('bounds', () => {
    it('covers every point', () => {
        const b = boundsOfPoints([
            { lat: 40, lng: -74 }, { lat: 41, lng: -73 }, { lat: 39, lng: -75 },
        ])!;
        expect(b.south).toBe(39);
        expect(b.north).toBe(41);
        expect(b.west).toBe(-75);
        expect(b.east).toBe(-73);
    });

    it('is null for nothing, rather than a zero-size box at the equator', () => {
        expect(boundsOfPoints([])).toBeNull();
        expect(boundsOfGeoJson({ type: 'FeatureCollection', features: [] })).toBeNull();
    });

    it('reads a FeatureCollection', () => {
        const b = boundsOfGeoJson({
            type: 'FeatureCollection',
            features: [{
                type: 'Feature',
                properties: {},
                geometry: { type: 'LineString', coordinates: [[-74, 40], [-73, 41]] },
            }],
        })!;
        expect(b.south).toBe(40);
        expect(b.north).toBe(41);
    });

    it('ignores junk instead of throwing', () => {
        expect(boundsOfGeoJson(null)).toBeNull();
        expect(boundsOfGeoJson({ type: 'Nonsense' })).toBeNull();
    });
});

describe('isPointInGeoJson', () => {
    const SQUARE = {
        type: 'Feature',
        properties: {},
        geometry: {
            type: 'Polygon',
            coordinates: [[[-74, 40], [-73, 40], [-73, 41], [-74, 41], [-74, 40]]],
        },
    };

    it('accepts an interior point', () => {
        expect(isPointInGeoJson(40.5, -73.5, SQUARE)).toBe(true);
    });

    it('rejects an exterior point', () => {
        expect(isPointInGeoJson(42, -73.5, SQUARE)).toBe(false);
        expect(isPointInGeoJson(40.5, -80, SQUARE)).toBe(false);
    });

    it('treats "no boundary configured" as everything being in bounds', () => {
        // Fail open, and this direction is the whole point: a town that has not
        // drawn its boundary yet must not have every report rejected as out of
        // area. I initially wrote this test the other way round and the code was
        // right, not the test.
        expect(isPointInGeoJson(40.5, -73.5, null)).toBe(true);
        expect(isPointInGeoJson(40.5, -73.5, {})).toBe(true);
    });

    it('is false rather than throwing on malformed geometry', () => {
        expect(isPointInGeoJson(40.5, -73.5, { type: 'Polygon', coordinates: 'nope' })).toBe(false);
    });
});
