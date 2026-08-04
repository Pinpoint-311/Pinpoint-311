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

    /**
     * `gm_authFailure` is Google's documented way of saying "this key is not
     * allowed from this site". It is a global the SDK *calls*: it does not
     * throw, does not reject the loader, and does not fail map construction.
     * The map object comes back intact and the tiles never arrive -- which is
     * the grey map, and the reason nothing else here notices.
     *
     * Chained rather than replaced, and put back by `stop()`. A hook left
     * behind would route every later failure into a check that has finished.
     */
    watchAuthFailure() {
        type Host = { gm_authFailure?: (() => void) | undefined };
        const host = window as unknown as Host;
        const previous = host.gm_authFailure;
        let failed = false;

        host.gm_authFailure = () => {
            failed = true;
            try { previous?.(); } catch { /* not ours to care about */ }
        };

        return {
            failed: () => failed,
            stop: () => { host.gm_authFailure = previous; },
        };
    },
};
