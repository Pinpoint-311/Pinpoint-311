/**
 * Geocoding for MapLibre towns.
 *
 * MapLibre GL has no geocoding whatsoever — it is a renderer and nothing else.
 * So this provider is assembled from two independent services:
 *
 *  - `suggest()` uses Photon (photon.komoot.io), an OSM-backed, type-ahead
 *    oriented search that needs no key. NOTE: the public instance carries no
 *    service guarantee, is rate-limited at the operator's discretion, and is
 *    explicitly intended to be self-hosted for production use — point
 *    `options.photonUrl` at your own instance.
 *  - `geocode()` / `reverseGeocode()` prefer Pinpoint's own backend geocoder,
 *    which is metered for the cost-monitoring page and is usually configured
 *    against a better address source than OSM. Photon is only the fallback.
 *
 * `attachAutocomplete` returns null: there is no vendor widget to attach, and
 * the interface already documents that callers fall back to suggest() plus
 * their own list. That is the honest answer, not a missing feature.
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
import { backendGeocodingProvider } from '../backend';

const DEFAULT_PHOTON_URL = 'https://photon.komoot.io';

/** Photon `properties.type` values that are street addresses rather than areas. */
const ADDRESS_TYPES = new Set(['house', 'street']);

interface PhotonProperties {
    name?: string;
    housenumber?: string;
    street?: string;
    city?: string;
    district?: string;
    state?: string;
    postcode?: string;
    country?: string;
    countrycode?: string;
    type?: string;
    osm_id?: number;
    osm_type?: string;
    extent?: [number, number, number, number];
}

interface PhotonFeature {
    geometry?: { coordinates?: [number, number] };
    properties?: PhotonProperties;
}

function primaryLabel(properties: PhotonProperties): string {
    if (properties.name) return properties.name;
    const street = [properties.housenumber, properties.street].filter(Boolean).join(' ');
    return street || properties.city || properties.state || properties.country || '';
}

function secondaryLabel(properties: PhotonProperties): string {
    return [properties.city ?? properties.district, properties.state, properties.postcode, properties.country]
        .filter(Boolean)
        .join(', ');
}

function formatAddress(properties: PhotonProperties): string {
    const head = [properties.housenumber, properties.street].filter(Boolean).join(' ');
    return [head || properties.name, properties.city ?? properties.district, properties.state, properties.postcode, properties.country]
        .filter(Boolean)
        .join(', ');
}

/** Photon's `extent` is [minLon, maxLat, maxLon, minLat] — not a standard bbox. */
function toViewport(extent: PhotonProperties['extent']): LatLngBounds | null {
    if (!extent || extent.length !== 4) return null;
    const [west, north, east, south] = extent;
    return { south, west, north, east };
}

function toResult(feature: PhotonFeature): GeocodeResult | null {
    const coordinates = feature.geometry?.coordinates;
    if (!coordinates || coordinates.length < 2) return null;
    const properties = feature.properties ?? {};
    return {
        formattedAddress: formatAddress(properties),
        position: { lat: coordinates[1], lng: coordinates[0] },
        viewport: toViewport(properties.extent),
        name: properties.name,
    };
}

export interface PhotonGeocoderOptions {
    /** Base URL of a Photon instance. Override with a self-hosted deployment. */
    photonUrl?: string;
    /** UI language for returned names. */
    language?: string;
}

export function createMapLibreGeocoder(options?: PhotonGeocoderOptions): GeocodingProvider {
    const base = (options?.photonUrl ?? DEFAULT_PHOTON_URL).replace(/\/$/, '');
    const language = options?.language ?? 'en';

    // resolveSuggestion() has to answer without a second network call, so the
    // full result is kept alongside the opaque id handed to the caller.
    const resolved = new Map<string, GeocodeResult>();

    const search = async (query: string, limit: number, suggest?: SuggestOptions): Promise<PhotonFeature[]> => {
        const params = new URLSearchParams({ q: query, limit: String(limit), lang: language });
        const bias = suggest?.biasBounds;
        if (bias) {
            params.set('bbox', `${bias.west},${bias.south},${bias.east},${bias.north}`);
            params.set('lat', String((bias.south + bias.north) / 2));
            params.set('lon', String((bias.west + bias.east) / 2));
        }

        const response = await fetch(`${base}/api/?${params.toString()}`);
        if (!response.ok) throw new Error(`Photon search failed: ${response.status}`);
        const body = await response.json() as { features?: PhotonFeature[] };
        let features = body.features ?? [];

        // Photon has no country parameter, so country restriction is applied
        // client-side against the returned countrycode.
        const countries = suggest?.countries?.map(code => code.toLowerCase());
        if (countries?.length) {
            features = features.filter(f => countries.includes((f.properties?.countrycode ?? '').toLowerCase()));
        }
        if (suggest?.addressesOnly) {
            features = features.filter(f => ADDRESS_TYPES.has(f.properties?.type ?? ''));
        }
        return features;
    };

    return {
        id: 'photon',

        async reverseGeocode(position: LatLng): Promise<GeocodeResult | null> {
            try {
                const fromBackend = await backendGeocodingProvider.reverseGeocode(position);
                if (fromBackend) return fromBackend;
            } catch (error) {
                console.warn('Backend reverse geocode failed, falling back to Photon:', error);
            }

            const params = new URLSearchParams({
                lat: String(position.lat),
                lon: String(position.lng),
                lang: language,
                limit: '1',
            });
            const response = await fetch(`${base}/reverse?${params.toString()}`);
            if (!response.ok) return null;
            const body = await response.json() as { features?: PhotonFeature[] };
            return body.features?.length ? toResult(body.features[0]) : null;
        },

        async geocode(query: string): Promise<GeocodeResult[]> {
            if (!query.trim()) return [];
            try {
                const fromBackend = await backendGeocodingProvider.geocode(query);
                if (fromBackend.length) return fromBackend;
            } catch (error) {
                console.warn('Backend geocode failed, falling back to Photon:', error);
            }

            const features = await search(query, 5);
            return features.map(toResult).filter((r): r is GeocodeResult => !!r);
        },

        async suggest(query: string, suggestOptions?: SuggestOptions): Promise<AddressSuggestion[]> {
            if (!query.trim()) return [];
            const features = await search(query, 8, suggestOptions);

            return features.flatMap(feature => {
                const result = toResult(feature);
                if (!result) return [];
                const properties = feature.properties ?? {};
                // OSM ids are absent for some Photon records, so fall back to the
                // coordinate — the id only has to be unique within one response.
                const id = properties.osm_type && properties.osm_id
                    ? `${properties.osm_type}${properties.osm_id}`
                    : `${result.position.lat},${result.position.lng}`;
                resolved.set(id, result);
                return [{
                    id,
                    label: primaryLabel(properties),
                    secondaryLabel: secondaryLabel(properties),
                }];
            });
        },

        async resolveSuggestion(suggestion: AddressSuggestion): Promise<GeocodeResult | null> {
            return resolved.get(suggestion.id) ?? null;
        },

        attachAutocomplete(_input: HTMLInputElement, _options: AutocompleteOptions): AutocompleteHandle | null {
            // Photon is a JSON API with no UI component. Callers render their
            // own dropdown from suggest().
            return null;
        },
    };
}
