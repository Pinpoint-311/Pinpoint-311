/**
 * Esri geocoding behind the GeocodingProvider interface.
 *
 * Deliberately implemented with plain fetch against the ArcGIS REST Geocoding
 * API rather than through `esri/rest/locator`. Two reasons, and the second is
 * the point of this whole adapter:
 *
 *  1. It needs no SDK, so a town rendering with MapLibre or Google can still
 *     geocode against Esri. registry.ts resolves geocoding independently of
 *     rendering precisely so that combination is possible.
 *  2. The locator URL is configurable. Most New Jersey counties publish their
 *     own composite address locator on their ArcGIS Server, built from the
 *     county's authoritative address points and road centrelines. That locator
 *     knows about new subdivisions, private lanes and municipal complexes months
 *     or years before Esri's or Google's world service does, and it is the
 *     difference between "123 Sunset Ridge Ct" resolving to the right driveway
 *     and resolving to the middle of a state highway.
 */

import {
    AddressSuggestion,
    GeocodeResult,
    GeocodingProvider,
    LatLng,
    LatLngBounds,
    SuggestOptions,
} from '../../types';

/* eslint-disable @typescript-eslint/no-explicit-any */

export const ESRI_WORLD_GEOCODER =
    'https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer';

export interface EsriGeocoderOptions {
    /** Locator service base URL, without the /suggest or /findAddressCandidates. */
    serviceUrl?: string;
    /** ArcGIS API key or token. Omit for an unsecured on-prem locator. */
    token?: string | null;
    /** Default country filter when SuggestOptions does not supply one. */
    countryCodes?: string[];
    /** Passed through to the service; useful for locators with custom categories. */
    category?: string | null;
    maxSuggestions?: number;
    maxCandidates?: number;
}

function normaliseUrl(url: string): string {
    return url.replace(/\/+$/, '');
}

/**
 * SuggestOptions.biasBounds, as a *bias*.
 *
 * This used to become ArcGIS's `searchExtent`, which reads like the equivalent
 * of Google's `locationBias` and is not: `searchExtent` is a hard filter,
 * discarding every candidate outside the envelope. The caller passes the map's
 * current viewport, so as soon as a resident zoomed in -- or simply dropped a
 * pin, which pans and zooms to it -- the envelope was a couple of hundred
 * metres across and *every* query returned zero suggestions. Verified against
 * the World locator: "main st" with the town's extent returns 3 suggestions and
 * with a street-level extent returns 0. That is the whole of "address
 * autocomplete does not work on Esri" -- the requests were going out and coming
 * back 200 with an empty list.
 *
 * `location` is the parameter that means what the interface means: a point that
 * ranks nearby candidates first without excluding anything. Same principle the
 * server-side dispatcher already states in geocode_dispatch.py -- a resident can
 * legitimately report something just over the border, on a shared road or in a
 * county park, so the town's own box must not be a restriction.
 *
 * wkid 4326 is stated explicitly because a locator's own default SR is
 * frequently State Plane, and an unlabelled point would be read in that SR's
 * units. Country codes stay a real filter; those the caller does mean.
 */
function biasLocation(bounds: LatLngBounds): string {
    return JSON.stringify({
        x: (bounds.west + bounds.east) / 2,
        y: (bounds.south + bounds.north) / 2,
        spatialReference: { wkid: 4326 },
    });
}

function candidateToResult(candidate: any): GeocodeResult | null {
    const location = candidate?.location;
    if (typeof location?.x !== 'number' || typeof location?.y !== 'number') return null;

    const extent = candidate.extent;
    return {
        formattedAddress: candidate.address ?? candidate.attributes?.Match_addr ?? '',
        position: { lat: location.y, lng: location.x },
        viewport: extent
            ? { south: extent.ymin, west: extent.xmin, north: extent.ymax, east: extent.xmax }
            : null,
        name: candidate.attributes?.PlaceName || undefined,
    };
}

export function createEsriGeocoder(options: EsriGeocoderOptions = {}): GeocodingProvider {
    const base = normaliseUrl(options.serviceUrl || ESRI_WORLD_GEOCODER);

    // magicKey is the only thing that makes a suggestion resolve to the exact
    // record the user picked, but AddressSuggestion.id is a plain string, so the
    // token travels as the id and is round-tripped straight back to the service.
    const suggestionText = new Map<string, string>();

    const call = async (operation: string, params: Record<string, string | undefined>): Promise<any> => {
        const query = new URLSearchParams({ f: 'json' });
        for (const [key, value] of Object.entries(params)) {
            if (value !== undefined && value !== '') query.set(key, value);
        }
        if (options.token) query.set('token', options.token);

        const response = await fetch(`${base}/${operation}?${query.toString()}`, {
            method: 'GET',
            // An on-prem county locator is usually a different origin with CORS
            // enabled but no credential support; never send cookies.
            credentials: 'omit',
        });
        if (!response.ok) throw new Error(`Esri geocoder ${operation} failed: ${response.status}`);

        const body = await response.json();
        // ArcGIS REST reports failures with HTTP 200 and an `error` member.
        if (body?.error) throw new Error(body.error.message || `Esri geocoder ${operation} failed`);
        return body;
    };

    return {
        id: 'esri',

        async reverseGeocode(position: LatLng): Promise<GeocodeResult | null> {
            const body = await call('reverseGeocode', {
                location: JSON.stringify({ x: position.lng, y: position.lat, spatialReference: { wkid: 4326 } }),
                outSR: '4326',
            });
            const address = body?.address;
            const location = body?.location;
            if (!address) return null;
            return {
                formattedAddress: address.LongLabel || address.Match_addr || '',
                position: typeof location?.y === 'number'
                    ? { lat: location.y, lng: location.x }
                    : position,
            };
        },

        async geocode(query: string): Promise<GeocodeResult[]> {
            if (!query.trim()) return [];
            const body = await call('findAddressCandidates', {
                SingleLine: query,
                outFields: 'Match_addr,PlaceName,Addr_type',
                // Force WGS84 out regardless of the locator's native SR — the
                // interface only speaks lat/lng and conversions stay in here.
                outSR: '4326',
                maxLocations: String(options.maxCandidates ?? 10),
                countryCode: options.countryCodes?.join(',') || undefined,
            });
            return ((body?.candidates || []) as any[])
                .map(candidateToResult)
                .filter((r): r is GeocodeResult => r !== null);
        },

        async suggest(query: string, suggestOptions?: SuggestOptions): Promise<AddressSuggestion[]> {
            if (!query.trim()) return [];
            const countries = suggestOptions?.countries?.length
                ? suggestOptions.countries
                : options.countryCodes;

            const body = await call('suggest', {
                text: query,
                maxSuggestions: String(options.maxSuggestions ?? 8),
                countryCode: countries?.join(',') || undefined,
                location: suggestOptions?.biasBounds ? biasLocation(suggestOptions.biasBounds) : undefined,
                category: suggestOptions?.addressesOnly
                    ? 'Address,Postal'
                    : (options.category || undefined),
            });

            suggestionText.clear();
            return ((body?.suggestions || []) as any[])
                .filter(s => !s.isCollection)
                .map(s => {
                    const id = String(s.magicKey ?? s.text);
                    suggestionText.set(id, s.text);
                    // Esri returns one flat string; split off the first comma so
                    // the caller's dropdown gets the same two-line shape Google
                    // gives via structured_formatting.
                    const comma = String(s.text).indexOf(',');
                    return comma > 0
                        ? {
                            id,
                            label: String(s.text).slice(0, comma),
                            secondaryLabel: String(s.text).slice(comma + 1).trim(),
                        }
                        : { id, label: String(s.text) };
                });
        },

        async resolveSuggestion(suggestion: AddressSuggestion): Promise<GeocodeResult | null> {
            const text = suggestionText.get(suggestion.id)
                ?? [suggestion.label, suggestion.secondaryLabel].filter(Boolean).join(', ');

            const body = await call('findAddressCandidates', {
                SingleLine: text,
                magicKey: suggestion.id,
                outFields: 'Match_addr,PlaceName,Addr_type',
                outSR: '4326',
                maxLocations: '1',
            });
            return candidateToResult((body?.candidates || [])[0]) ?? null;
        },

        // attachAutocomplete is intentionally absent. Esri's Search widget builds
        // and owns its own <input> inside a container it controls; it cannot be
        // bound to a caller-supplied input element, and pulling it in would drag
        // the whole SDK into a geocoder that otherwise needs none. Callers use
        // suggest() + their own list, which is what AutocompleteHandle returning
        // null is for.
    };
}
