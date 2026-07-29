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
import { GeocodeResult, GeocodingProvider, LatLng } from '../types';

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
};
