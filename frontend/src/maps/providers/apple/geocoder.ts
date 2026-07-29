/**
 * Apple geocoding behind the GeocodingProvider interface.
 *
 * Unlike the Esri geocoder this one cannot work without the SDK: Apple exposes
 * no public REST geocoding endpoint for MapKit JS credentials, so mapkit.Search
 * and mapkit.Geocoder are the only doors in and they require an initialised
 * MapKit with a valid JWT. A town wanting SDK-free geocoding should pair the
 * Apple renderer with the backend or Esri geocoder — registry.ts resolves the
 * two independently precisely so that is possible.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

import {
    AddressSuggestion,
    GeocodeResult,
    GeocodingProvider,
    LatLng,
    LatLngBounds,
    SuggestOptions,
} from '../../types';
import { appleMapKit } from './loader';

function regionFrom(mapkit: any, bounds: LatLngBounds): any {
    return new mapkit.BoundingRegion(
        bounds.north, bounds.east, bounds.south, bounds.west,
    ).toCoordinateRegion();
}

function placeToResult(place: any): GeocodeResult | null {
    const coordinate = place?.coordinate;
    if (!coordinate) return null;

    const region = place.region;
    const bounding = region?.toBoundingRegion?.();
    return {
        formattedAddress: place.formattedAddress
            ?? (place.displayLines || []).join(', ')
            ?? place.name
            ?? '',
        position: { lat: coordinate.latitude, lng: coordinate.longitude },
        viewport: bounding
            ? {
                south: bounding.southLatitude,
                west: bounding.westLongitude,
                north: bounding.northLatitude,
                east: bounding.eastLongitude,
            }
            : null,
        name: place.name || undefined,
    };
}

export interface AppleGeocoderOptions {
    /** BCP-47 language for results. */
    language?: string;
    /** Default ISO-3166-1 alpha-2 restriction. */
    countryCodes?: string[];
}

export function createAppleGeocoder(options: AppleGeocoderOptions = {}): GeocodingProvider {
    const mapkit = appleMapKit();

    let geocoder: any = null;
    const getGeocoder = () => (geocoder ??= new mapkit.Geocoder({
        language: options.language,
        getsUserLocation: false,
    }));

    let search: any = null;
    const getSearch = () => (search ??= new mapkit.Search({
        language: options.language,
        getsUserLocation: false,
    }));

    /**
     * mapkit.Search hands back an opaque completion *object* that must be passed
     * verbatim to search.search() to resolve. AddressSuggestion.id is a string,
     * so the objects are parked here under a generated id. The table is cleared
     * on each new suggest() call — resolveSuggestion is only ever called against
     * the most recent list, which is how every autocomplete UI behaves.
     */
    let completions = new Map<string, any>();
    let seed = 0;

    return {
        id: 'apple',

        reverseGeocode(position: LatLng): Promise<GeocodeResult | null> {
            return new Promise(resolve => {
                getGeocoder().reverseLookup(
                    new mapkit.Coordinate(position.lat, position.lng),
                    (error: any, data: any) => {
                        if (error) return resolve(null);
                        resolve(placeToResult((data?.results || [])[0]));
                    },
                );
            });
        },

        geocode(query: string): Promise<GeocodeResult[]> {
            if (!query.trim()) return Promise.resolve([]);
            return new Promise(resolve => {
                getGeocoder().lookup(
                    query,
                    (error: any, data: any) => {
                        if (error) return resolve([]);
                        resolve((data?.results || [])
                            .map(placeToResult)
                            .filter((r: GeocodeResult | null): r is GeocodeResult => r !== null));
                    },
                    { limitToCountries: options.countryCodes?.join(',') },
                );
            });
        },

        suggest(query: string, suggestOptions?: SuggestOptions): Promise<AddressSuggestion[]> {
            if (!query.trim()) return Promise.resolve([]);
            const countries = suggestOptions?.countries?.length
                ? suggestOptions.countries
                : options.countryCodes;

            return new Promise(resolve => {
                getSearch().autocomplete(
                    query,
                    (error: any, data: any) => {
                        if (error) return resolve([]);
                        completions = new Map();
                        const results = (data?.results || []).map((result: any) => {
                            const id = `apple-${++seed}`;
                            completions.set(id, result);
                            const lines: string[] = result.displayLines || [];
                            return {
                                id,
                                label: lines[0] ?? result.name ?? query,
                                secondaryLabel: lines.slice(1).join(', ') || undefined,
                            };
                        });
                        resolve(results);
                    },
                    {
                        includeAddresses: true,
                        // MapKit's autocomplete has no addresses-only mode; the
                        // best available approximation is to drop point-of-
                        // interest results from the request.
                        includePointsOfInterest: !suggestOptions?.addressesOnly,
                        includeQueries: false,
                        limitToCountries: countries?.join(','),
                        region: suggestOptions?.biasBounds
                            ? regionFrom(mapkit, suggestOptions.biasBounds)
                            : undefined,
                    },
                );
            });
        },

        resolveSuggestion(suggestion: AddressSuggestion): Promise<GeocodeResult | null> {
            const completion = completions.get(suggestion.id);
            const target = completion ?? [suggestion.label, suggestion.secondaryLabel]
                .filter(Boolean).join(', ');

            return new Promise(resolve => {
                getSearch().search(target, (error: any, data: any) => {
                    if (error) return resolve(null);
                    const place = (data?.places || data?.results || [])[0];
                    resolve(placeToResult(place));
                });
            });
        },

        attachAutocomplete(): null {
            // MapKit JS ships no autocomplete widget that binds to a caller's
            // <input>. mapkit.Search is a data API, and Apple's only UI surface
            // (the search control inside mapkit.Map) cannot be attached to an
            // arbitrary element or told which input to read. Returning null is
            // the interface's documented signal to fall back to suggest().
            return null;
        },
    };
}
