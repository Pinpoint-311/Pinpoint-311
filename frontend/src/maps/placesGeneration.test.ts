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
 * Both generations are supported now, because towns running since before the
 * cutoff still have the legacy API and do not need a migration they did not
 * ask for.
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
        // The legacy value is `address`; the new API calls it `street_address`
        // and rejects an unrecognised type outright rather than ignoring it.
        const fetchImpl = vi.fn(async (_req: any) => ({ suggestions: [] as any[] }));
        newGeneration(fetchImpl);
        await createGoogleGeocoder().suggest!('1 Main', { addressesOnly: true, countries: ['us'] });

        const request = fetchImpl.mock.calls[0][0] as any;
        expect(request.includedPrimaryTypes).toContain('street_address');
        expect(request.includedRegionCodes).toEqual(['us']);
        expect(request.types).toBeUndefined();
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

describe('a key with the legacy Places API', () => {
    it('still uses the legacy service, so long-running towns are untouched', async () => {
        legacyGeneration([{
            place_id: 'legacy-1',
            description: '1 Main Street, Cranbury, NJ',
            structured_formatting: { main_text: '1 Main Street', secondary_text: 'Cranbury, NJ' },
        }]);

        const suggestions = await createGoogleGeocoder().suggest!('1 Main');
        expect(suggestions[0]).toEqual({
            id: 'legacy-1',
            label: '1 Main Street',
            secondaryLabel: 'Cranbury, NJ',
        });
    });

    it('still attaches the legacy widget', () => {
        legacyGeneration([]);
        const handle = createGoogleGeocoder()
            .attachAutocomplete!(document.createElement('input'), { onSelect: () => {} });
        expect(handle).not.toBeNull();
    });
});

describe('a key with neither', () => {
    it('declines the widget rather than throwing', () => {
        installPlaces({});
        expect(createGoogleGeocoder()
            .attachAutocomplete!(document.createElement('input'), { onSelect: () => {} })).toBeNull();
    });
});
