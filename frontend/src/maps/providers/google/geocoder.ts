/**
 * Google geocoding + Places autocomplete behind the GeocodingProvider interface.
 *
 * Deliberately separate from the renderer: a town can render Esri tiles and
 * still resolve addresses here, and vice versa. Nothing in this file needs a
 * map object — the caller feeds viewport bias in through
 * AutocompleteHandle.setBiasBounds, which is why the two halves stay decoupled.
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

function fromBounds(bounds: LatLngBounds): google.maps.LatLngBounds {
    return new window.google.maps.LatLngBounds(
        { lat: bounds.south, lng: bounds.west },
        { lat: bounds.north, lng: bounds.east },
    );
}

function toResult(place: google.maps.places.PlaceResult): GeocodeResult | null {
    const location = place.geometry?.location;
    if (!location) return null;
    return {
        formattedAddress: place.formatted_address || place.name || '',
        position: { lat: location.lat(), lng: location.lng() },
        viewport: toBounds(place.geometry?.viewport),
        name: place.name,
    };
}

/**
 * Which generation of the Places API this key can actually use.
 *
 * On 1 March 2025 Google closed the legacy Places API to new customers. A
 * project created after that date can enable "Places API (New)" and nothing
 * else -- and the legacy classes this file used to call exclusively
 * (`places.Autocomplete`, `places.AutocompleteService`) then fail with
 * `ApiTargetBlockedMapError`, which reads as "your key is not authorized" and
 * sends everybody to the Cloud console to enable an API that is already
 * enabled. The key was right. The code was asking for the wrong generation.
 *
 * Both are supported here rather than picking one, because towns that have
 * been running for years still have the legacy API and switching them for no
 * reason is a migration they did not ask for.
 */
function hasNewPlaces(): boolean {
    const places = (window.google?.maps as unknown as Record<string, unknown> | undefined)?.places;
    return !!(places as Record<string, unknown> | undefined)?.AutocompleteSuggestion;
}

/** Places API (New): `AutocompleteSuggestion.fetchAutocompleteSuggestions`. */
async function suggestViaNewPlaces(
    query: string,
    options?: SuggestOptions,
): Promise<AddressSuggestion[]> {
    const places = (window.google.maps as unknown as Record<string, any>).places;
    const request: Record<string, unknown> = { input: query };
    if (options?.countries?.length) request.includedRegionCodes = options.countries;
    // "address" in the legacy API is `street_address` here, and the new API
    // rejects an unknown type rather than ignoring it.
    if (options?.addressesOnly) request.includedPrimaryTypes = ['street_address', 'premise'];
    if (options?.biasBounds) {
        const b = options.biasBounds;
        request.locationBias = { south: b.south, west: b.west, north: b.north, east: b.east };
    }

    const { suggestions } = await places.AutocompleteSuggestion
        .fetchAutocompleteSuggestions(request);

    return (suggestions || [])
        .map((s: any) => s.placePrediction)
        .filter(Boolean)
        .map((p: any) => ({
            // The id carries the prediction so resolveSuggestion can call
            // toPlace() on it -- the new API has no "look this up by id later"
            // that does not cost a second billed request.
            id: p.placeId,
            label: p.mainText?.text ?? p.text?.text ?? '',
            secondaryLabel: p.secondaryText?.text,
        }));
}

/** Places API (Legacy): `AutocompleteService.getPlacePredictions`. */
function suggestViaLegacyPlaces(
    service: google.maps.places.AutocompleteService,
    query: string,
    options: SuggestOptions | undefined,
    toGoogleBounds: (b: LatLngBounds) => google.maps.LatLngBounds,
): Promise<AddressSuggestion[]> {
    const request: google.maps.places.AutocompletionRequest = {
        input: query,
        types: options?.addressesOnly ? ['address'] : undefined,
        componentRestrictions: options?.countries?.length
            ? { country: options.countries }
            : undefined,
        bounds: options?.biasBounds ? toGoogleBounds(options.biasBounds) : undefined,
    };
    return new Promise(resolve => {
        service.getPlacePredictions(request, predictions => {
            resolve((predictions || []).map(p => ({
                id: p.place_id,
                label: p.structured_formatting?.main_text || p.description,
                secondaryLabel: p.structured_formatting?.secondary_text,
            })));
        });
    });
}

export function createGoogleGeocoder(): GeocodingProvider {
    let geocoder: google.maps.Geocoder | null = null;
    const getGeocoder = () => (geocoder ??= new window.google.maps.Geocoder());

    let autocompleteService: google.maps.places.AutocompleteService | null = null;
    const getAutocompleteService = () => {
        const places = (window.google?.maps as unknown as Record<string, unknown> | undefined)?.places as unknown as Record<string, unknown> | undefined;
        if (!places?.AutocompleteService) return null;
        return (autocompleteService ??= new window.google.maps.places.AutocompleteService());
    };

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
            if (hasNewPlaces()) return suggestViaNewPlaces(query, options);
            const svc = getAutocompleteService();
            if (!svc) return [];
            return suggestViaLegacyPlaces(svc, query, options, fromBounds);
        },

        async resolveSuggestion(suggestion: AddressSuggestion): Promise<GeocodeResult | null> {
            // Resolving a prediction by place_id through the Geocoder rather than
            // PlacesService avoids needing a DOM node to host the service.
            const results = await run({ placeId: suggestion.id });
            return results[0] ?? null;
        },

        attachAutocomplete(input: HTMLInputElement, options: AutocompleteOptions): AutocompleteHandle | null {
            const places = window.google?.maps?.places as unknown as Record<string, unknown> | undefined;
            if (!places?.Autocomplete || hasNewPlaces()) return null;

            try {
                const autocomplete = new window.google.maps.places.Autocomplete(input, {
                    types: options.addressesOnly ? ['address'] : undefined,
                    componentRestrictions: options.countries?.length
                        ? { country: options.countries }
                        : undefined,
                    fields: ['formatted_address', 'geometry', 'name'],
                });

                const listener = autocomplete.addListener('place_changed', () => {
                    const result = toResult(autocomplete.getPlace());
                    if (result) options.onSelect(result);
                });

                if (options.biasBounds) autocomplete.setBounds(fromBounds(options.biasBounds));

                return {
                    setBiasBounds(bounds: LatLngBounds | null): void {
                        if (bounds) autocomplete.setBounds(fromBounds(bounds));
                    },
                    destroy(): void {
                        window.google.maps.event.removeListener(listener);
                        window.google.maps.event.clearInstanceListeners(autocomplete);
                        // Google leaves its .pac-container attached to <body> after the
                        // input goes away; strays would otherwise float over the page.
                        document.querySelectorAll('.pac-container').forEach(node => {
                            if (!document.body.contains(input)) node.remove();
                        });
                    },
                };
            } catch (e) {
                console.warn('Google Places legacy Autocomplete unavailable, falling back to suggest():', e);
                return null;
            }
        },
    };
}
