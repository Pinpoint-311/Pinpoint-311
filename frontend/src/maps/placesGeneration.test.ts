import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { createGoogleGeocoder } from './providers/google/geocoder';

/**
 * "But I've been using the new one."
 *
 * On 1 March 2025 Google closed the legacy Places API to new customers. A
 * project created after that date can enable **Places API (New)** and nothing
 * else. This codebase called only the legacy surface --
 * `places.Autocomplete` and `places.AutocompleteService` -- so a correctly
 * configured new-generation key produced:
 *
 *     ApiTargetBlockedMapError
 *     "This API key is not authorized to use this service or API."
 *
 * which reads as a key problem and sent everybody to the Cloud console to
 * enable an API that was already enabled. The key was right. The code was
 * asking for a generation Google no longer issues.
 *
 * Places API (New) is now the only surface this provider calls. Legacy is not
 * a second path it falls back to: Google closed it to new projects, so the
 * generation a town has is decided by when its project was created rather than
 * by anything the app can choose, and keeping two code paths meant the one
 * nobody could reach still had to be reasoned about. A town whose key predates
 * the cutoff must enable Places API (New) alongside what it already has.
 */

const original = (globalThis as any).window?.google;

function installPlaces(places: Record<string, unknown>) {
    (globalThis as any).window = (globalThis as any).window || {};
    (globalThis as any).window.google = {
        maps: {
            places,
            Geocoder: class { geocode(_r: unknown, cb: (r: null, s: string) => void) { cb(null, 'ZERO_RESULTS'); } },
            LatLngBounds: class { constructor(_a: unknown, _b: unknown) {} },
        },
    };
}

/** Places API (New). No `Autocomplete`, no `AutocompleteService`. */
function newGeneration(fetchImpl: (req: any) => Promise<any>) {
    installPlaces({
        AutocompleteSuggestion: { fetchAutocompleteSuggestions: fetchImpl },
    });
}

/** Places API (Legacy). What a long-standing project still has. */
function legacyGeneration(predictions: any[]) {
    installPlaces({
        Autocomplete: class { addListener() { return {}; } setBounds() {} },
        AutocompleteService: class {
            getPlacePredictions(_r: unknown, cb: (p: any[]) => void) { cb(predictions); }
        },
    });
}

afterEach(() => {
    if (original) (globalThis as any).window.google = original;
});

describe('a key with only Places API (New)', () => {
    beforeEach(() => {
        newGeneration(async () => ({
            suggestions: [{
                placePrediction: {
                    placeId: 'abc',
                    mainText: { text: '1 Main Street' },
                    secondaryText: { text: 'Cranbury, NJ' },
                },
            }],
        }));
    });

    it('returns suggestions instead of failing', async () => {
        const suggestions = await createGoogleGeocoder().suggest!('1 Main');
        expect(suggestions).toEqual([
            { id: 'abc', label: '1 Main Street', secondaryLabel: 'Cranbury, NJ' },
        ]);
    });

    it('declines to attach the legacy widget rather than throwing', () => {
        // Constructing places.Autocomplete on this key is what produced
        // ApiTargetBlockedMapError. Null is the interface's own word for "no
        // widget here" and callers already know to render their own list.
        const handle = createGoogleGeocoder()
            .attachAutocomplete!(document.createElement('input'), { onSelect: () => {} });
        expect(handle).toBeNull();
    });

    it('translates "addresses only" into the types the new API accepts', async () => {
        // The legacy value is `address`, which the new API rejects outright
        // rather than ignoring. `geocode` is its equivalent collection.
        const fetchImpl = vi.fn(async (_req: any) => ({ suggestions: [] as any[] }));
        newGeneration(fetchImpl);
        await createGoogleGeocoder().suggest!('1 Main', { addressesOnly: true, countries: ['us'] });

        const request = fetchImpl.mock.calls[0][0] as any;
        expect(request.includedPrimaryTypes).toEqual(['geocode']);
        expect(request.includedRegionCodes).toEqual(['us']);
        expect(request.types).toBeUndefined();
    });

    it('does not narrow "addresses only" to a specific building', async () => {
        // `street_address` and `premise` only match a whole building, so Places
        // (New) returned nothing at all until a house number had been typed --
        // "Springfield Av" gave an empty list, which is a dead address box for
        // the entire time a resident is actually typing. They also exclude
        // `subpremise`, dropping flats and unit addresses even once the number
        // was there. Asking for the narrower pair is the bug, not a detail.
        const fetchImpl = vi.fn(async (_req: any) => ({ suggestions: [] as any[] }));
        newGeneration(fetchImpl);
        await createGoogleGeocoder().suggest!('Springfield Av', { addressesOnly: true });

        const types = (fetchImpl.mock.calls[0][0] as any).includedPrimaryTypes as string[];
        expect(types).not.toContain('street_address');
        expect(types).not.toContain('premise');
    });

    it('passes viewport bias in the shape the new API wants', async () => {
        const fetchImpl = vi.fn(async (_req: any) => ({ suggestions: [] as any[] }));
        newGeneration(fetchImpl);
        await createGoogleGeocoder().suggest!('1 Main', {
            biasBounds: { south: 40, west: -75, north: 41, east: -74 },
        });
        expect((fetchImpl.mock.calls[0][0] as any).locationBias)
            .toEqual({ south: 40, west: -75, north: 41, east: -74 });
    });

    it('survives a response with no suggestions field', async () => {
        newGeneration(async () => ({}));
        await expect(createGoogleGeocoder().suggest!('x')).resolves.toEqual([]);
    });
});

describe('a key with only the legacy Places API', () => {
    // These two used to assert the opposite -- that the legacy service was
    // still called and the legacy widget still attached. That stopped being
    // true when Places (New) became the only surface, and the assertions were
    // left behind, so the suite was reporting on a code path that no longer
    // existed. What matters for such a town is that it degrades quietly and the
    // Test button on the setup page tells them which API to enable, which is
    // what the backend check now does.
    it('offers no suggestions rather than throwing', async () => {
        legacyGeneration([{
            place_id: 'legacy-1',
            description: '1 Main Street, Cranbury, NJ',
            structured_formatting: { main_text: '1 Main Street', secondary_text: 'Cranbury, NJ' },
        }]);

        await expect(createGoogleGeocoder().suggest!('1 Main')).resolves.toEqual([]);
    });

    it('declines the legacy widget too, so the caller renders its own list', () => {
        // Constructing places.Autocomplete is what produced
        // ApiTargetBlockedMapError on a new-generation key, so this provider no
        // longer constructs it for anyone.
        legacyGeneration([]);
        const handle = createGoogleGeocoder()
            .attachAutocomplete!(document.createElement('input'), { onSelect: () => {} });
        expect(handle).toBeNull();
    });
});

describe('a key with neither', () => {
    it('declines the widget rather than throwing', () => {
        installPlaces({});
        expect(createGoogleGeocoder()
            .attachAutocomplete!(document.createElement('input'), { onSelect: () => {} })).toBeNull();
    });
});
