/**
 * Geocoding through Pinpoint's own backend.
 *
 * The backend already has Google and OSM/Nominatim geocoding paths behind
 * /gis/geocode, and it meters every call for the cost-monitoring page. Routing
 * through it rather than straight to a vendor SDK is what keeps that number
 * honest, so this provider is normally chained ahead of the render provider's
 * own geocoder.
 *
 * No SDK, no API key, no bundle cost — it is safe to include unconditionally.
 */

import { api } from '../../services/api';
import { AddressSuggestion, GeocodeResult, GeocodingProvider, LatLng } from '../types';

export const backendGeocodingProvider: GeocodingProvider = {
    id: 'backend',

    async reverseGeocode(position: LatLng): Promise<GeocodeResult | null> {
        const result = await api.reverseGeocode(position.lat, position.lng);
        if (!result?.formatted_address) return null;
        return {
            formattedAddress: result.formatted_address,
            position: { lat: result.lat ?? position.lat, lng: result.lng ?? position.lng },
        };
    },

    async geocode(query: string): Promise<GeocodeResult[]> {
        const result = await api.geocodeAddress(query);
        if (!result || typeof result.lat !== 'number') return [];
        return [{
            formattedAddress: result.formatted_address,
            position: { lat: result.lat, lng: result.lng },
        }];
    },

    /**
     * One confirmed match for what was typed, so the address box still does
     * something when the provider's own autocomplete is unavailable.
     *
     * This is not autocomplete. It cannot complete a half-typed street, and it
     * only answers once the text resolves to a real address. It exists because
     * the alternative was nothing: `suggest` and `attachAutocomplete` were the
     * only calls in the geocoding layer with no fallback, so a Places API that
     * is not enabled on a town's key -- or a town not on Google at all -- left
     * a dead input, while every other lookup on the page carried on working
     * through this same provider.
     *
     * Deliberately quiet on failure. A suggestion list that throws would take
     * the intake form with it, and not finding an address is a normal answer to
     * half of an address.
     */
    async suggest(query: string): Promise<AddressSuggestion[]> {
        const trimmed = query.trim();
        // Below this it is a fragment, and geocoding a fragment returns a
        // confident match for the wrong street.
        if (trimmed.length < 5) return [];
        try {
            const results = await api.geocodeAddress(trimmed);
            if (!results || typeof results.lat !== 'number') return [];
            return [{
                id: `backend:${results.lat},${results.lng}`,
                label: results.formatted_address,
            }];
        } catch {
            return [];
        }
    },

    async resolveSuggestion(suggestion: AddressSuggestion): Promise<GeocodeResult | null> {
        // The id carries the coordinates this provider already resolved, so
        // picking a suggestion costs no second lookup.
        const match = /^backend:(-?[\d.]+),(-?[\d.]+)$/.exec(suggestion.id);
        if (!match) return null;
        return {
            formattedAddress: suggestion.label,
            position: { lat: Number(match[1]), lng: Number(match[2]) },
        };
    },
};
