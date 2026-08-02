import { describe, it, expect, vi } from 'vitest';

import { chainGeocoders } from './registry';
import { AddressSuggestion, GeocodeResult, GeocodingProvider, LatLng } from './types';

/**
 * "All of the other lookups are working, so why is this one different?"
 *
 * Because it was the only one with no fallback.
 *
 * `geocode` and `reverseGeocode` run through the chain: the backend provider
 * answers first, from the server, and the render provider's SDK is a backstop.
 * `suggest` and `attachAutocomplete` did not. They picked the first provider
 * that implemented them -- Google -- and called it directly, uncaught.
 *
 * So when a town's browser key does not permit the Places API, address
 * resolution kept working through the backend while the address box went dead,
 * and both of those statements were true at the same time.
 *
 * The key restriction is still the thing to fix in Google Cloud. This is about
 * what the app does when it has not been.
 */

const HALL: GeocodeResult = {
    formattedAddress: '1 Main St',
    position: { lat: 40.7, lng: -74.2 },
    viewport: null,
};

function provider(id: string, overrides: Partial<GeocodingProvider> = {}): GeocodingProvider {
    return {
        id,
        reverseGeocode: async (_p: LatLng) => HALL,
        geocode: async () => [HALL],
        ...overrides,
    };
}

/** Stands in for Places being blocked on the key: the SDK is there, the call is refused. */
const blocked = () => { throw new Error('ApiTargetBlockedMapError'); };

describe('the address box degrades like everything else', () => {
    it('falls back to the next provider when the first suggester throws', () => {
        const google = provider('google', { suggest: async () => blocked() });
        const backend = provider('backend', {
            suggest: async () => [{ id: 'backend:40.7,-74.2', label: '1 Main St' }],
        });

        const chain = chainGeocoders(google, backend);
        return expect(chain.suggest!('1 Main St')).resolves.toEqual([
            { id: 'backend:40.7,-74.2', label: '1 Main St' },
        ]);
    });

    it('falls back when the first suggester returns nothing', async () => {
        // Not every failure throws. A provider with no coverage for a town
        // answers politely with an empty list, and stopping there is the same
        // dead box by a different route.
        const empty = provider('empty', { suggest: async () => [] });
        const backend = provider('backend', {
            suggest: async () => [{ id: 'b:1', label: '1 Main St' }],
        });

        const chain = chainGeocoders(empty, backend);
        expect(await chain.suggest!('1 Main St')).toHaveLength(1);
    });

    it('prefers the first provider when it works', async () => {
        // The fallback must not cost the good suggestions. Google's are better
        // -- they complete a half-typed street, which the backend cannot.
        const google = provider('google', {
            suggest: async () => [{ id: 'g:1', label: '1 Main Street, Newark NJ' }],
        });
        const backend = provider('backend', {
            suggest: vi.fn(async () => [{ id: 'b:1', label: '1 Main St' }]),
        });

        const chain = chainGeocoders(google, backend);
        expect((await chain.suggest!('1 Mai'))[0].id).toBe('g:1');
        expect(backend.suggest).not.toHaveBeenCalled();
    });

    it('does not let a fallback-only suggester hide the real one behind it', async () => {
        // This is the order the intake form actually builds:
        // chainGeocoders(backend, google). Backend first is deliberate for
        // geocode/reverseGeocode, because that is what meters usage for the cost
        // report -- but `suggest` takes the first provider that returns
        // anything, so the backend's single already-resolved match won every
        // keystroke and Google's list was never requested.
        //
        // It is not a subtle degradation either: the backend geocode is not
        // region-biased, so typing "Main St" in a New Jersey township returned
        // exactly one suggestion -- "Main St, Vancouver, BC, Canada" -- and
        // nothing else, for as long as you kept typing.
        const backend = provider('backend', {
            suggestFallbackOnly: true,
            suggest: vi.fn(async () => [{ id: 'b:1', label: 'Main St, Vancouver, BC, Canada' }]),
        });
        const google = provider('google', {
            suggest: async () => [
                { id: 'g:1', label: 'Main Street', secondaryLabel: 'Cranbury, NJ' },
            ],
        });

        const chain = chainGeocoders(backend, google);
        const results = await chain.suggest!('Main St');
        expect(results.map(r => r.id)).toEqual(['g:1']);
        expect(backend.suggest).not.toHaveBeenCalled();
    });

    it('still uses the fallback when the real suggester has nothing', async () => {
        // Reordering must not cost the fallback its reason for existing: a town
        // whose key has no Places access at all still gets a working box.
        const backend = provider('backend', {
            suggestFallbackOnly: true,
            suggest: async () => [{ id: 'b:1', label: '1 Main St' }],
        });
        const google = provider('google', { suggest: async () => [] });

        const chain = chainGeocoders(backend, google);
        expect((await chain.suggest!('1 Main St')).map(r => r.id)).toEqual(['b:1']);
    });

    it('leaves geocode and reverseGeocode backend-first, so usage stays metered', async () => {
        // The suggest reordering is scoped to suggestions. If it leaked into the
        // other two lookups it would quietly route them straight to the vendor
        // SDK and the cost-monitoring page would stop counting them.
        const backendGeocode = vi.fn(async () => [HALL]);
        const backend = provider('backend', {
            suggestFallbackOnly: true,
            suggest: async () => [],
            geocode: backendGeocode,
        });
        const google = provider('google', {
            suggest: async () => [],
            geocode: vi.fn(async () => [HALL]),
        });

        const chain = chainGeocoders(backend, google);
        await chain.geocode('1 Main St');
        expect(backendGeocode).toHaveBeenCalled();
        expect(google.geocode).not.toHaveBeenCalled();
    });

    it('returns an empty list rather than throwing when every provider fails', async () => {
        // This runs inside a keystroke handler on the intake form. An
        // unhandled rejection there is a clerk losing what they typed.
        const chain = chainGeocoders(
            provider('a', { suggest: async () => blocked() }),
            provider('b', { suggest: async () => blocked() }),
        );
        await expect(chain.suggest!('anything')).resolves.toEqual([]);
    });
});

describe('the autocomplete widget', () => {
    it('returns null instead of throwing when it cannot attach', () => {
        // The interface already promises callers a null when a provider has no
        // widget, and they fall back to suggest() plus their own list. A
        // provider whose SDK loaded but whose API is not enabled threw
        // instead, which no caller was written to expect.
        const chain = chainGeocoders(provider('google', {
            attachAutocomplete: () => blocked(),
        }));
        expect(chain.attachAutocomplete!(document.createElement('input'), { onSelect: () => {} })).toBeNull();
    });

    it('passes the handle through when it does attach', () => {
        const handle = { setBiasBounds: () => {}, destroy: () => {} };
        const chain = chainGeocoders(provider('google', { attachAutocomplete: () => handle }));
        expect(chain.attachAutocomplete!(document.createElement('input'), { onSelect: () => {} })).toBe(handle);
    });
});

describe('resolving a suggestion', () => {
    it('asks each provider until one recognises the id', async () => {
        // Ids are provider-opaque. Google's cannot be read by the backend and
        // vice versa, so resolution cannot just use the first provider.
        const google = provider('google', {
            suggest: async () => [],
            resolveSuggestion: async () => null,
        });
        const backend = provider('backend', {
            suggest: async () => [],
            resolveSuggestion: async (s: AddressSuggestion) =>
                s.id.startsWith('backend:') ? HALL : null,
        });

        const chain = chainGeocoders(google, backend);
        const result = await chain.resolveSuggestion!({ id: 'backend:40.7,-74.2', label: '1 Main St' });
        expect(result).toEqual(HALL);
    });

    it('does not let one provider throwing stop the others', async () => {
        const chain = chainGeocoders(
            provider('google', { suggest: async () => [], resolveSuggestion: async () => blocked() }),
            provider('backend', { suggest: async () => [], resolveSuggestion: async () => HALL }),
        );
        await expect(chain.resolveSuggestion!({ id: 'x', label: 'x' })).resolves.toEqual(HALL);
    });
});

describe('what was already true and must stay true', () => {
    it('still falls back for geocode, which is why other lookups kept working', async () => {
        const chain = chainGeocoders(
            provider('broken', { geocode: async () => blocked() }),
            provider('backend'),
        );
        expect(await chain.geocode('1 Main St')).toEqual([HALL]);
    });

    it('still falls back for reverse geocode', async () => {
        const chain = chainGeocoders(
            provider('broken', { reverseGeocode: async () => blocked() }),
            provider('backend'),
        );
        expect(await chain.reverseGeocode({ lat: 40.7, lng: -74.2 })).toEqual(HALL);
    });
});
