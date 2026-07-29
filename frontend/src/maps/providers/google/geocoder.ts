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

export function createGoogleGeocoder(): GeocodingProvider {
    let geocoder: google.maps.Geocoder | null = null;
    const getGeocoder = () => (geocoder ??= new window.google.maps.Geocoder());

    let autocompleteService: google.maps.places.AutocompleteService | null = null;
    const getAutocompleteService = () =>
        (autocompleteService ??= new window.google.maps.places.AutocompleteService());

    const run = (request: google.maps.GeocoderRequest): Promise<GeocodeResult[]> =>
        new Promise(resolve => {
            getGeocoder().geocode(request, (results, status) => {
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
            if (!query.trim()) return [];
            const request: google.maps.places.AutocompletionRequest = {
                input: query,
                types: options?.addressesOnly ? ['address'] : undefined,
                componentRestrictions: options?.countries?.length
                    ? { country: options.countries }
                    : undefined,
                bounds: options?.biasBounds ? fromBounds(options.biasBounds) : undefined,
            };
            return new Promise(resolve => {
                getAutocompleteService().getPlacePredictions(request, predictions => {
                    resolve((predictions || []).map(p => ({
                        id: p.place_id,
                        label: p.structured_formatting?.main_text || p.description,
                        secondaryLabel: p.structured_formatting?.secondary_text,
                    })));
                });
            });
        },

        async resolveSuggestion(suggestion: AddressSuggestion): Promise<GeocodeResult | null> {
            // Resolving a prediction by place_id through the Geocoder rather than
            // PlacesService avoids needing a DOM node to host the service.
            const results = await run({ placeId: suggestion.id });
            return results[0] ?? null;
        },

        attachAutocomplete(input: HTMLInputElement, options: AutocompleteOptions): AutocompleteHandle {
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
        },
    };
}
