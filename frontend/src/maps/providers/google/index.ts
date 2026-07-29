/**
 * Google provider registration.
 *
 * This module (and everything it imports, including
 * @googlemaps/markerclusterer) is only pulled in when a town has selected
 * Google — src/maps/registry.ts reaches it through a dynamic import.
 */

import { loadGoogleMaps } from '../../../utils/googleMaps';
import {
    GeocodingProvider,
    MapInitOptions,
    MapProviderConfig,
    MapProviderFactory,
    MapRenderer,
} from '../../types';
import { createGoogleGeocoder } from './geocoder';
import { GOOGLE_CAPABILITIES, GoogleMapRenderer } from './renderer';

export const googleMapProvider: MapProviderFactory = {
    id: 'google',
    displayName: 'Google Maps',
    capabilities: GOOGLE_CAPABILITIES,

    load(config: MapProviderConfig): Promise<void> {
        if (!config.apiKey) return Promise.reject(new Error('Google Maps API key is required'));
        return loadGoogleMaps(config.apiKey);
    },

    createRenderer(container: HTMLElement, _config: MapProviderConfig, options: MapInitOptions): MapRenderer {
        return new GoogleMapRenderer(container, options);
    },

    createGeocoder(_config: MapProviderConfig): GeocodingProvider {
        return createGoogleGeocoder();
    },
};
