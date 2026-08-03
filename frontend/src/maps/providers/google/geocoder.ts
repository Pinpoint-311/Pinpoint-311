/**
 * Google geocoding + Places API (New) autocomplete.
 *
 * Exclusively uses modern, non-deprecated Places API (New)
 * (`google.maps.places.AutocompleteSuggestion`).
 */

import {
    AddressSuggestion,
    AutocompleteHandle,
    AutocompleteOptions,
    GeocodeResult,
    GeocodingProvider,
    LatLng,
    LatLngBounds,
    SuggestOptions,
} from '../../types';

function toBounds(value: google.maps.LatLngBounds | null | undefined): LatLngBounds | null {
    if (!value) return null;
    const ne = value.getNorthEast();
    const sw = value.getSouthWest();
    return { south: sw.lat(), west: sw.lng(), north: ne.lat(), east: ne.lng() };
}

/** Places API (New): `AutocompleteSuggestion.fetchAutocompleteSuggestions`. */
async function suggestViaNewPlaces(
    query: string,
    options?: SuggestOptions,
): Promise<AddressSuggestion[]> {
    const places = (window.google.maps as unknown as Record<string, any>).places;
    if (!places?.AutocompleteSuggestion) {
        console.warn('Google Places API (New) AutocompleteSuggestion not available on window.google.maps.places');
        return [];
    }

    const request: Record<string, unknown> = { input: query };
    if (options?.countries?.length) request.includedRegionCodes = options.countries;
    // `geocode`, not ['street_address', 'premise'].
    //
    // Those two types only match a *specific building*, so Places (New)
    // returned nothing at all until a house number had been typed: "Springfield
    // Av" gave zero suggestions, which reads as a dead address box for the
    // whole time a resident is actually typing. They also exclude
    // `subpremise`, so flats and unit addresses were dropped even once the
    // number was there -- "42 Prospect Street, Jersey City NJ" is a
    // `subpremise` and never appeared.
    //
    // `geocode` is the collection that covers route, street_address, premise
    // and subpremise together while still excluding businesses, which is what
    // `addressesOnly` has always meant here.
    if (options?.addressesOnly) request.includedPrimaryTypes = ['geocode'];
    if (options?.biasBounds) {
        const b = options.biasBounds;
        request.locationBias = { south: b.south, west: b.west, north: b.north, east: b.east };
    }

    try {
        const { suggestions } = await places.AutocompleteSuggestion.fetchAutocompleteSuggestions(request);
        return (suggestions || [])
            .map((s: any) => s.placePrediction)
            .filter(Boolean)
            .map((p: any) => ({
                id: p.placeId,
                label: p.mainText?.text ?? p.text?.text ?? '',
                secondaryLabel: p.secondaryText?.text,
            }));
    } catch (e) {
        console.warn('Error fetching Google Places API (New) suggestions:', e);
        return [];
    }
}

export function createGoogleGeocoder(): GeocodingProvider {
    let geocoder: google.maps.Geocoder | null = null;
    const getGeocoder = () => (geocoder ??= new window.google.maps.Geocoder());

    const run = (request: google.maps.GeocoderRequest): Promise<GeocodeResult[]> =>
        new Promise(resolve => {
            const g = getGeocoder();
            if (!g) return resolve([]);
            g.geocode(request, (results, status) => {
                if (status !== 'OK' || !results) return resolve([]);
                resolve(results.map(r => ({
                    formattedAddress: r.formatted_address,
                    position: { lat: r.geometry.location.lat(), lng: r.geometry.location.lng() },
                    viewport: toBounds(r.geometry.viewport),
                })));
            });
        });

    return {
        id: 'google',

        async reverseGeocode(position: LatLng): Promise<GeocodeResult | null> {
            const results = await run({ location: position });
            return results[0] ?? null;
        },

        geocode(query: string): Promise<GeocodeResult[]> {
            return run({ address: query });
        },

        async suggest(query: string, options?: SuggestOptions): Promise<AddressSuggestion[]> {
            if (!query.trim() || !window.google?.maps) return [];
            return suggestViaNewPlaces(query, options);
        },

        async resolveSuggestion(suggestion: AddressSuggestion): Promise<GeocodeResult | null> {
            const results = await run({ placeId: suggestion.id });
            return results[0] ?? null;
        },

        // Always return null so LocationPicker uses our modern UI driven by
        // suggest() -> Places API (New), avoiding deprecated legacy Autocomplete.
        attachAutocomplete(_input: HTMLInputElement, _options: AutocompleteOptions): AutocompleteHandle | null {
            return null;
        },
    };
}

