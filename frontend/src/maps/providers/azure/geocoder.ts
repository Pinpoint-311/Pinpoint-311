/**
 * Azure Maps Search behind the GeocodingProvider interface.
 *
 * The Web SDK does not bundle a search client (that is a separate
 * azure-maps-rest package), and the Search REST API is a handful of GETs, so
 * this talks to it directly with the same subscription key the renderer uses.
 * That also keeps geocoding usable without loading the map SDK at all — which
 * is the whole reason rendering and geocoding are separate interfaces.
 *
 * `attachAutocomplete` returns null: Azure ships no input widget of any kind.
 * Type-ahead is `suggest()` on top of Fuzzy Search with `typeahead=true`, and
 * callers render their own list.
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

const DEFAULT_DOMAIN = 'atlas.microsoft.com';
const API_VERSION = '1.0';

interface AzurePoint { lat: number; lon: number }

interface AzureSearchResult {
    id?: string;
    type?: string;
    address?: {
        freeformAddress?: string;
        streetNameAndNumber?: string;
        municipality?: string;
        countrySubdivision?: string;
        postalCode?: string;
        country?: string;
    };
    poi?: { name?: string };
    position?: AzurePoint;
    viewport?: { topLeftPoint?: AzurePoint; btmRightPoint?: AzurePoint };
}

function toViewport(viewport: AzureSearchResult['viewport']): LatLngBounds | null {
    const topLeft = viewport?.topLeftPoint;
    const bottomRight = viewport?.btmRightPoint;
    if (!topLeft || !bottomRight) return null;
    return { north: topLeft.lat, west: topLeft.lon, south: bottomRight.lat, east: bottomRight.lon };
}

function toResult(result: AzureSearchResult): GeocodeResult | null {
    if (!result.position) return null;
    return {
        formattedAddress: result.address?.freeformAddress ?? result.poi?.name ?? '',
        position: { lat: result.position.lat, lng: result.position.lon },
        viewport: toViewport(result.viewport),
        name: result.poi?.name,
    };
}

function secondaryLabel(result: AzureSearchResult): string {
    return [result.address?.municipality, result.address?.countrySubdivision, result.address?.postalCode]
        .filter(Boolean)
        .join(', ');
}

export interface AzureGeocoderOptions {
    /** Geography-specific endpoint, e.g. 'us.atlas.microsoft.com'. */
    domain?: string;
    language?: string;
}

export function createAzureGeocoder(
    subscriptionKey: string,
    options?: AzureGeocoderOptions,
): GeocodingProvider {
    const domain = (options?.domain ?? DEFAULT_DOMAIN).replace(/^https?:\/\//, '').replace(/\/$/, '');
    const language = options?.language;

    // resolveSuggestion() should not cost a second billed call; Fuzzy Search
    // already returns coordinates with every prediction.
    const resolved = new Map<string, GeocodeResult>();

    const request = async (path: string, params: URLSearchParams): Promise<any> => {
        params.set('api-version', API_VERSION);
        params.set('subscription-key', subscriptionKey);
        if (language) params.set('language', language);
        const response = await fetch(`https://${domain}${path}?${params.toString()}`);
        if (!response.ok) throw new Error(`Azure Maps search failed: ${response.status}`);
        return response.json();
    };

    const fuzzy = async (
        query: string,
        limit: number,
        typeahead: boolean,
        suggestOptions?: SuggestOptions,
    ): Promise<AzureSearchResult[]> => {
        const params = new URLSearchParams({ query, limit: String(limit) });
        if (typeahead) params.set('typeahead', 'true');
        if (suggestOptions?.countries?.length) params.set('countrySet', suggestOptions.countries.join(','));
        // Azure biases with a lat/lon pair rather than a box, so the bias bounds
        // are reduced to their centre.
        const bias = suggestOptions?.biasBounds;
        if (bias) {
            params.set('lat', String((bias.south + bias.north) / 2));
            params.set('lon', String((bias.west + bias.east) / 2));
        }
        if (suggestOptions?.addressesOnly) params.set('idxSet', 'PAD,Addr,Str');

        const body = await request('/search/fuzzy/json', params);
        return (body?.results ?? []) as AzureSearchResult[];
    };

    return {
        id: 'azure',

        async reverseGeocode(position: LatLng): Promise<GeocodeResult | null> {
            const params = new URLSearchParams({ query: `${position.lat},${position.lng}` });
            const body = await request('/search/address/reverse/json', params);
            const address = body?.addresses?.[0];
            if (!address?.address?.freeformAddress) return null;

            // The reverse endpoint returns "lat,lon" as a string rather than the
            // {lat, lon} object every other endpoint uses.
            const [lat, lon] = String(address.position ?? '').split(',').map(Number);
            return {
                formattedAddress: address.address.freeformAddress,
                position: {
                    lat: Number.isFinite(lat) ? lat : position.lat,
                    lng: Number.isFinite(lon) ? lon : position.lng,
                },
            };
        },

        async geocode(query: string): Promise<GeocodeResult[]> {
            if (!query.trim()) return [];
            const results = await fuzzy(query, 5, false);
            return results.map(toResult).filter((r): r is GeocodeResult => !!r);
        },

        async suggest(query: string, suggestOptions?: SuggestOptions): Promise<AddressSuggestion[]> {
            if (!query.trim()) return [];
            const results = await fuzzy(query, 8, true, suggestOptions);

            return results.flatMap((result, index) => {
                const geocoded = toResult(result);
                if (!geocoded) return [];
                const id = result.id ?? `${geocoded.position.lat},${geocoded.position.lng}:${index}`;
                resolved.set(id, geocoded);
                return [{
                    id,
                    label: result.poi?.name
                        ?? result.address?.streetNameAndNumber
                        ?? result.address?.freeformAddress
                        ?? '',
                    secondaryLabel: secondaryLabel(result),
                }];
            });
        },

        async resolveSuggestion(suggestion: AddressSuggestion): Promise<GeocodeResult | null> {
            return resolved.get(suggestion.id) ?? null;
        },

        attachAutocomplete(_input: HTMLInputElement, _options: AutocompleteOptions): AutocompleteHandle | null {
            // No Azure equivalent of google.maps.places.Autocomplete exists.
            return null;
        },
    };
}
