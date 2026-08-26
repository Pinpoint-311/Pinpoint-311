import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { createEsriGeocoder, ESRI_WORLD_GEOCODER } from './geocoder';

/**
 * `biasBounds` is a bias, and the Esri adapter used to make it a filter.
 *
 * SuggestOptions.biasBounds carries the map's current viewport, which is what
 * every caller has to hand and what Google's Places widget takes as
 * `locationBias`. ArcGIS's `searchExtent` looks like the same idea and is not:
 * it discards every candidate outside the envelope. So the address box worked
 * only while the map happened to be showing the whole town, and returned an
 * empty list from the moment a resident zoomed in or dropped a pin -- with the
 * requests going out and coming back HTTP 200 the whole time, which is why this
 * looked like "Places is not enabled on the key".
 *
 * Checked against the live World locator while fixing it: "main st" biased to
 * the town's extent returns 3 suggestions; the same query with a street-level
 * extent returns 0; the same query with `location` set to that street-level
 * point returns 8, town-first.
 *
 * These tests read the URL the adapter builds. Asserting the absence of
 * `searchExtent` matters as much as the presence of `location` -- sending both
 * would reinstate the filter.
 */

const bounds = { south: 40.7436, west: -74.2925, north: 40.7446, east: -74.2905 };

let calls: string[] = [];

function respond(body: unknown) {
    return Promise.resolve({ ok: true, status: 200, json: async () => body } as unknown as Response);
}

beforeEach(() => {
    calls = [];
    vi.stubGlobal('fetch', vi.fn((url: string) => {
        calls.push(String(url));
        return respond({ suggestions: [{ text: 'Main St, Maplewood, NJ, 07040, USA', magicKey: 'mk1' }] });
    }));
});

afterEach(() => {
    vi.unstubAllGlobals();
});

const params = (index = 0) => new URL(calls[index]).searchParams;

describe('Esri suggest bias', () => {
    it('sends the viewport as a proximity bias, not as a bounding filter', async () => {
        const geocoder = createEsriGeocoder({ token: 'k' });
        await geocoder.suggest!('main st', { biasBounds: bounds });

        expect(calls).toHaveLength(1);
        const q = params();

        // searchExtent would exclude everything outside a street-level box.
        expect(q.get('searchExtent')).toBeNull();

        const location = JSON.parse(q.get('location')!);
        expect(location.spatialReference).toEqual({ wkid: 4326 });
        // The centre of the bias bounds, in lng/lat order for ArcGIS.
        expect(location.x).toBeCloseTo((bounds.west + bounds.east) / 2, 9);
        expect(location.y).toBeCloseTo((bounds.south + bounds.north) / 2, 9);
    });

    it('omits the bias entirely when the caller has no viewport yet', async () => {
        const geocoder = createEsriGeocoder({ token: 'k' });
        await geocoder.suggest!('main st', { biasBounds: null });

        const q = params();
        expect(q.get('location')).toBeNull();
        expect(q.get('searchExtent')).toBeNull();
        expect(q.get('text')).toBe('main st');
    });

    it('still filters by country, which is the one restriction the caller means', async () => {
        const geocoder = createEsriGeocoder({ token: 'k', countryCodes: ['USA'] });
        await geocoder.suggest!('main st', { biasBounds: bounds, countries: ['us'] });

        expect(params().get('countryCode')).toBe('us');
    });

    it('asks the configured locator rather than the world service', async () => {
        const geocoder = createEsriGeocoder({
            serviceUrl: 'https://gis.example-county.gov/arcgis/rest/services/Composite/GeocodeServer/',
            token: 'k',
        });
        await geocoder.suggest!('main st', { biasBounds: bounds });

        expect(calls[0]).toContain('https://gis.example-county.gov/arcgis/rest/services/Composite/GeocodeServer/suggest');
        expect(calls[0]).not.toContain(ESRI_WORLD_GEOCODER);
    });

    it('returns the suggestions the service sent, split into two lines', async () => {
        const geocoder = createEsriGeocoder({ token: 'k' });
        const results = await geocoder.suggest!('main st', { biasBounds: bounds });

        expect(results).toHaveLength(1);
        expect(results[0].label).toBe('Main St');
        expect(results[0].secondaryLabel).toBe('Maplewood, NJ, 07040, USA');
        expect(results[0].id).toBe('mk1');
    });

    it('reports an ArcGIS error member rather than treating HTTP 200 as success', async () => {
        vi.stubGlobal('fetch', vi.fn(() => respond({ error: { code: 498, message: 'Invalid Token' } })));
        const geocoder = createEsriGeocoder({ token: 'bad' });

        await expect(geocoder.suggest!('main st', { biasBounds: bounds })).rejects.toThrow('Invalid Token');
    });
});
